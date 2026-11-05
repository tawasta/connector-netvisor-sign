from odoo import fields, models


class AgreementType(models.Model):
    _inherit = "agreement.type"

    report_id = fields.Many2one(
        comodel_name="ir.actions.report",
        string="Netvisor Sign Report",
        domain=[("model", "in", ["agreement", "sale.order"])],
        help="Report used to render the document sent to Netvisor Sign for "
        "agreements of this type: an agreement report, or a sale order report "
        "rendered from the quotation the agreement was created from.",
    )
