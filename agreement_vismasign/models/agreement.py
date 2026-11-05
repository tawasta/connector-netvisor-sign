import base64
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class Agreement(models.Model):
    _inherit = "agreement"

    vismasign_document_uuid = fields.Char(readonly=True, copy=False)
    vismasign_file_uuid = fields.Char(readonly=True, copy=False)
    vismasign_invitation_uuid = fields.Char(readonly=True, copy=False)
    vismasign_status = fields.Char(readonly=True, copy=False, tracking=True)
    vismasign_last_check = fields.Datetime(readonly=True, copy=False)
    vismasign_signer_ids = fields.One2many(
        comodel_name="agreement.vismasign.signer",
        inverse_name="agreement_id",
        string="Visma Sign Signers",
        copy=False,
        help="People who sign in addition to the customer. The customer is "
        "added automatically. Available when the Visma Sign backend allows "
        "multiple signers.",
    )
    vismasign_allow_multiple_signers = fields.Boolean(
        compute="_compute_vismasign_allow_multiple_signers",
        help="Technical field: the Visma Sign backend of the company allows "
        "several signers per document.",
    )

    @api.depends("company_id")
    def _compute_vismasign_allow_multiple_signers(self):
        # sudo: vismasign.backend is restricted to
        # connector.group_connector_manager because it stores API
        # credentials; only the multiple signers flag is read from it
        backends = (
            self.env["vismasign.backend"]
            .sudo()
            .search([("company_id", "in", self.company_id.ids)])
        )
        # Same backend as the one used when sending: the first of the company
        backend_by_company = {}
        for backend in backends:
            backend_by_company.setdefault(backend.company_id, backend)
        for agreement in self:
            backend = backend_by_company.get(agreement.company_id)
            agreement.vismasign_allow_multiple_signers = bool(
                backend and backend.allow_multiple_signers
            )

    def action_vismasign_send(self):
        """
        Send the agreement PDF to Visma Sign for electronic signing.

        Workflow:
        1. Determine the signers: the customer, and the additional signers
           added on the agreement when the backend allows multiple signers.
        2. Determine the report to use: the report configured on the
           agreement's type.
        3. Render the agreement PDF with that report and attach it to the
           agreement as an audit-trail copy of what was sent.
        4. Create a document in Visma Sign.
        5. Upload the PDF file to the created document.
        6. Send the signing invitation(s). The customer-only flow is a single
           invitation tracked by its UUID; with additional signers all
           invitations are sent in one request and tracked on the signers.
        7. Store returned UUIDs and the current signing status.

        Raises:
            UserError: If the agreement is a template, no backend is configured,
                       no customer email exists, the signers are invalid, or
                       no report could be resolved or rendered.
        """
        self.ensure_one()

        if self.is_template:
            raise UserError(_("A template agreement cannot be sent for signature."))

        if not self.partner_id.email:
            raise UserError(_("The customer does not have an email address."))

        # Sending again would create a second document and invite the signers
        # twice, and Visma Sign cannot add invitations to a document afterwards
        if self.vismasign_document_uuid:
            raise UserError(_("This agreement has already been sent to Visma Sign."))

        # sudo: vismasign.backend is restricted to
        # connector.group_connector_manager because it stores API
        # credentials; the calling user only needs to trigger the send,
        # not manage the backend configuration
        backend = (
            self.env["vismasign.backend"]
            .sudo()
            .search(
                [("company_id", "=", self.company_id.id)],
                limit=1,
            )
        )
        if not backend:
            raise UserError(
                _("No Visma Sign backend is configured for company %s.")
                % self.company_id.display_name
            )

        signers = self._prepare_vismasign_signers(backend)

        report = self._get_vismasign_report()
        report_records = self._get_vismasign_report_records(report)

        try:
            # sudo: rendering the report is a technical action; the calling
            # user only needs read access to the agreement, not to the report
            # action itself
            pdf = (
                self.env["ir.actions.report"]
                .sudo()
                ._render_qweb_pdf(
                    report,
                    report_records.ids,
                )[0]
            )
        except Exception as exc:
            _logger.exception(
                "Failed to render report %s for agreement %s",
                report.report_name,
                self.id,
            )
            raise UserError(
                _("Failed to render the configured agreement report: %s")
                % report.display_name
            ) from exc

        self.env["ir.attachment"].create(
            {
                "name": "Agreement - %s (unsigned).pdf" % self.code,
                "res_model": self._name,
                "res_id": self.id,
                "company_id": self.company_id.id,
                "type": "binary",
                "datas": base64.b64encode(pdf),
                "mimetype": "application/pdf",
            }
        )

        payload = {
            "document": {
                "name": self.display_name,
            }
        }

        document_uuid = backend.create_document(payload)
        file_uuid = backend.add_file(document_uuid, f"{self.code}.pdf", pdf)
        if signers:
            status_vals = self._send_vismasign_to_signers(
                backend, document_uuid, signers
            )
        else:
            status_vals = self._send_vismasign_to_customer(backend, document_uuid)

        self.write(
            {
                "vismasign_document_uuid": document_uuid,
                "vismasign_file_uuid": file_uuid,
                "vismasign_last_check": fields.Datetime.now(),
                **status_vals,
            }
        )

        self.message_post(
            body=_("The agreement was sent to Visma Sign for electronic signing."),
            subtype_xmlid="mail.mt_note",
        )

    def _send_vismasign_to_customer(self, backend, document_uuid):
        """Send the single customer invitation and return the status values."""
        invitation_data = backend.send_invitation(document_uuid, self.partner_id.email)

        invitation_uuid = False
        invitation_status = False

        if isinstance(invitation_data, list) and invitation_data:
            invitation_uuid = invitation_data[0].get("uuid")
            invitation_status = invitation_data[0].get("status")
        elif isinstance(invitation_data, dict):
            invitation_uuid = invitation_data.get("uuid")
            invitation_status = invitation_data.get("status")

        return {
            "vismasign_invitation_uuid": invitation_uuid,
            "vismasign_status": invitation_status,
        }

    def _send_vismasign_to_signers(self, backend, document_uuid, signers):
        """Send all invitations in one request and return the status values."""
        backend.send_invitation(document_uuid, signers.mapped("email"))

        # Visma Sign creates every invitation as "waiting-for-send"; the
        # status marks the signer as invited, so the cron keeps tracking it
        signers.write({"status": "waiting-for-send"})
        document = self._get_vismasign_document_after_send(backend, document_uuid)
        signers._apply_vismasign_invitations(document.get("invitations") or [])

        return {"vismasign_status": document.get("status") or "pending"}

    def _get_vismasign_document_after_send(self, backend, document_uuid):
        """Fetch the document so the invitations can be matched to the signers.

        The invitations already exist in Visma Sign at this point. Failing here
        would roll back their saved state and a retry would send duplicates,
        so an error is only logged; the cron fills in the missing details.
        """
        try:
            return backend.get_document(document_uuid)
        except UserError as exc:
            _logger.warning(
                "Failed to fetch Visma Sign document %s after sending agreement %s: %s",  # noqa: E501
                document_uuid,
                self.id,
                exc,
            )
            return {}

    def _prepare_vismasign_signers(self, backend):
        """Return the signers to invite, or nothing for a customer-only request.

        Without additional signers the request goes to the customer only, as
        before. With additional signers the customer's signer line is created
        too, so all invitations are tracked on the signers.

        Raises:
            UserError: If additional signers were added but the backend does
                       not allow multiple signers, or two signers share an
                       email address.
        """
        self.ensure_one()

        no_signers = self.env["agreement.vismasign.signer"]
        company_signers = self.vismasign_signer_ids.filtered(
            lambda signer: signer.role == "company"
        )
        if not company_signers:
            return no_signers

        # Not ignored silently, or the user would think they were invited
        if not backend.allow_multiple_signers:
            raise UserError(
                _(
                    "The Visma Sign backend does not allow multiple signers. "
                    "Remove the additional signers to send the signature "
                    "request to the customer only."
                )
            )

        customer_signer = self.env["agreement.vismasign.signer"].create(
            {
                "agreement_id": self.id,
                "role": "customer",
                "partner_id": self.partner_id.id,
            }
        )
        signers = customer_signer | company_signers

        emails = [signers._normalize_email(email) for email in signers.mapped("email")]
        if len(set(emails)) != len(emails):
            raise UserError(
                _(
                    "Each signer needs a different email address. Remove the "
                    "duplicate or change the email address."
                )
            )

        return signers

    def _get_vismasign_report(self):
        """Resolve the report used to render the document sent to Visma Sign.

        Each agreement type (e.g. lease vs. sale agreements, or the
        different sale agreement templates) configures its own report, so
        different types can use different documents.
        """
        self.ensure_one()

        report = self.agreement_type_id.report_id
        if not report:
            raise UserError(
                _(
                    "No Visma Sign report is configured for agreement type "
                    "%(type)s. Set the report on the agreement type."
                )
                % {"type": self.agreement_type_id.display_name or _("(none)")}
            )
        return report

    def _get_vismasign_report_records(self, report):
        """Return the records the Visma Sign report is rendered for.

        The report is rendered for records of its own model: the agreement
        itself, or the quotation the agreement was created from. Rendering a
        sale order report with the agreement id would print an unrelated
        order, so the quotation is resolved through ``agreement_id``.
        """
        self.ensure_one()

        if report.model == self._name:
            return self

        if report.model == "sale.order":
            orders = self.env["sale.order"].search([("agreement_id", "=", self.id)])
            if len(orders) != 1:
                raise UserError(
                    _(
                        "The Visma Sign report %(report)s is rendered from the "
                        "quotation, so the agreement must be linked to exactly "
                        "one quotation (now linked to %(count)s)."
                    )
                    % {"report": report.display_name, "count": len(orders)}
                )
            return orders

        raise UserError(
            _(
                "The Visma Sign report %(report)s is for model %(model)s. Only "
                "agreement and sale order reports are supported."
            )
            % {"report": report.display_name, "model": report.model}
        )

    @api.model
    def cron_update_vismasign_status(self):
        """
        Scheduled task that synchronizes Visma Sign signing statuses to agreements.

        Workflow:
        - Find agreements that have a document UUID and are not yet marked as signed.
        - Fetch the latest status from Visma Sign: the invitation status, or for
          agreements with several signers the document status.
        - Update the local status and timestamp.
        - When the status becomes 'signed' (for several signers: every signer
          has signed):
            * download the signed PDF and store it as an attachment
            * post a chatter message
        """
        # sudo: vismasign.backend is restricted to
        # connector.group_connector_manager; this cron runs as a
        # technical/scheduled action, not as an end-user browsing backend
        # configuration
        backends = self.env["vismasign.backend"].sudo().search([])

        for backend in backends:
            agreements = self.search(
                [
                    "|",
                    ("vismasign_invitation_uuid", "!=", False),
                    ("vismasign_signer_ids.status", "!=", False),
                    ("company_id", "=", backend.company_id.id),
                    ("vismasign_status", "!=", "signed"),
                ]
            )

            for agreement in agreements:
                try:
                    status = agreement._update_vismasign_status(backend)
                except UserError as exc:
                    _logger.warning(
                        "Failed to fetch Visma Sign status for agreement %s: %s",
                        agreement.id,
                        exc,
                    )
                    continue

                if status != "signed" or not agreement.vismasign_document_uuid:
                    continue

                try:
                    self._process_vismasign_signed(agreement, backend)
                except Exception:
                    # One malformed record must not roll back the status
                    # updates already applied to the other agreements in
                    # this cron run.
                    _logger.exception(
                        "Failed to process the signed Visma Sign document for "
                        "agreement %s",
                        agreement.id,
                    )

    def _update_vismasign_status(self, backend):
        """Fetch the signing status from Visma Sign, store it and return it.

        An agreement sent to the customer only is tracked by its single
        invitation. An agreement sent to several signers is tracked by its
        document, which is signed only when every signer has signed; the
        status of each signer is updated too.
        """
        self.ensure_one()

        invited_signers = self.vismasign_signer_ids.filtered("status")
        if invited_signers:
            data = backend.get_document(self.vismasign_document_uuid)
            invited_signers._apply_vismasign_invitations(data.get("invitations") or [])
        else:
            data = backend.get_invitation_status(self.vismasign_invitation_uuid)

        status = data.get("status")
        self.write(
            {
                "vismasign_status": status,
                "vismasign_last_check": fields.Datetime.now(),
            }
        )
        return status

    def _process_vismasign_signed(self, agreement, backend):
        """Attach the signed PDF (once) and notify followers."""
        # Technical, non-translated name so the lookup below stays stable
        # regardless of the user's language.
        attachment_name = "Agreement - %s (signed).pdf" % agreement.code

        existing_attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", agreement._name),
                ("res_id", "=", agreement.id),
                ("name", "=", attachment_name),
            ],
            limit=1,
        )

        if not existing_attachment:
            try:
                signed_pdf = backend.get_document_file(
                    agreement.vismasign_document_uuid,
                    index=0,
                )
            except UserError as exc:
                _logger.warning(
                    "Failed to download signed Visma Sign document for agreement %s: %s",  # noqa: E501
                    agreement.id,
                    exc,
                )
                return

            if not signed_pdf:
                _logger.warning(
                    "Empty signed document content for agreement %s",
                    agreement.id,
                )
                return

            self.env["ir.attachment"].create(
                {
                    "name": attachment_name,
                    "res_model": agreement._name,
                    "res_id": agreement.id,
                    "company_id": agreement.company_id.id,
                    "type": "binary",
                    "datas": base64.b64encode(signed_pdf),
                    "mimetype": "application/pdf",
                }
            )

        message_body = (
            Markup(
                "<p>The agreement <strong>%s</strong> has been signed "
                "in Visma Sign.</p>"
            )
            % agreement.display_name
        )

        agreement.message_post(
            body=message_body,
            subtype_xmlid="mail.mt_comment",
        )
