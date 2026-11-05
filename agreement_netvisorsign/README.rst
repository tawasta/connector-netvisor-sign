.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

=======================
Agreement Netvisor Sign
=======================
This module integrates the OCA ``agreement`` module with Netvisor Sign electronic
signatures.

The module allows sending agreements directly to Netvisor Sign, tracking
signature status automatically, and downloading signed PDF documents.

Features
========
* Create an agreement directly from a quotation (``agreement_sale``), either
  manually with a button or automatically on order confirmation
* Select the document template per agreement type, so lease agreements and
  the different sale agreement templates each use their own report
* Send agreements to Netvisor Sign directly from the agreement form
* Add one or more additional signers on the agreement, in addition to the
  customer. Any contact with an email address can be a signer, for example a
  company representative, and the number of signers is not limited. This
  requires **Allow multiple signers** on the Netvisor Sign backend; without it
  the signature request goes to the customer only
* Track the signing status of each signer. The agreement is signed only when
  every signer has signed
* Attach a local copy of the rendered (unsigned) document for audit purposes
* Store Netvisor Sign document, file, and invitation UUIDs on the agreement
* Automatic signature status synchronization using a scheduled action
* Download and attach the signed PDF document automatically
* Multi-company support

Configuration
=============

#. Go to
   *Agreements -> Settings* and configure:

   * **Auto-create Agreement on Order Confirmation**
     If enabled, confirming a quotation that has an agreement type set
     automatically creates the linked agreement. Otherwise, use the
     *Create Agreement* button on the quotation.

#. On each *Agreement Type* (*Agreements -> Configuration -> Agreement
   Types*), select the **Netvisor Sign Report** used to render the document
   for agreements of that type. Only agreement reports (e.g. provided by
   ``agreement_legal``) and sale order reports are offered. A sale order
   report is rendered from the quotation the agreement was created from.
   This is required before an agreement of that type can be sent for
   signature.

#. To send agreements to additional signers too, enable **Allow
   multiple signers** on the company's Netvisor Sign backend (*Connectors ->
   Netvisor Sign -> Backends*). It is disabled by default, and then agreements
   are sent to the customer only as before.

#. Ensure that a Netvisor Sign backend is configured for the company (requires
   the **Connector Manager** group (``connector.group_connector_manager``) —
   see ``connector_netvisorsign``'s README). Sending an agreement itself does
   not require this group, since ``action_vismasign_send()`` accesses the
   backend via ``sudo()``.

Usage
=====

#. On a quotation, set the **Agreement Type**, then either:

   * click *Create Agreement*, or
   * confirm the order, if automatic creation is enabled

   This creates an agreement linked to the quotation via ``agreement_id``.

#. Open the agreement (not a template).

#. If the backend allows multiple signers, the *Netvisor Sign* tab shows the
   **Signers** list. Add one or more contacts to it to send the signature
   request to them in addition to the customer. The customer is added
   automatically when the request is sent, and each signer needs a different
   email address. Without additional signers the request goes to the customer
   only.

   The list cannot be changed after the request has been sent, because
   Netvisor Sign creates all invitations of a document at the same time.

#. Click:

   ::

       Send for Signature

#. The module will:

   * render the document using the report configured on the agreement's type
   * attach the rendered PDF to the agreement as an audit-trail copy
   * create a Netvisor Sign document
   * upload the PDF
   * send the signature invitation to the partner, or the invitations to all
     signers in one request

#. Signature status is updated automatically every 15 minutes using a cron job.
   For several signers the agreement status shows the status of the Netvisor
   Sign document (for example ``pending`` or ``signed``), and each signer's
   status is shown on the signer list.

#. Once the agreement has been signed (by every signer):

   * the signed PDF is downloaded automatically
   * the signed document is attached to the agreement
   * a chatter notification is posted on the agreement

Technical Details
=================

Scheduled Action
----------------

The module installs the following scheduled action:

::

    Netvisor Sign: Update Invitation Status (Agreements)

Default interval:

* Every 15 minutes

Agreement Fields
-----------------

The following technical fields are added to the agreement:

* ``vismasign_document_uuid``
* ``vismasign_file_uuid``
* ``vismasign_invitation_uuid`` (only filled when the request was sent to
  the customer only)
* ``vismasign_status``
* ``vismasign_last_check``
* ``vismasign_signer_ids``: the additional signers added before sending
  and, once sent to several signers, all signers
  (``agreement.vismasign.signer``) with their role, email, invitation UUID and
  status

Agreement Type Fields
----------------------

* ``report_id``: report used to render agreements of this type. Required
  before an agreement of that type can be sent for signature. An agreement
  report is rendered for the agreement itself; a sale order report is
  rendered for the single quotation linked to the agreement.

Sale Order
----------

* ``action_create_agreement()``: creates the agreement for the quotation
  using its ``agreement_type_id`` (from ``agreement_sale``) and links it back
  via ``agreement_id``.
* Confirming an order auto-creates the agreement when the
  ``agreement_vismasign.auto_create_agreement_on_confirm`` system parameter
  is enabled.


Known issues / Roadmap
======================
\-

Credits
=======

Contributors
------------

* Valtteri Lattu <valtteri.lattu@futural.fi>

Maintainer
----------

.. image:: https://tawasta.fi/templates/tawastrap/images/logo.png
   :alt: Oy Tawasta OS Technologies Ltd.
   :target: https://tawasta.fi/

This module is maintained by Oy Tawasta OS Technologies Ltd.
