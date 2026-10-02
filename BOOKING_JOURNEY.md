# Appointment journey: implementation and operation

The backend is the booking authority. The patient website routes ordinary booking to `/book/`; `booking_preview=true` retains the explicit website prototype. Google appointment links can point to `/book/?source=google_business&doctor=<backend-slug>&branch=<backend-slug>`. Slots are displayed on our booking page; this does not publish native slots on Google.

## Phone verification through WhatsApp

1. The browser accepts the clinic booking privacy notice and enters its international WhatsApp number.
2. The backend stores a hashed browser token and an expiring, hashed challenge. It returns a five-minute `wa.me` verification link.
3. The patient sends the prepared message from that number. The signed Meta webhook persists the inbound event; the worker verifies the sender through the service-only backend route.
4. The original browser checks verification. Its HttpOnly cookie owns holds; the verified number authorizes website appointment management for 30 minutes. There is no public verification bypass or user-supplied owner key.
5. Availability, temporary hold, fee review and confirmation use the same database authority as WhatsApp and voice. The appointment, confirmation event, explicit reminder preference and reminder job commit together.

Verification is proof of control of a phone, not proof of legal identity. People sharing a number can see website bookings for that number. Verification does not opt into marketing. Patients without WhatsApp need reception assistance. The existing WhatsApp booking conversation remains available when browser booking is disabled.

## Patient and staff controls

Patients can download a calendar file, view arrival details and directions, cancel future website visits, reschedule within the same doctor/clinic/visit type, and consent to a dated waitlist. Changing doctor, clinic or visit type requires cancellation and a new fee review. Reminder jobs are queued work, not delivery evidence.

The appointment staff workspace includes rescheduling and waitlist offers. An offer reserves actual capacity until its hold expires; acceptance is atomic and replay-safe. Offers currently require staff-approved contact and the patient to refresh the secure booking page; this implementation does not automatically message offers. Expired offers return to waiting while preferences are still valid. Joining the waitlist requires explicit consent; STOP ALL prevents preparing a WhatsApp offer.

Schedules include doctor absence/blocked time. Staff preview affected confirmed or checked-in visits and acknowledge the exact list before saving. A block invalidates outstanding holds but preserves confirmed appointments for staff resolution. Staff actions leave an audit record. Reception staff have appointment controls; Google/growth access remains the separate existing RBAC module. Website verification depends on the WhatsApp module being enabled.

## Deployment

Apply `uv run --locked alembic upgrade head` (migration `0011_booking_journey`). Build `npm --prefix staff-web ci && npm --prefix staff-web run build` in the API image. Serve `/book`, `/book/`, `/staff/assets/` and `/api/v1/` through the backend on the **same public HTTPS origin** as the website. Retain the website fallback for other routes. `/book` redirects while preserving its query.

Configure server-side `WEB_BOOKING_ENABLED=true`, `WEB_BOOKING_ORIGIN=https://<clinic-domain>` and `WHATSAPP_BOOKING_NUMBER=<international-digits>`. Enable the WhatsApp module with its signed Cloud API webhook and worker operational. Follow `whatsapp-bot/PRODUCTION_DEPLOYMENT.md`; do not use the fictional preview number. Production cookies are Secure and SameSite Strict; mutations require exact origin and session CSRF. Privacy notices must describe the actual clinic/operator and processing. Clinic roster, fees, schedule, addresses and directions must be approved before activation.

The feature defaults off and cannot operate with DEMO_MODE. Development receipts are labelled test bookings. Keep secrets on the server. Provision named staff through the existing operator CLI; there are no new default login credentials. Browser verification is rate limited to five challenges per number or hashed IP per hour. Challenge creation prunes session/challenge records that expired more than one day ago, retaining hourly rate-limit evidence. The clinic still needs an overall patient-data retention policy.

## Analytics and external boundaries

Appointments persist acquisition source (`direct`, `google_business`, `organic_search`, `paid`, `referral`, `unknown`) and demo status. Existing growth reporting can attribute authoritative outcomes. Existing PostHog website collection and aggregate reader remain separate; adding this page does not claim a complete live PostHog funnel. PostHog credentials, consent policy and production event reconciliation are still required.

Google OAuth/profile publishing, native Google appointment-slot distribution, automatic waitlist outreach, deposits/payments, calendar synchronization and live voice/Meta delivery are not implemented or proven by this change. A local successful booking is not a deployed clinic outcome.
