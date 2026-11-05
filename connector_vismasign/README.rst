.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

====================
Visma Sign Connector
====================

This module provides a **generic, standalone Visma Sign connector** that integrates
Odoo with the Visma Sign electronic signature service.

It is intentionally designed as a **reusable, model-agnostic backend**.
You can use it as a base when implementing signature flows for any Odoo model
(e.g. agreements, sales orders, HR documents, custom models, etc.).

It handles the low-level communication, authentication, API calls, request signing
and logging—allowing other modules to focus only on business logic.

Features
========

* Generic Visma Sign backend with full Connector integration
* Supports **two authentication modes**:

  * **Customer credentials (HMAC)**: requests are signed with HMAC–SHA512 and authenticated with ``Authorization: Onnistuu ...``
  * **Partner OAuth2**: OAuth2 ``client_credentials`` token (``Authorization: Bearer <token>``) and acting on behalf of a customer with ``as_organization=<uuid>``

* Document creation (``/api/v1/document/``)
* PDF file upload to a document
* Sending signing invitations
* Optional support for several signers per document (``Allow multiple
  signers`` on the backend, disabled by default)
* Fetching invitation status
* Fetching a document with its status and all of its invitations
* Downloading document files via the API (e.g. signed PDF)
* Request/response logging in ``vismasign.binding`` (for debugging and audit)
* “Test Connection” tool for validating configuration (logs the test call into bindings)
* Optional **default document category** support:

  * Resolves/creates category by name and caches the category UUID on the backend
  * Automatically attaches the category UUID to created documents (if set)

* Optional **inviter** support (name/email) in invitation payload
* Optional invitation signing behavior defaults:

  * ``sign_as_organization``
  * ``sign_as_inviter_organization`` (requires ``sign_as_organization``)

* Partner onboarding helpers (UI wizards):

  * Search organization by business id (Y-tunnus)
  * “One button” flow to invite/request access or create organization, and store ``as_organization_uuid``


Architecture
============

This module:
------------

* Implements a reusable Connector backend (``vismasign.backend``)
* Stores all API traffic in ``vismasign.binding`` for traceability
* Provides a unified request layer that selects auth mode automatically
* Exposes Python helper methods you can call from any model:

  - ``create_document(payload)``
  - ``add_file(document_uuid, filename, pdf_data)``
  - ``send_invitation(document_uuid, recipient_email)``
  - ``get_invitation_status(invitation_uuid)``
  - ``get_document(document_uuid)``
  - ``get_document_file(document_uuid, index=0)``

Other modules:
--------------

Feature-specific modules should:
* Generate their PDF content
* Call backend methods
* Store returned UUIDs on the business model

This connector itself **does NOT implement any business flow**—it only provides the foundation.

Security
========
``vismasign.backend`` and ``vismasign.binding`` store API credentials
(HMAC secrets, OAuth client secrets, cached access tokens) and request/
response logs, so access is restricted to the standard **Connector Manager**
group (``connector.group_connector_manager``, shared with the other
connector modules in this repo, e.g. ``connector_fennoa``). Only users in
this group see the *Visma Sign* menu (nested under *Connectors*) or can
read/write these models directly.

Feature-specific modules that call the backend's helper methods
(``create_document``, ``add_file``, ``send_invitation``, etc.) on behalf of
an end-user who is not in this group must fetch the backend record via
``sudo()`` first, with a comment explaining why — see
``agreement_vismasign``'s ``action_vismasign_send()`` for an example.

Configuration
=============
1. Navigate to **Connectors → Visma Sign → Backends** (requires the
   **Connector Manager** group).
2. Create a backend and fill:

   * **Company**
   * **Base URL** (no trailing slash)
   * **Authentication mode**

3. If using **Customer credentials (HMAC)**:

   * **HMAC client identifier**
   * **HMAC secret key (Base64)**

4. If using **Partner OAuth2**:

   * **Partner OAuth client_id**
   * **Partner OAuth client_secret**
   * **Partner OAuth scopes** (space-separated, according to what you need)
   * **Target organization UUID** (``as_organization_uuid``)

     * Required for organization-level API calls (documents, categories, invitations) in Partner mode

   In Partner mode you can also use the provided wizards from the backend form:

   * **Partner onboarding** (search organizations)
   * **Send partner invite** (invite/request access or create organization based on Business ID)

5. Optional configuration:

   * **Default document category (name/description)**: the module will resolve/create the category and cache its UUID
   * **Inviter (name/email)**: sent in invitation payload when set
   * **Signing behavior defaults**: defaults applied when sending invitations
   * **Allow multiple signers**: allow sending a document to several signers
     at once. Disabled by default, so only one signer per document is allowed

6. Click **Test Connection**.

Usage
=====
Other modules can import and use the connector like this:

* Find your backend (``sudo()`` is required unless the calling user is in
  ``connector.group_connector_manager``, see *Security* above):

  ``backend = env["vismasign.backend"].sudo().search([], limit=1)``

* Create a document:

  ``uuid = backend.create_document(payload)``

  If **Default category** is configured on the backend, the connector will:

  * resolve/create the category in Visma Sign
  * set ``category_uuid`` on the outgoing document payload automatically (unless your payload already sets it)

* Add a PDF:

  ``file_uuid = backend.add_file(uuid, filename, pdf_bytes)``

* Send an invitation:

  ``inv = backend.send_invitation(uuid, email)``

  The connector can optionally include:

  * ``inviter`` block (name/email) if configured
  * default signing flags (``sign_as_organization`` / ``sign_as_inviter_organization``) if enabled on the backend

  To invite several signers, pass a list of emails. Visma Sign creates all
  invitations of a document at once, so they are sent in one request. This
  requires **Allow multiple signers** on the backend; otherwise passing more
  than one email raises an error:

  ``inv = backend.send_invitation(uuid, [email_1, email_2])``

  The order of the returned invitations is not documented to match the
  emails, so match them by email using ``get_document``.

* Check invitation status:

  ``status = backend.get_invitation_status(invitation_uuid)``

* Get a document with its status and all of its invitations (the document is
  ``signed`` only when every invitation is fulfilled):

  ``document = backend.get_document(uuid)``

* Download a document file (e.g. signed PDF):

  ``pdf_bytes = backend.get_document_file(uuid, index=0)``

Bindings allow you to see all requests and responses in Odoo UI for debugging:
**Connectors → Visma Sign → Bindings**.

Known issues / Roadmap
======================
\-

Credits
=======

Contributors
------------

* Valtteri Lattu <valtteri.lattu@tawasta.fi>

Maintainer
----------

.. image:: https://tawasta.fi/templates/tawastrap/images/logo.png
   :alt: Oy Tawasta OS Technologies Ltd.
   :target: https://tawasta.fi/

This module is maintained by Oy Tawasta OS Technologies Ltd.
