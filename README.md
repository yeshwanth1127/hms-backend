# Avocado Health Core Backend

The transactional source of truth for the Avocado Health website, future staff tools, and the separately hosted voice agent.

## Implemented first slice

- Branch, department, and doctor catalogue APIs
- Recurring doctor schedule rules
- Availability generation in the branch timezone
- Short-lived, concurrency-safe slot holds
- Appointment confirmation from a valid hold
- Appointment lookup and cancellation
- Idempotency for hold and appointment creation
- Appointment status history and transactional outbox events
- PostgreSQL migration, Docker Compose, and API tests

The voice agent must call this API for availability and bookings. It must only speak a confirmation after `POST /api/v1/appointments` succeeds.

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
- Holds expire after the configured duration.
- A database constraint prevents two active reservations for the same doctor and exact time range.
- Confirmation, status history, and the notification outbox event commit together.
- Notification delivery is intentionally not yet implemented; the outbox is ready for a worker.

See the frontend repository's `BACKEND_ARCHITECTURE.md` for the complete delivery plan.
