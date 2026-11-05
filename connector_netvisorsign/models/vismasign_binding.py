from odoo import fields, models


class VismaSignBinding(models.Model):
    _name = "vismasign.binding"
    _description = "Netvisor Sign Binding Log"
    _inherit = "external.binding"
    _order = "id DESC"

    backend_id = fields.Many2one("vismasign.backend", required=True)
    method = fields.Char()
    endpoint = fields.Char()
    payload = fields.Text()
    response = fields.Text()
    status_code = fields.Integer()
    successful = fields.Boolean()
