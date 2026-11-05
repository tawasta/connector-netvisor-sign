##############################################################################
#
#    Author: Tawasta
#    Copyright 2020 Oy Tawasta OS Technologies Ltd. (https://tawasta.fi)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program. If not, see http://www.gnu.org/licenses/agpl.html
#
##############################################################################
{
    "name": "Agreement vismasign",
    "summary": "Agreement vismasign",
    "version": "17.0.1.1.0",
    "category": "Contract",
    "website": "https://gitlab.com/tawasta/odoo/connector_vismasign",
    "author": "Tawasta",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "agreement",
        "agreement_sale",
        "connector_vismasign",
        "sales_team",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_cron.xml",
        "views/res_config_settings_views.xml",
        "views/agreement.xml",
        "views/agreement_type.xml",
        "views/sale_order.xml",
    ],
}
