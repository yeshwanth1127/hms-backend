# Appointment automation meeting coverage

Audit: 1 October 2026. Scope confirmed by the user: discovery through clinic arrival, not a full hospital management system. Read-only source/runbook review; no live provider or deployed patient journey was exercised for this audit.

Canonical backend: `hms-backend-whatsapp`, main at `0d1d9c9`. Main CI for this revision passed: https://github.com/yeshwanth1127/hms-backend/actions/runs/36877973497. CI does not prove live delivery, calls, Google visibility or production bookings.

## Coverage and gaps

| Patient stage | Implemented coverage | Missing or not yet proven |
| --- | --- | --- |
| Discover | Patient website; doctor/specialty/location content; Google profile concept preview; approved-origin branch booking-link preparation | Google OAuth, profile editing/publication, performance imports and review inbox/replies are not implemented. SEO launch remains gated pending approved facts. Native Google slots are not an accepted integration. |
| Decide | Doctor portraits/guides; consultation fee and clinic address in WhatsApp; directions and arrival instructions; browse-before-book | Clinic-approved content and real schedules must be supplied. Website branch/source deep links need implementation, rather than assuming generated parameters work. |
| Book | Shared backend availability, expiring holds, transactional confirmation; WhatsApp flow; tracked voice booking tools | Website still uses sample slots and local demo verification, with no appointment submission. Production public booking mutations are blocked pending patient authentication. Real voice/provider hooks and WhatsApp delivery need verification. |
| Recover from friction | Alternate WhatsApp dates; reception handoff; conflict/expiry handling in the booking foundation | No durable consented waitlist/cancellation-fill workflow. No verified universal website fallback or secure cross-channel continuation. Booking is English; multilingual outreach templates do not prove multilingual booking. |
| Manage visit | WhatsApp cancellation/rescheduling; sender/reference access controls; appointment status history | Secure website visit management and equivalent staff rescheduling need completion. Voice lookup uses phone plus reference, not OTP identity verification. |
| Remember and travel | Consent-based WhatsApp reminder worker; receipt address, Maps link and arrival instructions | Live reminder receipt and delivery exceptions need rehearsal. General SMS/email/calendar delivery and patient arrival acknowledgement are not established by the outbox. |
| Arrive | Staff appointment filters, patient details, check-in, completed/no-show/cancelled status actions | No patient self-check-in, queue position or ETA feature. Staff statuses require an actual clinic operating procedure. |
| Improve | Backend acquisition/status/attendance aggregates; PostHog aggregate reader; outreach delivery/engagement reports | PostHog credentials/receipt pending; website events remain demo; no real visitor-to-confirmation funnel, branch website attribution or Google performance ingestion. No measured uplift claimed. |
| Operate | Named login, role restrictions, independently optional modules, audited changes, consent/STOP, uncertain-send quarantine, voice quotas | Clinic per deployment, not shared-database multi-tenancy. No MFA/SSO claim. Backup restoration, production monitoring, support staffing and incident response require operational proof. |

## Recommended order before the meeting

1. **Complete authoritative website booking.** Verified patient contact/session, real catalogue and availability, hold/expiry/conflict recovery, committed confirmation, secure cancellation/rescheduling. Consume the correct branch and allowlisted source from Google links. Never remove the production protection simply to make the demo work.
2. **Prove one configured channel end to end.** Real approved clinic data and test recipients; booking visible in the staff desk; confirmation, reminder, cancellation/rescheduling and reception reply actually received. For voice, verify trusted lifecycle hooks and an actual call before claiming it live. Keep an isolated demo as a fallback.
3. **Finish schedule disruption operations.** Availability already reads ScheduleException records, but there is no reviewed staff exception CRUD route in app/admin.py. Add leave/holiday/blocked-time controls, affected-booking preview, staff rescheduling and explicit reviewed patient notification. Removing recurring rules alone is insufficient.
4. **Add a genuine opt-in waitlist.** Patient-approved doctor/branch/time preferences, expiring offers, current consent/STOP checks and atomic first-acceptance booking. A reception request currently does not create a waiting-list place. Do not message analytics-only abandoners without an operational opt-in.
5. **Activate discovery and measurement accurately.** Verify Google profile and available booking/WhatsApp controls; point to a working landing journey. Configure PostHog and correlate consented booking attempts with authoritative outcomes before claiming conversion. Manual Google configuration is a valid first release; automated profile management is a separate feature backlog.

## Buyer-dependent additions

Useful next: appointment calendar download, accessibility/language walkthrough, delivery-failure alert routing, reception response-time indicators, capacity/no-availability/hold-expiry reporting and aggregate exports.

Add only if required by the clinic: deposits/UPI with refunds and reconciliation; HMS/calendar integration with explicit slot ownership; multilingual patient booking; family/dependent booking; virtual consultation provider integration. None should be presented as already complete.

## Five-minute meeting demonstration

Use fictional demo data unless a verified live test setup exists. Label provider simulations.

1. Enter from a clinic-specific discovery link, choose a doctor and inspect truthful fees/location.
2. Show actual booking channel holding and confirming a slot; find the matching backend appointment. If website booking is still demo, explicitly use the implemented WhatsApp/test path rather than implying the website submitted it.
3. Show the receipt, directions, reminder, patient cancellation/rescheduling and reception fallback; distinguish a simulated receipt from real provider delivery.
4. Check in through the staff desk and show the change in persisted operational reports.
5. Sign in as reception versus growth manager and disable a module to demonstrate both hidden navigation and denied API access.

Prepare the normal path, no-slot/conflict path, provider failure path and doctor-unavailable path. State current limitations before the buyer discovers them. Do not present native Google slots, real PostHog conversions or live voice recordings using illustrative fixtures.

## Evidence and platform boundaries

Source anchors: `app/api.py` (production website booking guard); website `src/components/booking/ScheduleAppointmentPage.tsx` and its Original counterpart (demo slots/verification); `app/growth.py` (manual link setup); `app/services.py` (availability/holds and schedule exceptions); `WHATSAPP_OUTREACH.md`; `VOICE_MODULE.md`; `POSTHOG_BACKEND_INTEGRATION.md`; `DASHBOARD_MIGRATION.md`; `STAFF_WORKSPACE.md`.

Google [Appointments Redirect](https://developers.google.com/actions-center/verticals/appointments/redirect/overview) redirects to the provider's booking page and requires eligibility/partner steps. It does not establish our eligibility for native healthcare slots. Google [WhatsApp contact options](https://support.google.com/business/answer/15013580) require a claimed/verified profile and are available only in selected regions/profiles. Public display must be observed on the actual profile.

Some older deployment runbooks still describe shared admin-key UI and old migration heads; current named staff authentication, module and voice documentation supersede those statements. Reconcile these instructions before a client handover.

Feature breadth cannot guarantee a sale. The defensible offer is reliable appointment acquisition and attendance, demonstrated with operational evidence, transparent optional modules, a clear support owner and explicit activation requirements.
