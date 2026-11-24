from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    agreement_vismasign_auto_create_agreement_on_confirm = fields.Boolean(
        string="Auto-create Agreement on Order Confirmation",
        config_parameter="agreement_vismasign.auto_create_agreement_on_confirm",
    )
