# WhatsApp integration contract (local pilot)

The existing FastAPI backend owns clinical catalogue, availability, holds, appointments, uploaded staff assets, support cases, and reminder jobs. The Node WhatsApp service verifies Meta webhooks and formats/sends WhatsApp messages. The Node service calls only `/api/v1/integrations/whatsapp/*` with `X-Service-Key`; staff asset management uses `X-Admin-Key`. Keys remain server-side.

The Node runtime is included in [`whatsapp-bot/`](./whatsapp-bot/README.md), with its own tests and container. Run one worker replica. Upgrade Alembic to `head` before starting it; `0005_merge_whatsapp_schedule` joins the schedule and WhatsApp migration branches.

## Identity and safety

- `sender_id` is the `messages[].from` identifier from a signature-verified Meta webhook. The backend derives an opaque `owner_key` from it using HMAC; the caller cannot supply an owner key. Production chat additionally asks for the 64-bit booking reference before showing a historical visit or allowing a change/cancellation, and that access expires after 30 minutes. This reduces exposure when a phone number is reassigned; it is not a complete patient identity system. It does **not** link pre-existing web, voice, or staff bookings by typed phone number.
- Patients confirm the selected slot and provide a name before the bot creates an appointment. The bot says `confirmed` only after the backend returns a confirmation code. Availability alone is advisory; a hold can expire or conflict.
- No real doctor claims, medical advice, patient documents, or automated follow-ups should be enabled before clinic content, staff ownership, consent, and approved WhatsApp templates are configured.
- `idempotency_key` request fields are derived from the inbound WhatsApp message ID and operation and are checked against sender and request content on replay.

## Service endpoints

All paths have prefix `/api/v1/integrations/whatsapp` and require `X-Service-Key`.

| Method and path | Request | Response / rule |
| --- | --- | --- |
| `GET /conversations/{sender_id}` | none | Saved conversation step and latest prepared reply for restart recovery. |
| `PUT /conversations/{sender_id}` | `state`, `last_message_id`, `last_reply` | Persist progress before outbound send; the service key is required. |
| `POST /inbound` | `message_id`, `sender_id`, parsed `payload` | Commit a unique inbound event before acknowledging Meta; duplicates return their existing status. |
| `GET /inbound/ready` | none | Queue schema and, in production, ClamAV socket are ready. |
| `POST /inbound/claim` | none | Claim the next due event, ordered per sender, with an opaque claim token. |
| `POST /inbound/{id}/sending` | `claim_token` | Mark outbound attempt before calling Meta. |
| `POST /inbound/{id}/sent` | `claim_token` | Mark accepted by Meta and discard stored message payload. |
| `POST /inbound/{id}/failed` | `claim_token`, optional `error` | Retry bounded pre-send failures; quarantine ambiguous sends as `uncertain`. |
| `GET /inbound/issues` | optional `limit` | Failed and uncertain events without message content. |
| `GET /catalogue` | none | Active branches and departments; each department includes its current `guide_asset_id`. |
| `GET /doctors?department=<slug>&branch=<slug>` | query filters | Active doctors with stable IDs, branch/department IDs, and `photo_asset_id`. |
| `GET /availability` | `doctor_id`, `branch_id`, `start_date`, `end_date`, `consultation_type` | UTC slot timestamps plus branch timezone. |
| `POST /slot-holds` | `sender_id`, exact slot fields, `idempotency_key` | Hold ID and expiry, or 409 if unavailable. |
| `POST /appointments` | `sender_id`, `hold_id`, `patient_name`, `consent_to_reminders`, `idempotency_key` | Authoritative appointment ID, code, and status. Phone is taken from sender ID; origin is `whatsapp`. |
| `GET /appointments?sender_id=...` | optional `limit` | Only appointments owned by this WhatsApp sender, newest first. |
| `GET /appointments/page?sender_id=...` | `limit`, `offset` | Sender-scoped page with total count so older visits remain reachable. |
| `GET /appointments/by-code/{confirmation_code}?sender_id=...` | reference and sender | Fetch one WhatsApp visit only when both owner and unguessable reference match. |
| `GET /appointments/{id}?sender_id=...` | none | Owned appointment or 404. |
| `POST /appointments/{id}/reschedule` | `sender_id`, `new_hold_id`, `idempotency_key` | Atomic move of the existing appointment to the new hold; old slot is released. |
| `POST /appointments/{id}/cancel` | `sender_id`, `reason` | Cancelled authoritative appointment; repeat is safe. |
| `POST /cases` | `sender_id`, `kind=issue|feedback`, `description`, optional `rating`, `idempotency_key` | Durable case ID for staff review. |
| `POST /cases/{id}/attachments` | multipart `file`, `sender_id`, `source_message_id` | Durable attachment metadata; supports bounded PDF/image/audio/video types. |
| `GET /assets/{id}` | none | Authenticated binary for a current specialty guide or doctor photo. |
| `GET /reminders/due` | `limit` | Due, opted-in reminder jobs claimable by one worker. |
| `POST /reminders/{id}/complete` | `status=sent|failed|uncertain`, optional error | Mark job result; ambiguous sends never retry automatically. |
| `GET /reminders/issues` | optional `limit` | Failed and uncertain reminder jobs. |

## Staff endpoints and upload UI

- `GET /api/v1/admin/whatsapp-assets` lists active specialty guides and doctor photos.
- `POST /api/v1/admin/departments/{id}/guide` accepts one PDF, validates type and size, and replaces the active guide.
- `POST /api/v1/admin/doctors/{id}/photo` accepts one JPEG/PNG and replaces the active photo.
- `GET /api/v1/admin/whatsapp-cases` shows issues, feedback, and attachment metadata for staff.
- `GET /api/v1/admin/whatsapp-delivery-issues` shows failed and uncertain sends for staff review.
- `PATCH /api/v1/admin/whatsapp-cases/{id}` changes a case between open, in progress, and resolved.
- `/whatsapp-assets` is a small drag-and-drop upload page. It asks for the admin key at runtime and does not save it in browser storage.

The guide belongs to a specialty, matching the WhatsApp flow: select specialty → send its uploaded PDF → show the backend doctor list. A missing PDF is stated plainly; no demo PDF is substituted in live mode. A doctor without an uploaded photo gets a text profile.

## Follow-ups

On a confirmed appointment with `consent_to_reminders=true`, the backend creates one reminder job due 24 hours before the appointment (or soon after creation if the visit is sooner). The Node worker sends an approved utility template and acknowledges the job only when `WA_CLINIC_READY=true` and a template is configured. A cancellation suppresses the job; rescheduling moves it. Feedback outreach is intentionally separate and requires approved template/category and consent before being scheduled.

## Local pilot evidence boundary

Tests should cover service authentication, ownership isolation, idempotency, conflict handling, upload validation/replacement, case/media persistence, and reminder state changes. A backend test passing under SQLite does not prove PostgreSQL deployment or Meta phone delivery. A final two-phone walkthrough is required before claiming the integrated flow works on WhatsApp.

Conversation state, inbound deduplication, and the latest prepared reply survive a Node restart. The worker marks `sending` before calling Meta. A crash or timeout at that point leaves an `uncertain` item for staff review rather than automatically repeating a possibly delivered message. Full delivery/read receipts and multi-instance send coordination remain outside this integration. Run one bot replica. The production backend requires PostgreSQL, strong secrets, persistent media storage, and a private ClamAV Unix socket; uploads fail closed if scanning is unavailable.
