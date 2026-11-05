import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class VismaSignBackend(models.Model):
    """
    Backend connector for communicating with the Visma Sign API.

    Supports TWO auth modes:
      1) HMAC (customer has their own Visma Sign credentials)
      2) Partner OAuth2 (you use your partner credentials)
    """

    _name = "vismasign.backend"
    _description = "Visma Sign Backend"
    _inherit = "connector.backend"
    _rec_name = "company_id"

    base_url = fields.Char(required=True)

    auth_mode = fields.Selection(
        selection=[
            ("hmac", "Customer credentials (HMAC)"),
            ("partner", "Partner OAuth2"),
        ],
        string="Authentication mode",
        required=True,
        default="hmac",
        help=(
            "HMAC: customer enters their own Visma Sign API credentials.\n"
            "Partner: you use partner OAuth2 credentials + 'as_organization' to act on behalf of this customer's org."  # noqa: E501
        ),
    )

    client_identifier = fields.Char(string="HMAC client identifier")
    secret_key_b64 = fields.Char(string="HMAC secret key (Base64)")

    # -------------------------
    # Partner OAuth2 fields (your credentials)
    # -------------------------
    partner_client_id = fields.Char(string="Partner OAuth client_id")
    partner_client_secret = fields.Char(string="Partner OAuth client_secret")
    partner_scope = fields.Char(
        string="Partner OAuth scopes",
        help="Space-separated scopes. Configure according to what your module needs.",
    )

    partner_access_token = fields.Char(string="Cached access token", readonly=True)
    partner_token_expires_at = fields.Datetime(string="Token expires at", readonly=True)

    # The customer org UUID (per customer Odoo installation) used with Partner mode
    as_organization_uuid = fields.Char(
        string="Target organization UUID",
        help="In Partner mode, all org-API calls will be executed with ?as_organization=<this uuid>.",  # noqa: E501
    )

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    binding_ids = fields.One2many("vismasign.binding", "backend_id", readonly=True)

    category_name = fields.Char(
        string="Default category (name)",
        help=(
            "Visma Sign category name to use for created documents. "
            "If set, the backend will resolve/create the category and attach it to documents."  # noqa: E501
        ),
    )
    category_description = fields.Text(
        string="Category description",
        help="Optional description used only when creating the category in Visma Sign.",
    )
    category_uuid = fields.Char(
        string="Default category UUID",
        readonly=True,
        help=(
            "Resolved/created Visma Sign category UUID (cached). "
            "Cleared automatically if name/description changes or organization changes."
        ),
    )

    inviter_name = fields.Char(
        string="Inviter name",
        help="Optional. If set, sent as inviter.name (5-50 chars) in invitation payload.",  # noqa: E501
    )
    inviter_email = fields.Char(
        string="Inviter email",
        help="Optional. If set, sent as inviter.email in invitation payload.",
    )

    default_sign_as_organization = fields.Boolean(
        string="Default: sign as organization",
        default=False,
        help="If enabled, invitations will default to sign_as_organization=true unless overridden.",  # noqa: E501
    )
    default_sign_as_inviter_organization = fields.Boolean(
        string="Default: sign as inviter's organization",
        default=False,
        help="Only used if sign_as_organization is true. If enabled, invitations will default to "  # noqa: E501
        "sign_as_inviter_organization=true unless overridden.",
    )

    allow_multiple_signers = fields.Boolean(
        default=False,
        help="If enabled, a document can be sent to several signers at once. "
        "If disabled, only one signer per document is allowed.",
    )

    @api.constrains(
        "default_sign_as_organization", "default_sign_as_inviter_organization"
    )
    def _check_default_signing_flags(self):
        for rec in self:
            if (
                rec.default_sign_as_inviter_organization
                and not rec.default_sign_as_organization
            ):
                raise ValidationError(
                    _(
                        "Default: sign as inviter's organization requires 'sign as organization' to be enabled."  # noqa: E501
                    )
                )

    @api.constrains("inviter_name")
    def _check_inviter_name(self):
        for rec in self:
            if rec.inviter_name:
                name = rec.inviter_name.strip()
                if len(name) < 5 or len(name) > 50:
                    raise ValidationError(_("Inviter name must be 5-50 characters."))

    @api.constrains("base_url")
    def _check_base_url(self):
        for rec in self:
            if rec.base_url.endswith("/"):
                raise ValidationError(_("Base URL must not end with '/'."))

    @api.constrains(
        "auth_mode",
        "client_identifier",
        "secret_key_b64",
        "partner_client_id",
        "partner_client_secret",
        "as_organization_uuid",
    )
    def _check_auth_configuration(self):
        for rec in self:
            if rec.auth_mode == "hmac":
                if not rec.client_identifier or not rec.secret_key_b64:
                    raise ValidationError(
                        _(
                            "HMAC mode requires 'client_identifier' and 'secret_key_b64' to be set."  # noqa: E501
                        )
                    )
            elif rec.auth_mode == "partner":
                if not rec.partner_client_id or not rec.partner_client_secret:
                    raise ValidationError(
                        _(
                            "Partner mode requires 'partner_client_id' and 'partner_client_secret' to be set."  # noqa: E501
                        )
                    )

    @api.onchange("category_name", "category_description", "as_organization_uuid")
    def _onchange_category_fields(self):
        for rec in self:
            rec.category_uuid = False

    # -------------------------
    # HMAC implementation
    # -------------------------
    def _get_secret_key(self):
        return base64.b64decode(self.secret_key_b64 or "")

    def _build_hmac_headers(self, method, path, body, content_type=""):
        secret_key = self._get_secret_key()
        md5 = base64.b64encode(hashlib.md5(body).digest()).decode()
        date = format_datetime(datetime.now(timezone.utc))
        string = "\n".join([method, md5, content_type, date, path])
        signature = base64.b64encode(
            hmac.new(secret_key, string.encode(), hashlib.sha512).digest()
        ).decode()
        auth = f"Onnistuu {self.client_identifier}:{signature}"
        return {
            "Content-MD5": md5,
            "Content-Type": content_type,
            "Date": date,
            "Authorization": auth,
        }

    # -------------------------
    # Partner OAuth2 implementation
    # -------------------------
    def _partner_token_valid(self):
        self.ensure_one()
        if not self.partner_access_token or not self.partner_token_expires_at:
            return False
        now = fields.Datetime.now()
        return self.partner_token_expires_at > (now + timedelta(seconds=60))

    def _get_partner_access_token(self):
        """
        OAuth2 client_credentials:
          POST /api/v1/auth/token
        """
        self.ensure_one()

        if self._partner_token_valid():
            return self.partner_access_token

        if not self.partner_client_id or not self.partner_client_secret:
            raise UserError(
                _("Partner mode selected but partner credentials are missing.")
            )

        token_path = "/api/v1/auth/token"
        url = f"{self.base_url}{token_path}"

        form = {
            "grant_type": "client_credentials",
            "client_id": (self.partner_client_id or "").strip(),
            "client_secret": (self.partner_client_secret or "").strip(),
        }
        if self.partner_scope:
            form["scope"] = (self.partner_scope or "").strip()

        try:
            resp = requests.post(
                url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        except requests.RequestException as e:
            raise UserError(str(e)) from e

        if resp.status_code != 200:
            raise UserError(
                _("Failed to get partner access token: %s\n%s")
                % (resp.status_code, resp.text)
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise UserError(
                _("Token endpoint did not return JSON:\n%s") % resp.text  # noqa: E501
            ) from e

        token = data.get("access_token")
        token_type = (data.get("token_type") or "").lower()
        expires_in = data.get("expires_in")

        if not token or token_type != "bearer":
            raise UserError(
                _("Unexpected token response:\n%s")
                % json.dumps(data, ensure_ascii=False, indent=2)
            )

        try:
            expires_in = int(expires_in)
        except Exception:
            expires_in = 900

        expires_at = fields.Datetime.now() + timedelta(seconds=expires_in)

        self.write(
            {
                "partner_access_token": token,
                "partner_token_expires_at": expires_at,
            }
        )
        return token

    def _append_query_param(self, path, key, value):
        parts = urlsplit(path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query[key] = value
        new_query = urlencode(query, doseq=True)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )

    def _is_partner_management_endpoint(self, path):
        """
        Endpoints that must NOT get as_organization automatically.
        """
        return (
            path.startswith("/api/v1/auth/")
            or path.startswith("/api/v1/organization/")
            or path.startswith("/api/v1/partner/")
        )

    def _should_add_as_organization(self, path):
        if not path.startswith("/api/v1/"):
            return False
        if self._is_partner_management_endpoint(path):
            return False
        return True

    # -------------------------
    # Unified request
    # -------------------------
    def _request(self, method, path, body=b"", content_type=""):
        self.ensure_one()

        final_path = path
        headers = {}

        if self.auth_mode == "hmac":
            headers = self._build_hmac_headers(method, final_path, body, content_type)

        elif self.auth_mode == "partner":
            token = self._get_partner_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            if content_type:
                headers["Content-Type"] = content_type

            if self._should_add_as_organization(final_path):
                if not self.as_organization_uuid:
                    raise UserError(
                        _(
                            "Partner mode requires 'as_organization_uuid' for org API calls (document/category/invitation)."  # noqa: E501
                        )
                    )
                final_path = self._append_query_param(
                    final_path,
                    "as_organization",
                    (self.as_organization_uuid or "").strip(),
                )

        else:
            raise UserError(_("Unknown auth mode: %s") % self.auth_mode)

        url = f"{self.base_url}{final_path}"
        try:
            resp = requests.request(method, url, headers=headers, data=body, timeout=30)
        except requests.RequestException as e:
            raise UserError(str(e)) from e

        return resp

    # -------------------------
    # Test connection
    # -------------------------
    def action_test_connection(self):
        self.ensure_one()

        if self.auth_mode == "hmac":
            path = "/api/v1/document/00000000-0000-0000-0000-000000000000"
        else:
            path = "/api/v1/category/"

        binding = self.env["vismasign.binding"].create(
            {"backend_id": self.id, "method": "GET", "endpoint": path}
        )

        try:
            resp = self._request("GET", path)

            if self.auth_mode == "hmac":
                successful = resp.status_code in (200, 404)
            else:
                successful = resp.status_code == 200

            binding.write(
                {
                    "status_code": resp.status_code,
                    "response": resp.text,
                    "successful": successful,
                }
            )
        except Exception as e:
            binding.write({"response": str(e), "successful": False})
            raise UserError(_("Connection failed:\n%s") % e) from e

        if successful:
            raise UserError(
                _("Connection successful. Visma Sign responded with status %s.")
                % resp.status_code
            )

        raise UserError(
            _("Unexpected status code from Visma Sign: %s\n%s")
            % (resp.status_code, resp.text)
        )

    # -------------------------
    # Partner onboarding helpers
    # -------------------------
    def partner_search_organization(self, business_id):
        """
        GET /api/v1/organization/?business_id=<...>
        """
        self.ensure_one()
        if self.auth_mode != "partner":
            raise UserError(_("This action requires Partner mode."))

        path = self._append_query_param(
            "/api/v1/organization/", "business_id", (business_id or "").strip()
        )
        resp = self._request("GET", path)

        if resp.status_code != 200:
            raise UserError(
                _("Organization search failed: %s\n%s") % (resp.status_code, resp.text)
            )
        return resp.json()

    def partner_create_organization(
        self,
        name,
        business_id,
        postal_address,
        postal_code,
        municipality,
        admin_identifier,
        admin_first_name,
        admin_last_name,
        admin_email,
    ):
        """
        POST /api/v1/organization/

        Finland + company is hardcoded to keep it simple.
        Uses ONLY required fields from the docs.
        """
        self.ensure_one()
        if self.auth_mode != "partner":
            raise UserError(_("This action requires Partner mode."))

        payload = {
            "name": (name or "").strip(),  # Required
            "organization_type": "company",  # Required
            "country_of_operation": "Finland",  # Required
            "business_id": (business_id or "").strip(),  # Required
            "postal_address": (postal_address or "").strip(),  # Required
            "postal_code": (postal_code or "").strip(),  # Required
            "municipality": (municipality or "").strip(),  # Required
            "admins": [  # Required, at least one admin
                {
                    "identifier": (admin_identifier or "").strip(),  # Required
                    "first_name": (admin_first_name or "").strip(),  # Required
                    "last_name": (admin_last_name or "").strip(),  # Required
                    "email": (admin_email or "").strip(),  # Required
                }
            ],
        }

        # minimal validation (client side)
        for k in (
            "name",
            "business_id",
            "postal_address",
            "postal_code",
            "municipality",
        ):
            if not payload[k]:
                raise UserError(_("Missing required organization field: %s") % k)
        admin = payload["admins"][0]
        for k in ("identifier", "first_name", "last_name", "email"):
            if not admin[k]:
                raise UserError(_("Missing required admin field: %s") % k)

        path = "/api/v1/organization/"
        body = json.dumps(payload).encode("utf-8")

        binding = self.env["vismasign.binding"].create(
            {
                "backend_id": self.id,
                "method": "POST",
                "endpoint": path,
                "payload": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        )

        resp = self._request("POST", path, body=body, content_type="application/json")

        binding.write(
            {
                "status_code": resp.status_code,
                "response": resp.text,
                "successful": resp.status_code == 201,
            }
        )

        if resp.status_code != 201:
            raise UserError(
                _("Organization create failed: %s\n%s") % (resp.status_code, resp.text)
            )

        # UUID from Location header
        location = resp.headers.get("Location") or ""
        uuid = location.rstrip("/").split("/")[-1] if location else False
        if not uuid:
            # as fallback try JSON
            try:
                data = resp.json()
                uuid = data.get("uuid")
            except Exception:
                uuid = False

        if not uuid:
            raise UserError(_("Could not determine created organization UUID."))

        return uuid

    def partner_request_access(self, organization_uuid, message, lang="fi"):
        """
        POST /api/v1/organization/<uuid>/client-authorization?lang=fi
        Body requires: {"message": "..."}  (ONLY required field)
        """
        self.ensure_one()
        if self.auth_mode != "partner":
            raise UserError(_("This action requires Partner mode."))

        organization_uuid = (organization_uuid or "").strip()
        if not organization_uuid:
            raise UserError(_("Missing organization UUID."))

        message = (message or "").strip()
        if not message:
            raise UserError(_("Message is required."))

        base = f"/api/v1/organization/{organization_uuid}/client-authorization"
        path = self._append_query_param(base, "lang", (lang or "fi").strip())

        payload = {"message": message}
        body = json.dumps(payload).encode("utf-8")

        binding = self.env["vismasign.binding"].create(
            {
                "backend_id": self.id,
                "method": "POST",
                "endpoint": path,
                "payload": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        )

        resp = self._request("POST", path, body=body, content_type="application/json")

        binding.write(
            {
                "status_code": resp.status_code,
                "response": resp.text,
                "successful": resp.status_code == 201,
            }
        )

        if resp.status_code != 201:
            raise UserError(
                _("Organization access request failed: %s\n%s")
                % (resp.status_code, resp.text)
            )

        return True

    def partner_invite_or_create_by_business_id(
        self,
        business_id,
        message,
        organization_name,
        postal_address,
        postal_code,
        municipality,
        admin_identifier,
        admin_first_name,
        admin_last_name,
        admin_email,
        lang="fi",
    ):
        """
        Simple “one button” flow:
          1) Search by business_id
          2) If found:
               - if authorized => set as_organization_uuid
               - else => request access (invite)
          3) If not found:
               - create organization with required fields
               - set as_organization_uuid
        Returns dict describing what happened.
        """
        self.ensure_one()
        if self.auth_mode != "partner":
            raise UserError(_("This action requires Partner mode."))

        bid = (business_id or "").strip()
        if not bid:
            raise UserError(_("Business ID is required."))

        data = self.partner_search_organization(bid)
        orgs = data.get("organizations") or []
        if isinstance(orgs, dict):
            orgs = [orgs]

        if orgs:
            # choose the first match (partner docs mention multiple possible)
            org = orgs[0]
            org_uuid = (org.get("uuid") or "").strip()
            auth = org.get("authorization") or {}
            authorized = (
                bool(auth.get("authorized")) if isinstance(auth, dict) else False
            )

            if not org_uuid:
                raise UserError(_("Visma Sign returned an organization without UUID."))

            if authorized:
                self.write({"as_organization_uuid": org_uuid})
                return {"action": "already_authorized", "organization_uuid": org_uuid}

            # not authorized => send invite (required: message)
            self.partner_request_access(org_uuid, message=message, lang=lang)
            return {"action": "invite_sent", "organization_uuid": org_uuid}

        # No org exists => create it (required fields)
        created_uuid = self.partner_create_organization(
            name=organization_name,
            business_id=bid,
            postal_address=postal_address,
            postal_code=postal_code,
            municipality=municipality,
            admin_identifier=admin_identifier,
            admin_first_name=admin_first_name,
            admin_last_name=admin_last_name,
            admin_email=admin_email,
        )
        self.write({"as_organization_uuid": created_uuid})
        return {"action": "created", "organization_uuid": created_uuid}

    # -------------------------
    # Existing methods (unchanged)
    # -------------------------
    def _build_inviter_payload(self):
        self.ensure_one()
        inviter = {}
        if self.inviter_name:
            inviter["name"] = self.inviter_name.strip()
        if self.inviter_email:
            inviter["email"] = self.inviter_email.strip()
        return inviter or False

    def get_categories(self):
        self.ensure_one()
        path = "/api/v1/category/"

        binding = self.env["vismasign.binding"].create(
            {"backend_id": self.id, "method": "GET", "endpoint": path}
        )

        response = self._request("GET", path)

        try:
            data = response.json()
            response_text = json.dumps(data, ensure_ascii=False, indent=2)
        except ValueError:
            data = {}
            response_text = response.text

        binding.write(
            {
                "status_code": response.status_code,
                "response": response_text,
                "successful": response.status_code == 200,
            }
        )

        if response.status_code != 200:
            raise UserError(
                _("Visma Sign get categories failed: %s\n%s")
                % (response.status_code, response.text)
            )

        return data

    def create_category(self, name, description=""):
        self.ensure_one()
        path = "/api/v1/category/"
        payload = {"name": name, "description": description or ""}
        body = json.dumps(payload).encode("utf-8")

        binding = self.env["vismasign.binding"].create(
            {
                "backend_id": self.id,
                "method": "POST",
                "endpoint": path,
                "payload": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        )

        response = self._request("POST", path, body, "application/json")

        binding.write(
            {
                "status_code": response.status_code,
                "response": response.text,
                "successful": response.status_code == 201,
            }
        )

        if response.status_code != 201:
            raise UserError(
                _("Failed to create category in Visma Sign:\n%s") % response.text
            )

        location = response.headers.get("Location") or ""
        category_uuid = location.rstrip("/").split("/")[-1]
        if not category_uuid:
            raise UserError(
                _("Visma Sign did not return category uuid in Location header.")
            )
        return category_uuid

    def ensure_default_category_uuid(self):
        self.ensure_one()

        if not self.category_name:
            return False
        if self.category_uuid:
            return self.category_uuid

        wanted = (self.category_name or "").strip()
        if not wanted:
            return False

        data = self.get_categories()
        categories = data.get("categories") or []
        for cat in categories:
            if (cat.get("name") or "").strip() == wanted:
                uuid = cat.get("uuid")
                if uuid:
                    self.write({"category_uuid": uuid})
                    return uuid

        new_uuid = self.create_category(wanted, self.category_description or "")
        self.write({"category_uuid": new_uuid})
        return new_uuid

    def create_document(self, payload):
        self.ensure_one()

        payload = payload or {}
        doc = payload.get("document") or {}
        if "category_uuid" not in doc and "category" not in doc:
            cat_uuid = self.ensure_default_category_uuid()
            if cat_uuid:
                payload = dict(payload)
                doc = dict(doc)
                doc["category_uuid"] = cat_uuid
                payload["document"] = doc

        path = "/api/v1/document/"
        body = json.dumps(payload).encode("utf-8")

        binding = self.env["vismasign.binding"].create(
            {
                "backend_id": self.id,
                "method": "POST",
                "endpoint": path,
                "payload": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        )

        response = self._request("POST", path, body, "application/json")

        binding.write(
            {
                "status_code": response.status_code,
                "response": response.text,
                "successful": response.status_code == 201,
            }
        )
        if response.status_code != 201:
            raise UserError(
                _("Failed to create document in Visma Sign:\n%s") % response.text
            )

        location = response.headers.get("Location") or ""
        document_uuid = location.rstrip("/").split("/")[-1]
        return document_uuid

    def add_file(self, document_uuid, filename, pdf_data):
        self.ensure_one()

        filename_q = quote(filename, safe="")
        path = f"/api/v1/document/{document_uuid}/files?filename={filename_q}"

        binding = self.env["vismasign.binding"].create(
            {"backend_id": self.id, "method": "POST", "endpoint": path}
        )

        response = self._request("POST", path, pdf_data, "application/pdf")

        try:
            response_data = response.json()
        except ValueError:
            response_data = {}

        binding.write(
            {
                "status_code": response.status_code,
                "response": response.text,
                "successful": response.status_code == 201,
            }
        )

        if response.status_code != 201:
            raise UserError(
                _("Visma Sign add file failed: %s\n%s")
                % (response.status_code, response.text)
            )

        file_uuid = response_data.get("uuid")
        if not file_uuid:
            raise UserError(_("Visma Sign did not return file uuid."))

        return file_uuid

    def _prepare_invitation(self, recipient_email):
        """Build the invitation of one recipient from the backend defaults."""
        self.ensure_one()
        invite = {"email": recipient_email, "messages": {"send_invitation_email": True}}

        if self.default_sign_as_organization:
            invite["sign_as_organization"] = True
            if self.default_sign_as_inviter_organization:
                invite["sign_as_inviter_organization"] = True

        inviter_payload = self._build_inviter_payload()
        if inviter_payload:
            invite["inviter"] = inviter_payload

        return invite

    def send_invitation(self, document_uuid, recipient_email):
        """Send signing invitations of a document.

        :param document_uuid: uuid of the Visma Sign document
        :param recipient_email: one email address, or a list of them when
            ``allow_multiple_signers`` is enabled on the backend. Visma Sign
            requires all invitations of a document to be created at once.
        :return: list of created invitations (uuid, status, passphrase). The
            order is not documented to match the recipients, so match them
            by email using ``get_document``.
        """
        self.ensure_one()
        path = f"/api/v1/document/{document_uuid}/invitations"

        recipient_emails = (
            list(recipient_email)
            if isinstance(recipient_email, list | tuple)
            else [recipient_email]
        )
        if not recipient_emails:
            raise UserError(_("At least one recipient is required."))
        if len(recipient_emails) > 1 and not self.allow_multiple_signers:
            raise UserError(
                _(
                    "Multiple signers are not allowed. Enable 'Allow multiple "
                    "signers' on the Visma Sign backend."
                )
            )

        if (
            self.default_sign_as_inviter_organization
            and not self.default_sign_as_organization
        ):
            raise UserError(
                _(
                    "Default 'sign as inviter's organization' requires 'sign as organization' to be enabled."  # noqa: E501
                )
            )

        invites = [self._prepare_invitation(email) for email in recipient_emails]
        body = json.dumps(invites).encode("utf-8")

        binding = self.env["vismasign.binding"].create(
            {
                "backend_id": self.id,
                "method": "POST",
                "endpoint": path,
                "payload": json.dumps(invites, ensure_ascii=False, indent=2),
            }
        )

        response = self._request("POST", path, body, "application/json")

        try:
            response_data = response.json()
        except ValueError:
            response_data = {}

        binding.write(
            {
                "status_code": response.status_code,
                "response": response.text,
                "successful": response.status_code == 201,
            }
        )

        if response.status_code != 201:
            raise UserError(
                _("Visma Sign send invitation failed: %s\n%s")
                % (response.status_code, response.text)
            )

        return response_data

    def get_document(self, document_uuid):
        """Return the document with its status and all of its invitations.

        The document is ``signed`` only when every invitation is fulfilled.
        """
        self.ensure_one()
        path = f"/api/v1/document/{document_uuid}"

        binding = self.env["vismasign.binding"].create(
            {"backend_id": self.id, "method": "GET", "endpoint": path}
        )

        response = self._request("GET", path)

        try:
            data = response.json()
            response_text = json.dumps(data, ensure_ascii=False, indent=2)
        except ValueError:
            data = {}
            response_text = response.text

        binding.write(
            {
                "status_code": response.status_code,
                "response": response_text,
                "successful": response.status_code == 200,
            }
        )

        if response.status_code != 200:
            raise UserError(
                _("Visma Sign get document failed: %s\n%s")
                % (response.status_code, response.text)
            )

        # A document is always an object; callers read its keys directly
        return data if isinstance(data, dict) else {}

    def get_invitation_status(self, invitation_uuid):
        self.ensure_one()
        path = f"/api/v1/invitation/{invitation_uuid}"

        binding = self.env["vismasign.binding"].create(
            {"backend_id": self.id, "method": "GET", "endpoint": path}
        )

        response = self._request("GET", path)

        try:
            data = response.json()
            response_text = json.dumps(data, ensure_ascii=False, indent=2)
        except ValueError:
            data = {}
            response_text = response.text

        binding.write(
            {
                "status_code": response.status_code,
                "response": response_text,
                "successful": response.status_code == 200,
            }
        )

        if response.status_code != 200:
            raise UserError(
                _("Visma Sign get invitation status failed: %s\n%s")
                % (response.status_code, response.text)
            )

        return data

    def get_document_file(self, document_uuid, index=0):
        self.ensure_one()
        path = f"/api/v1/document/{document_uuid}/files/{index}"

        binding = self.env["vismasign.binding"].create(
            {"backend_id": self.id, "method": "GET", "endpoint": path}
        )

        response = self._request("GET", path)

        if response.status_code != 200:
            try:
                response_text = response.text
            except Exception:
                response_text = "<binary response>"

            binding.write(
                {
                    "status_code": response.status_code,
                    "response": response_text,
                    "successful": False,
                }
            )
            raise UserError(
                _("Visma Sign get document file failed: %s\n%s")
                % (response.status_code, response_text)
            )

        content = response.content or b""
        binding.write(
            {
                "status_code": response.status_code,
                "response": _("Binary content (%s bytes)") % len(content),
                "successful": True,
            }
        )
        return content

    def action_open_partner_onboarding_wizard(self):
        self.ensure_one()
        if self.auth_mode != "partner":
            raise UserError(_("This wizard is available only in Partner mode."))

        vat = (self.company_id.vat or "").strip().upper()
        business_id = vat.replace("FI", "").strip() if vat else ""

        return {
            "type": "ir.actions.act_window",
            "name": _("Partner onboarding"),
            "res_model": "vismasign.partner.onboard.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_backend_id": self.id,
                "default_business_id": business_id,
                "default_organization_name": self.company_id.name,
            },
        }

    def action_open_partner_invite_wizard(self):
        self.ensure_one()
        if self.auth_mode != "partner":
            raise UserError(_("This wizard is available only in Partner mode."))

        vat = (self.company_id.vat or "").strip().upper()
        business_id = vat.replace("FI", "").strip() if vat else ""

        return {
            "type": "ir.actions.act_window",
            "name": _("Send Visma Sign partner invite"),
            "res_model": "vismasign.partner.invite.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_backend_id": self.id,
                "default_business_id": business_id,
                "default_organization_name": self.company_id.name,
            },
        }
