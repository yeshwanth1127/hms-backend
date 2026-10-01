# WhatsApp booking, reception and outreach

The bot and clinic desk live in this backend repository. The staff desk is
`/whatsapp-assets`. Production delivery remains an operator-controlled rollout;
payments are disabled and all fees shown are payable at the clinic.

## Patient experience

- Pictured welcome, specialty PDF, doctor portraits and a browsing mode.
- Specialty, clinic, doctor and time pagination. Choose a date within 30 days,
  browse another date when full, or ask reception for help. A reception request
  does **not** reserve a slot or promise a waiting-list place.
- Review patient, doctor, time, location, quoted consultation fee and payment
  arrangement. The backend rejects a changed quote. Receipts retain the fee.
- `hi` returns to start and releases an unconfirmed hold. `back` works through
  booking. Cancellation and changes use expiring confirmation buttons.
- A sender-bound receipt shortcut opens the visit for 30 minutes. Production
  “Open a visit” also requires its booking reference. Shared phones still expose
  conversations to everyone who can read that phone; use a clinical identity
  check before disclosing additional records.
- “Message preferences” offers separate visit-message and marketing consent.
  Neither is enabled for a new contact. The migration preserves previously recorded visit-reminder consent and labels its provenance; it never grants marketing consent. Booking with a reminder opts into visit
  messages only. `STOP` / `unsubscribe` stops all proactive messages;
  `STOP OFFERS` and a campaign opt-out button stop marketing only.
- Optional clinic, specialty and outreach-language preferences. Booking is in
  English; only approved outreach templates are language-filtered. An empty
  interest list means all specialties. Clinic targeting requires a selected
  clinic; it never infers location from a medical record.
- “Talk to reception” pauses automatic replies and records subsequent messages
  and attachments in the case. “Resume bot” returns to automated booking.
  Urgent keywords produce emergency guidance, not diagnosis or treatment.

## Operator configuration

Backend environment:

| Setting | Purpose |
|---|---|
| `WHATSAPP_OUTREACH_ENABLED` | Default false. Enables approved patient outreach and staff replies. |
| `WHATSAPP_TEST_RECIPIENTS` | Comma-separated, country-code-prefixed digit strings for phones already verified in Meta. Explicit staff test action only. |
| `CLINIC_PHONE` | Verified clinic number shown on handoff. |
| `RECEPTION_HOURS` / `RECEPTION_RESPONSE` | Honest hours and expected reply message. |

Bot environment:

| Setting | Purpose |
|---|---|
| `WA_BUSINESS_ACCOUNT_ID` | Numeric WABA ID. Syncs templates at start and hourly. |
| `WA_OUTREACH_ENABLED` | Default false. Starts the durable outbound worker. Enable for tests; the backend switch still gates patient sends. |
| `WA_REMINDER_TEMPLATE_NAME` / `WA_REMINDER_TEMPLATE_LANGUAGE` | Existing approved reminder template, with reference, doctor and visit-time body fields. |

Use the official token with `whatsapp_business_messaging` and
`whatsapp_business_management` permissions. Store secrets in deployment secret
storage, never source control. Subscribe the app to WABA messages/statuses.
Apply `alembic upgrade head` before launching the new bot. The current head is
`0006_whatsapp_outreach`; it adds consent, handoff, template and outbound tables,
clinic address fields and a fee snapshot without rewriting old bookings.

Keep one bot replica. The database coordinates claims and frequency checks,
but inbound session ordering and exactly-once external sends are not proven
for multiple workers. Keep the staff desk behind HTTPS and authenticated staff
access. Its shared admin key is an existing pilot mechanism: the entered staff
name is an attribution label, **not a verified user identity**. Connect the
hospital's real authentication and staff roles before broad staff access.

## Staff desk

1. **Doctor content:** upload clinic-approved guides/photos.
2. **Reception:** assign a name, inspect the conversation, queue a reply or
   close the case. Review issues, attachments and uncertain inbound/reminder delivery here. Free text requires a fresh patient message within 24 hours;
   consent/STOP and handoff state are rechecked immediately before delivery.
3. **Outreach:** choose a Meta-approved MARKETING template, fill the exact
   numeric body fields, optionally upload its image/PDF header, filter consented
   audience and schedule within 30 days. Save a draft, preview, send one test
   to a configured phone, receive and check it, then review and approve the
   exact recipient count. Changed consent invalidates the preview hash.
4. **Follow-ups:** enable an approved template with three fields: booking
   reference, doctor and visit time. Feedback is queued only after staff mark a
   visit completed; rebooking only after staff mark no-show. A doctor-requested
   follow-up requires a completed visit and a staff-selected future date.
   Per-visit and current contact consent are both required. A disabled or
   changed rule prevents queued delivery. Marketing-classified care templates
   also require marketing consent. Clinical advice is never generated.
5. **Clinic details:** maintain verified address, Google Maps link and arrival
   instructions shown in booking receipts.

Staff-recorded visit statuses are managed through the hospital's admin
appointment contract (`PATCH /api/v1/admin/appointments/{id}/status`). The bot
cannot mark a patient completed or no-show. Follow-up timing/content must be
approved by the clinic; these messages are administrative, not treatment.

## Send controls and evidence

- Approved template inventory expires after two hours. Changed/rejected/deleted
  templates stop existing draft/queued sends; an inventory is fetched completely
  before syncing. This prevents silently deleting templates on a partial fetch.
- Staff campaigns freeze their template fingerprint, attachment and parameters.
  Supported layouts: numeric body fields; static text/image/PDF header; quick
  replies; static URL/phone buttons. Flows, carousel, named fields and dynamic
  URLs are deliberately rejected until supported and tested.
- A preview is capped at 1,000 recipients. Its cost is count × the staff-entered
  rate; exceeding the **estimated** budget blocks approval. It is not a Meta
  billing cap, and test messages also have platform costs. Check the current
  rate card and billing independently.
- Proactive template messages wait until 09:00–19:00 in the preferred clinic's
  timezone (India fallback). Marketing sends are limited to one in seven days
  and two in 30 days per contact. Tests bypass quiet/frequency limits only for
  configured test phones. Consent, clinic/interest/language, template, visit
  status, handoff and campaign pause are checked at dispatch.
- `pending → claimed → sending → accepted → sent → delivered → read`.
  Before-send failures become failed. After-send timeout/crash becomes uncertain;
  it is never blindly retried. A pause/STOP cannot retract a message already
  handed to Meta. Staff must inspect Meta before sending another message.
- Signed status callbacks are persisted, deduplicated and monotonic, including
  callbacks arriving before the send response is stored. Meta “accepted” does
  not prove delivery. Callback data and queue failures appear in the desk.
- Campaign reports show statuses, button engagements, bookings linked to a
  Book button (30-minute session attribution) and opt-outs from Stop buttons.
  They do not claim that unrelated free-text replies/bookings came from a
  campaign; general STOP is still enforced globally.
- Staff uploads use existing magic-byte/parser validation and production ClamAV
  fail-closed scanning. Patient case assets are never eligible campaign assets.

## HTTP contracts

All service routes use `/api/v1/integrations/whatsapp` plus `X-Service-Key`.
All desk operations use `/api/v1/admin/whatsapp` plus `X-Admin-Key`.
Bodies reject unknown fields. Full schemas are available in the backend OpenAPI.

| Service operation | Route |
|---|---|
| Preferences / consent event | `GET/PUT /preferences/{sender}` |
| Reception request / paused messages / resume | `POST /reception`, `/reception/messages`, `/reception/{sender}/resume` |
| Complete trusted template inventory | `POST /templates/sync` |
| Durable dispatch | `POST /outreach/claim`, `/outreach/{id}/sending`, `/sent`, `/failed` |
| Signed provider delivery event | `POST /delivery-status` |
| Owned button engagement | `POST /outreach/{id}/engage` |
| Recheck legacy reminder consent/state | `POST /reminders/{id}/authorize` |

| Staff operation | Route |
|---|---|
| Reception inbox / assignment / reply | `GET /reception`, `PATCH /reception/{sender}`, `POST /reception/{sender}/reply` |
| Template inventory / config | `GET /templates`, `/operations-config` |
| Campaign draft / inventory | `POST/GET /campaigns` |
| Preview / test / approve / pause | `GET /campaigns/{id}/preview`, `POST /test`, `/approve`, `/pause` |
| Image/PDF assets | `POST/GET /campaign-assets`, `GET /assets/{id}` |
| Follow-up rules / doctor-selected date | `GET /followup-rules`, `PUT /followup-rules/{kind}`, `POST /appointments/{id}/followup` |
| Delivery record / clinic details | `GET /outbound`, `PATCH /branches/{id}` |

## Deployment acceptance still required

Use `whatsapp-bot/PRODUCTION_DEPLOYMENT.md` for the existing deployment gates.
Before enabling patient outreach, verify live opt-in/STOP, the real number,
template permissions and approval, patient and partner phone delivery, scanner
availability, backups/retention, reception staffing and actual Meta billing.
No live campaign or charge is performed by the automated test suite. Native
WhatsApp Flows and UPI payment collection remain a separate future release.

Primary references:
[WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/),
[Meta template inventory](https://www.postman.com/meta/whatsapp-business-platform/request/qtgr0i7/get-all-templates-default-fields),
[Meta interactive templates](https://www.postman.com/meta/whatsapp-business-platform/request/lwtlz1k/send-message-template-interactive).
