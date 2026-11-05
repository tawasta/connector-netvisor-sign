import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AgreementVismasignSigner(models.Model):
    _name = "agreement.vismasign.signer"
    _description = "Agreement Visma Sign Signer"
    _order = "id"
    _check_company_auto = True

    agreement_id = fields.Many2one(
        comodel_name="agreement",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="agreement_id.company_id",
        store=True,
        index=True,
    )
    role = fields.Selection(
        selection=[
            ("customer", "Customer"),
            ("company", "Additional signer"),
        ],
        required=True,
        default="company",
        readonly=True,
        copy=False,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Signer",
        required=True,
        check_company=True,
        domain=[("email", "!=", False)],
    )
    # Stored so that matching the invitations in Visma Sign keeps working
    # even if the contact's email is changed after the invitation was sent.
    # Precomputed because the field is required: rows created in code without
    # an email would otherwise be inserted empty and violate the constraint.
    email = fields.Char(
        compute="_compute_email",
        store=True,
        readonly=False,
        required=True,
        precompute=True,
    )
    invitation_uuid = fields.Char(readonly=True, copy=False)
    status = fields.Char(readonly=True, copy=False)

    @api.depends("partner_id")
    def _compute_email(self):
        for signer in self:
            signer.email = signer.partner_id.email

    @staticmethod
    def _normalize_email(email):
        return (email or "").strip().lower()

    def _apply_vismasign_invitations(self, invitations):
        """Store uuid and status of the Visma Sign invitations on the signers.

        Visma Sign does not document the order of the invitations, so they
        are matched to the signers by email.

        :param invitations: ``invitations`` list of a Visma Sign document
        """
        invitation_by_email = {
            self._normalize_email(invitation.get("email")): invitation
            for invitation in invitations
            if isinstance(invitation, dict) and invitation.get("email")
        }
        for signer in self:
            invitation = invitation_by_email.get(self._normalize_email(signer.email))
            if not invitation:
                _logger.warning(
                    "No Visma Sign invitation matches signer %s of agreement %s",
                    signer.id,
                    signer.agreement_id.id,
                )
                continue
            vals = {
                "invitation_uuid": invitation.get("uuid"),
                "status": invitation.get("status"),
            }
            if any(signer[field] != value for field, value in vals.items()):
                signer.write(vals)
