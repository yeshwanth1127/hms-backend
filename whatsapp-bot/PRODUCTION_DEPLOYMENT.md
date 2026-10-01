# WhatsApp production deployment

This repository is prepared for a clinic deployment; it has **not** been deployed or accepted on a real clinic number. Keep `WA_CLINIC_READY=false` on the local test number.

## Required topology

1. Put a stable HTTPS reverse proxy in front of the Node bot. Expose only `GET/POST /webhook` and, to your monitoring system, `/health/ready`. Preserve the raw request body and `X-Hub-Signature-256` header. Use a fixed hostname; a temporary tunnel is unsuitable.
2. Run **one** bot replica. The backend PostgreSQL database is the durable inbound queue and deduplication store. The bot acknowledges Meta only after the message is committed, then one worker processes it. Additional bot replicas need shared per-sender send coordination before they are safe.
3. Keep the FastAPI backend behind private HTTPS. Run Alembic migrations before starting either service. Set `APP_ENV=production`, a PostgreSQL `DATABASE_URL`, strong `ADMIN_API_KEY`, `VOICE_SERVICE_API_KEY`, `WHATSAPP_SERVICE_API_KEY`, and `WHATSAPP_OWNER_SECRET` (each at least 32 random characters), and an absolute, backed-up `MEDIA_DIR`.
4. Provide ClamAV on a **private Unix socket** as `MEDIA_SCAN_SOCKET`. Do not expose a clamd TCP port publicly. Set `StreamMaxLength` above 16 MB and keep its signature database updated. Both patient attachments and staff PDF/photo uploads fail closed if the scanner is unavailable. The socket must be accessible to the backend process.
5. Store the Meta app secret, production system-user access token, webhook verify token, service key, and backend keys in the host's secret manager. Do not bake `.env` into images, commit it, or print it in logs. Restrict backend and media-storage access; back up PostgreSQL and media together.

The bot image can be built from the repo root with `docker build -f whatsapp-bot/Dockerfile whatsapp-bot`. Mount a clinic-approved PNG/JPEG welcome image into the container; the bundled `welcome.png` is demo artwork and is rejected by the production guard. The image binds port 8787 inside the container. CI builds both images, exercises the booking and queue contract against disposable PostgreSQL, and starts the coupled development bot. Inspect the latest CI result and scan release images before deployment; these checks do not establish a production deployment or live Meta delivery.

## Configuration and preflight

Set `WA_ENV=production`, `WA_MODE=backend`, `WA_CLINIC_READY=true`, `WA_LIVE_NUMBER_CONFIRMED=true`, `WA_BIND_HOST=0.0.0.0`, `BACKEND_URL=https://...`, `BACKEND_WHATSAPP_SERVICE_KEY`, `WA_VERIFY_TOKEN`, `WA_APP_SECRET`, `WA_PHONE_NUMBER_ID`, `WA_ACCESS_TOKEN`, `WA_GRAPH_VERSION`, and an absolute `WA_WELCOME_IMAGE_PATH`. `WA_LIVE_NUMBER_CONFIRMED=true` is a human attestation after checking the registered number; code cannot prove who owns it. The production guard rejects demo mode, weak secrets, plaintext backend URLs, and the bundled demo image.

Use a production **system-user** token with the WhatsApp permissions and access to the intended business account. Meta's dashboard test token expires and must not be used for deployment. Rotate secrets through the secret manager and restart the bot. Verify the callback on the fixed HTTPS URL and subscribe to `whatsapp_business_account.messages` only after the service is healthy.

Run `npm --prefix whatsapp-bot run preflight` with the production environment before switching the webhook. It checks the backend queue and scanner, active branches and specialties, a PDF for each specialty, a portrait for each active doctor, the welcome image, and Meta access to a non-test phone number. It does **not** verify that doctor facts, schedule rules, fees, identity rules, or staff procedures are clinically correct. Staff must approve those separately.

The backend has illustrative seed doctors and schedules in development only. Populate production records from approved clinic data, then confirm that holds and appointments write to the actual booking authority. If the clinic's real HMS is a different system, its booking contract must be integrated before enabling `WA_CLINIC_READY=true`.

## Rollout and operations

- Complete a two-phone walkthrough: `hi`, specialty PDF, doctor photo, current slots, held slot, explicit booking, reference-gated visit lookup, reschedule, cancellation, issue, rating, supported media, and an opted-in reminder. Verify the appointment and case in the backend, not just WhatsApp messages.
- Use an approved utility template for reminders and set `WA_REMINDER_TEMPLATE_NAME` only after its three parameters (reference, doctor, local date/time) are approved. The reminder worker never retries an ambiguous Meta send automatically. No payment or UPI request is enabled.
- Check `/health/ready` and the staff desk's **Messages needing attention** section. An `uncertain` item may have reached the patient. Check Meta delivery status and the booking record before contacting or resending. A `failed` item means processing stopped before an outbound attempt. Alert on any failed/uncertain item and on a persistently growing `pending` queue.
- Deploy with a single bot replica and a drain period of at least 45 seconds. The bot stops accepting requests on SIGTERM and waits for active work. If stopped during a Meta call, the job is quarantined as uncertain after its lease expires.
- Define a clinic retention policy for conversation state, sender IDs, cases, attachments, and delivery metadata. The queue discards message content after terminal delivery status, but the backend retains other patient data until a policy and deletion process are implemented.
- Put the staff desk behind clinic SSO, an allowlist, or a private network in addition to its admin key. Assign people to review issues and delivery exceptions. The current single admin key has no per-staff audit trail.

## Release blockers still owned by the clinic

- A registered production WhatsApp number and system-user token; this machine currently uses Meta's test number and a temporary test token.
- Real, approved clinicians, locations, schedules, prices, PDFs, portraits, and a durable media volume; current local records are illustrative.
- Patient identity rules for broader historical and cross-channel access. Production chat currently requires both the sender and a 64-bit booking reference for one visit, with a 30-minute access window. This is a possession check, not a full patient identity system; do not expose a complete visit list or link other channels without an identity decision.
- Operational ownership of support cases, delivery exceptions, backups, scanner updates, secret rotation, and data retention.
- A production PostgreSQL migration and live device acceptance. SQLite tests and a local tunnel do not establish these outcomes.

Meta's official [Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api) describes production system-user tokens. The [Meta WhatsApp SDK webhook reference](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/) documents challenge and signature checks. [ClamAV's INSTREAM protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html) is used for upload scanning.

## Outreach rollout

Apply migration `0006_whatsapp_outreach` and follow [the outreach runbook](../WHATSAPP_OUTREACH.md). Both dispatch switches default off. Complete a verified test send and staff review before enabling patient campaigns. No UPI charge is implemented.
