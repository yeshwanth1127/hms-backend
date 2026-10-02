# Appointment flow verification — 2 October 2026

## Passed locally

- Full backend suite: 91 tests passed with independent PostgreSQL connections enabled for booking, voice admission and WhatsApp outreach. Migration upgrades from base and both historical branches reach `0011_booking_journey` and preserve existing clinic records.
- Nine booking journey tests prove request-to-database results: verified production booking, exact origin/CSRF checks, wrong sender and session expiry, per-phone access, duplicate-safe confirmation, fee changes, schedule changes, cancellation, rescheduling, waitlist offers/acceptance/expiry, reminder consent, STOP ALL and staff check-in.
- PostgreSQL races prove two overlapping holds cannot both succeed and simultaneous identical retries return one hold. Existing voice/outreach concurrency tests also pass.
- WhatsApp bot: 37 unit tests and one full real HTTP integration passed. A signed synthetic webhook is durably accepted and processed by the worker, verifies the original browser session, then permits availability → hold → confirmation → replay → cancellation. An independent database query checks booked capacity, Google source attribution and exactly one confirmation event and reminder job. Meta outbound transport is simulated.
- Website: 46 tests passed and production build passed. Ordinary booking links delegate to the backend; explicit prototype routes remain test-only. Website source and clinic deep-link parameters are preserved.
- Backend shadcn workspace/patient booking production build passed. Lint completed with warnings (existing and new React effect/fast-refresh warnings); lint is not warning-free.

## Observed browser evidence

Local preview: `http://localhost:8031/book/`, staff workspace `http://localhost:8031/staff/schedules`. Development uses fictional clinic data and a fictional bot number.

A browser booking for **Fictional Meeting Patient** saved reference **AVO-184D51F8E7D068EE**. A separate query found its confirmed appointment, booked reservation, `google_business` source, one confirmation event and one reminder job. Its receipt explicitly identifies a test booking. The verification step in this browser walkthrough was completed through the trusted local service route; the separate real HTTP test exercises the signed webhook and worker boundary.

The staff browser previewed the persisted appointment affected by doctor blocked time, acknowledged the exact impact, and saved a block while keeping the visit booked. The patient cancellation confirmation dialog was checked without cancelling the browser receipt. Screenshots are local ignored evidence in `output/booking-confirmed.png` and `output/schedule-impact-review.png`.

## Not verified live

No production deployment, real phone ownership, Meta delivery/read receipt, Sarvam call, Google profile publishing or PostHog project query was proven. No patient messages were sent. Production requires approved clinic data, HTTPS/same-origin routing, a registered WhatsApp number, signed webhook and working worker, server secrets and module enablement. Google profile automation/native slot distribution and automatic waitlist outreach are separate remaining implementation work.

## Reproduce

```sh
uv sync --locked --extra dev
npm --prefix staff-web ci
npm --prefix staff-web run build
uv run --locked pytest
npm --prefix whatsapp-bot test
npm --prefix whatsapp-bot run test:integration
```

For row-lock proof, set `HMS_BOOKING_DATABASE_URL`, `HMS_VOICE_DATABASE_URL` and `HMS_OUTREACH_DATABASE_URL` to a **disposable PostgreSQL test database**, then run pytest. Each enabled fixture uses an isolated random schema and drops only its own schema. Without these variables, PostgreSQL-only race tests skip. CI now runs all three suites against its disposable Compose PostgreSQL service. Provider messages are simulated in the HTTP test; do not infer live delivery from its pass.
