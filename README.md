# Avocado Health Core Backend

The transactional source of truth for the Avocado Health website, future staff tools, and the separately hosted voice agent.

## Implemented first slice

- Branch, department, and doctor catalogue APIs
- Recurring doctor schedule rules with an explicit `schedule_date` anchor
- Availability generation in the branch timezone
- Short-lived, concurrency-safe slot holds
- Appointment confirmation from a valid hold
- Appointment lookup and cancellation
- Idempotency for hold and appointment creation
- Appointment status history and transactional outbox events
- PostgreSQL migration, Docker Compose, and API tests
- Authenticated WhatsApp booking service API, staff PDF/photo uploads, support cases, and reminder jobs

The voice agent uses the authenticated `/api/v1/integrations/voice/*` routes as its source of truth for doctors, schedulable branches, availability, holds, and bookings. It must only speak a confirmation after the appointment endpoint succeeds.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

API documentation is available at `http://localhost:8000/docs` and health checks at `http://localhost:8000/api/health/live` and `/api/health/ready`.

For a lightweight developer run without Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
DATABASE_URL=sqlite:///./avocado.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite:///./avocado.db .venv/bin/uvicorn app.main:app --reload
```

## Important behavior

- Availability is advisory until a hold is created.
- `schedule_date` is the first concrete occurrence of a weekly schedule; `effective_until` can end the recurrence.
- Voice directory responses include only branches that currently have an active schedule for that doctor.
- Holds expire after the configured duration.
- A database constraint prevents two active reservations for the same doctor and exact time range.
- Confirmation, status history, and the notification outbox event commit together.
- General notification delivery is not yet implemented; the transactional outbox is ready for a worker. The separate WhatsApp reminder worker can send approved templates when explicitly enabled in the bot.

See the frontend repository's `BACKEND_ARCHITECTURE.md` for the complete delivery plan.

## Virtual OPD development accounts

The development seed creates named hospital accounts so `/admin` and `/virtual-opd` exercise the same session and authorization model used by the API:

- Administrator: `admin@example.com` / `change-me-in-production`
- Assigned doctor: `doctor@example.com` / `doctor-demo-password`
- Patient: `patient@example.com` / `patient-demo-password`

These credentials are development fixtures only. Production startup rejects the default bootstrap password and Jitsi secret. Set secure cookies behind HTTPS and configure the Jitsi issuer, app ID, domain, and signing secret for the protected deployment.

After production migrations, create the first named administrator with `python -m app.bootstrap` using `DEFAULT_HOSPITAL_SLUG`, `BOOTSTRAP_ADMIN_EMAIL`, and a one-time `BOOTSTRAP_ADMIN_PASSWORD`. Rotate or remove that bootstrap password immediately; subsequent staff access should use the membership administration workflow.

## WhatsApp local pilot

The [WhatsApp contract](./WHATSAPP_CONTRACT.md) lists every bot-facing route and the patient ownership rule. Run this backend on `127.0.0.1:8000`, then open `http://127.0.0.1:8000/whatsapp-assets` for the staff drag-and-drop page. Enter `ADMIN_API_KEY` from your local environment; the page keeps it in memory only. Upload one PDF per specialty and a PNG/JPEG portrait per doctor. Uploaded files live in `MEDIA_DIR`; back up that directory along with the database.

Set a distinct `WHATSAPP_SERVICE_API_KEY` and a long random `WHATSAPP_OWNER_SECRET` in the backend environment. Configure the Node bot with the same service key and `BACKEND_URL`. The bot must verify Meta webhook signatures before it sends a `sender_id` to this API. The owner key is derived from that verified sender and never sent by patients. The WhatsApp route only lists or manages appointments created by that WhatsApp sender; it does not reveal existing web or voice appointments by matching a phone number.

The direct public hold and appointment endpoints are disabled when `APP_ENV=production` until the website gains patient authentication. The authenticated voice and WhatsApp integration routes remain available. Reminder jobs are created only when the patient chooses reminder consent. The WhatsApp worker must have an approved utility template configured before it polls due jobs; a successful Meta send request records dispatch, not final delivery.

This repository still seeds illustrative doctors and schedules in development, with schedules only at the first branch. Replace those records with approved clinic data before setting a bot to clinic-ready mode. Production requires PostgreSQL migrations, durable uploaded-file storage, service credentials, staff access controls, and a phone walkthrough; local API tests alone do not establish those conditions.
