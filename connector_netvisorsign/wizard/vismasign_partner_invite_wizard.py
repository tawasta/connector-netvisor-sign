import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class VismaSignPartnerInviteWizard(models.TransientModel):
    _name = "vismasign.partner.invite.wizard"
    _description = "Netvisor Sign Partner Invite (Business ID flow)"

    backend_id = fields.Many2one("vismasign.backend", required=True, readonly=True)

    # REQUIRED for search (and create if missing)
    business_id = fields.Char(string="Business ID (Y-tunnus)", required=True)

    # REQUIRED for create organization if it doesn't exist
    organization_name = fields.Char(string="Organization name", required=True)
    postal_address = fields.Char(string="Postal address", required=False)
    postal_code = fields.Char(string="Postal code", required=False)
    municipality = fields.Char(string="Municipality", required=False)

    # REQUIRED admin block for create organization
    admin_identifier = fields.Char(string="Admin identifier", required=False)
    admin_first_name = fields.Char(string="Admin first name", required=False)
    admin_last_name = fields.Char(string="Admin last name", required=False)
    admin_email = fields.Char(string="Admin email", required=False)

    # REQUIRED for request access (invite)
    lang = fields.Selection(
        [("fi", "Finnish"), ("en", "English"), ("sv", "Swedish")],
        string="Language",
        default="fi",
        required=True,
    )
    message = fields.Text(
        string="Message",
        required=True,
        default=lambda self: _(
            "Hei!\n\nVoitteko hyväksyä kutsun, jotta voimme liittää organisaationne Netvisor Sign -partnerimalliin "  # noqa: E501
            "ja käyttää allekirjoituksia suoraan Odoosta?\n\nKiitos!"
        ),
    )

    def action_send(self):
        self.ensure_one()
        backend = self.backend_id

        if backend.auth_mode != "partner":
            raise UserError(_("Backend is not in Partner mode."))

        result = backend.partner_invite_or_create_by_business_id(
            business_id=(self.business_id or "").strip(),
            message=(self.message or "").strip(),
            organization_name=(self.organization_name or "").strip(),
            postal_address=(self.postal_address or "").strip(),
            postal_code=(self.postal_code or "").strip(),
            municipality=(self.municipality or "").strip(),
            admin_identifier=(self.admin_identifier or "").strip(),
            admin_first_name=(self.admin_first_name or "").strip(),
            admin_last_name=(self.admin_last_name or "").strip(),
            admin_email=(self.admin_email or "").strip(),
            lang=self.lang,
        )

        action = result.get("action")
        org_uuid = result.get("organization_uuid")

        if action == "invite_sent":
            msg = _("Access request sent to Netvisor Sign for organization %s.") % org_uuid
            title = _("Invitation sent")
        elif action == "already_authorized":
            msg = _("Already authorized. Set as_organization_uuid to %s.") % org_uuid
            title = _("Already authorized")
        elif action == "created":
            msg = (
                _(
                    "Organization created in Netvisor Sign (%s). Set as_organization_uuid automatically."  # noqa: E501
                )
                % org_uuid
            )
            title = _("Organization created")
        else:
            msg = _("Done.")
            title = _("Netvisor Sign")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": msg,
                "sticky": False,
            },
        }
