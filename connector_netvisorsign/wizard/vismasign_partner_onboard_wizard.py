import json
import logging
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class VismaSignPartnerOnboardWizard(models.TransientModel):
    _name = "vismasign.partner.onboard.wizard"
    _description = "Netvisor Sign Partner Organization Search"

    backend_id = fields.Many2one("vismasign.backend", required=True, readonly=True)
    business_id = fields.Char(string="Business ID (Y-tunnus)", required=True)

    line_ids = fields.One2many(
        "vismasign.partner.onboard.wizard.line",
        "wizard_id",
        string="Results",
    )

    def _normalize_business_id(self, business_id):
        bid = (business_id or "").strip().upper()
        bid = bid.replace("FI", "")
        bid = re.sub(r"\s+", "", bid)
        return bid

    def action_search(self):
        self.ensure_one()
        backend = self.backend_id

        if backend.auth_mode != "partner":
            raise UserError(_("Backend is not in Partner mode."))

        bid = self._normalize_business_id(self.business_id)
        if not bid:
            raise UserError(_("Please enter a business id (Y-tunnus)."))

        self.business_id = bid

        self.line_ids.unlink()

        data = backend.partner_search_organization(bid)

        organizations = data.get("organizations") or []
        if isinstance(organizations, dict):
            organizations = [organizations]

        lines = []
        for org in organizations:
            uuid = org.get("uuid")
            auth = org.get("authorization") or {}
            authorized = (
                bool(auth.get("authorized")) if isinstance(auth, dict) else False
            )

            if not uuid:
                continue

            lines.append(
                (
                    0,
                    0,
                    {
                        "organization_uuid": uuid,
                        "name": org.get("name") or "",
                        "business_id": org.get("business_id") or bid,
                        "authorized": authorized,
                    },
                )
            )

        if lines:
            self.write({"line_ids": lines})

        return {
            "type": "ir.actions.act_window",
            "res_model": "vismasign.partner.onboard.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class VismaSignPartnerOnboardWizardLine(models.TransientModel):
    _name = "vismasign.partner.onboard.wizard.line"
    _description = "Netvisor Sign Partner Organization Search Result"

    wizard_id = fields.Many2one(
        "vismasign.partner.onboard.wizard",
        required=True,
        ondelete="cascade",
    )

    organization_uuid = fields.Char(string="UUID", readonly=True)
    name = fields.Char(string="Name", readonly=True)
    business_id = fields.Char(string="Business ID", readonly=True)
    authorized = fields.Boolean(string="Authorized", readonly=True)
