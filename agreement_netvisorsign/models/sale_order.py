from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        res = super().action_confirm()

        # sudo: reading a system parameter requires group_system, which the
        # calling user (e.g. a salesperson) does not necessarily have
        auto_create = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("agreement_vismasign.auto_create_agreement_on_confirm")
        )
        if auto_create:
            for order in self:
                if order.agreement_type_id and not order.agreement_id:
                    order.action_create_agreement()

        return res

    def action_create_agreement(self):
        """Create the agreement to be signed for this quotation.

        The agreement type set on the order (and the Netvisor Sign report
        configured on it) determines which document is generated once the
        agreement is sent for signature.
        """
        self.ensure_one()

        if self.agreement_id:
            raise UserError(_("This order is already linked to an agreement."))

        if not self.agreement_type_id:
            raise UserError(
                _("Set an agreement type on the order before creating the agreement.")
            )

        agreement = self.env["agreement"].create(self._prepare_agreement_vals())
        self.agreement_id = agreement.id

        return agreement

    def _prepare_agreement_vals(self):
        self.ensure_one()
        return {
            "name": _("Agreement for %s", self.name),
            "code": self.name,
            "partner_id": self.partner_id.id,
            "agreement_type_id": self.agreement_type_id.id,
            "company_id": self.company_id.id,
        }
