> Historical research plan, preserved during the local-work reconciliation. The implemented module, migrations and named login are documented in STAFF_WORKSPACE.md, GROWTH_UX_DECISION_BOOK.md and POSTHOG_BACKEND_INTEGRATION.md. Statements below describe the earlier planning state and are not current setup instructions.

# Google Business management and appointment growth

Research and proposed implementation scope, 1 October 2026. No Google connection, published profile edits, live slot feed, or PostHog dashboard is implemented by this document.

## Product outcome

Give clinic staff one place to improve discovery, remove booking friction, and measure confirmed and attended appointments. Optimize for appropriate care and useful bookings rather than clicks alone. The first path is Google Search/Maps → branch-specific booking page → live availability → hold → persisted confirmation → reminder → attendance.

## Current foundation and gaps

The backend already implements branch/doctor catalogues, schedule rules, availability, expiring holds, confirmation, cancellation, appointment status history and transactional outbox events. `app/admin.py` provides analytics, appointment management, schedules, catalogue and operations endpoints. `origin_channel` describes web/voice/WhatsApp delivery channel; it does not establish Google acquisition attribution.

The existing analytics `conversion_rate` divides current confirmed/checked-in/completed appointments by all appointment records. This is a status share, not visitor-to-booking conversion. Rename it in a versioned contract or add an accurately named replacement and retire the misleading label with the consuming UI.

Public holds and appointments are disabled in production pending website patient authentication. The frontend PostHog plan treats its current confirmation as a demo. Connect production-safe booking before promoting a Google appointment link. Existing admin access uses a shared key: introduce staff identities, branch-scoped roles and audit history before multi-clinic Google account management. Existing working-tree changes must be preserved.

## Google capabilities

1. **Appointment link:** Place Actions API manages location action links. Query action-type metadata for the location/country before offering an appointment action. Link directly to the correct branch booking page. Google controls eligibility, rendering and button wording; saving a link is not proof that a specific “Book now” button is visible.
2. **Live slots within Google:** separate Actions Center partner workstream. Determine the current healthcare integration, country support, merchant eligibility and partner acceptance before designing feeds or booking adapters. Generic appointments support is not evidence of healthcare eligibility in India or any other market. Do not promise native slots in the MVP.
3. **Profile management:** progressively expose supported business information, regular/special hours, services, photos, posts and review replies through the appropriate approved APIs. Verify current endpoint support and account permissions per feature before implementation. Profile hours and doctor availability are separate data; never derive one automatically from the other.
4. **Performance:** import supported daily Search/Maps impressions, website clicks, call clicks and directions; monthly search-keyword impressions separately. Unsupported/missing metrics are unavailable, not zero. Booking metrics must retain Google's own provider definition and must not be treated as our persisted appointments.
5. **Access:** project approval, enabled APIs, OAuth consent and an authorized profile manager are prerequisites. Support a manual appointment-link setup while API approval is pending.

## Staff dashboard

| Area | What staff sees and does | Measurement/action |
| --- | --- | --- |
| Overview | Branch/date filters; Google visibility/actions, booking starts, confirmed appointments, attendance | Every card shows source, definition, reporting timezone and freshness |
| Google profiles | Connect Google; map locations to clinic branches; inspect current profile; draft edits and preview changes | Explicit publish with before/after audit and readback |
| Booking links | Generate branch-specific HTTPS booking URL; inspect supported actions; set eligible preferred appointment link | Separate saved/API state from observed Search/Maps visibility |
| Availability | Next available appointments, days without availability, schedule exceptions and filled slots | Fix genuine schedule gaps; never invent capacity |
| Conversion | Consented web funnel, validation friction, no-slot results, slot conflicts and hold expiry | Prioritize the largest measured loss with sufficient sample |
| Reputation | Review inbox and staff-approved public replies | Never disclose a patient's visit, treatment or identity in a reply; no automated clinical replies |
| Experiments | Hypothesis, owner, target cohort, primary metric, guardrails and result | One meaningful change at a time; no causal claims from before/after alone |
| Connection health | Revoked access, failed sync, stale data and pending profile edits | Clear reconnect/retry actions and last successful sync |

Keep operational patient records restricted to booking staff. A marketing viewer receives aggregates and profile data, not the appointment endpoint's patient fields.

## Three sources of evidence

- **Google:** aggregated discovery and profile actions. Call clicks do not prove connected calls or bookings. Do not join Google's impression totals to individual visitors or display an impression-to-confirmation funnel as if it tracks the same people.
- **PostHog:** consented, allowlisted website behavior. Reuse `../brave-mendel/POSTHOG_ANALYTICS_PLAN.md`; avoid duplicating SDK work. Add coarse Google Business entry source and booking outcome semantics through that contract's privacy review. Keep demo/test traffic excluded. No patient identifiers, confirmation codes, reasons, symptoms, exact slots, raw search terms or URLs in analytics. Do not send Google's keyword strings into patient events.
- **Backend:** committed confirmations, cancellations, checked-in/completed/no-show status transitions, capacity and notification outcomes. Count these with database aggregates. Add an idempotent outbox publisher only when the approved event contract permits server analytics; never forward the current outbox payload wholesale to PostHog because it includes booking identifiers. Core operational totals remain usable without analytics consent.

Use an allowlisted acquisition value such as `google_business` on booking entry. Treat it as attributed link traffic, not cryptographic proof of origin. Store delivery channel independently. Preserve source across the booking attempt according to an approved retention/consent policy; no cross-channel patient matching by phone/email. Consented session attribution and operational booking attribution have different coverage, and the dashboard must state that.

Definitions:

- Booking funnel completion = consented eligible attempts reaching authoritative confirmation / consented eligible attempts started, within a defined window. Display counts and coverage.
- Google-link attributed bookings = committed booking creations carrying the accepted coarse source, excluding demo/staff/test records; report cancellations separately.
- Attendance rate = checked-in/completed visits / eligible past appointments, with cancelled visits and unknown outcomes explicitly separated.
- Utilization = reserved appointment capacity / bookable capacity under a documented schedule snapshot and time window. Schedule edits and blocked time affect the denominator.
- No-availability rate = measured eligible availability searches yielding zero bookable slots / measured eligible availability searches. Do not infer it from appointment records.

Use creation-date cohorts for acquisition, visit-date cohorts for attendance/capacity. Do not silently mix them. Google and clinic reporting timezones/latency may differ. Small samples, missing days and disconnected sources must remain visible.

## Conversion improvements in priority order

1. Branch-specific mobile booking entry: correct clinic, address, care selection and earliest real availability immediately visible; retain context across steps.
2. Clear price where approved, consultation type, location and cancellation terms before confirmation; minimal patient fields and verified contact. No mandatory account creation beyond necessary secure verification.
3. Refresh and offer alternatives when a slot is lost or a hold expires. Show the next date/branch with real availability and an honest call/WhatsApp fallback when none exists. Preserve appropriate user input securely.
4. Persist confirmation before showing success; give secure cancellation/rescheduling access. Add rescheduling backend support before promising it in the UI.
5. Consent-based reminders, cancellation release and staff-approved waitlist offers to reduce empty slots. Never send abandoned-booking messages based only on analytics activity; require a separate lawful opt-in and operational contact workflow.
6. Keep factual profiles, special hours and service information current. Invite genuine reviews consistently without incentives or filtering by sentiment.
7. Test earliest-slot prominence, CTA placement and fewer unnecessary steps after baseline data exists. Guard against conflicts, cancellations, inappropriate bookings and staff workload; avoid false urgency or guaranteed medical outcomes.

## Backend implementation sequence

**Phase 1 — trustworthy booking and growth overview.** Audit production website authentication/booking integration and staff permissions. Define metrics and source attribution; correct conversion naming. Add date/branch filters and database aggregation instead of loading every appointment. Provide aggregate growth endpoints independent of PostHog availability. Acceptance: totals reconcile with known backend records, branch access is enforced, demo data is excluded, concurrent booking and expired-hold journeys behave correctly.

**Phase 2 — Google connection and booking links.** Implement OAuth with state validation and server-side token storage protected at rest; never send refresh tokens/shared admin secrets to browsers. Add account/location discovery, explicit branch mapping, disconnect/revocation handling and capability checks. Read current links before mutation, validate owned HTTPS destinations, require a staff publish action, read back changes and inspect real Search/Maps visibility. Manual setup remains available. Acceptance: authorized test profile and revoked-access tests; link saved and visibility reported as separate checks.

**Phase 3 — Google performance and actionable funnel.** Scheduled incremental imports with backfill, deduplication, bounded retries, quotas and freshness metadata. PostHog connection credentials stay server-side; fetch approved aggregate insights or link to approved dashboards initially. Cache reports and show partial-source errors. Acceptance: Google imported values reconcile with its source for the same dates; backend booking totals reconcile independently; no invented cross-source conversion rates.

**Phase 4 — broader profile controls and retention.** Hours/services/photos/posts and review workflows after endpoint verification; audited drafts/publish and ownership conflict handling. Add approved reminder/waitlist/reschedule operations and outcome reports. Acceptance: change history and public readback, no sensitive public reply content, no duplicate outreach.

**Phase 5 — native Google appointment inventory, conditional.** Obtain healthcare/country eligibility confirmation and partner acceptance first. Then design feed freshness, availability updates, booking adapter, cancellations and sandbox isolation for the selected integration. All channels share the same authoritative reservations. Acceptance includes provider sandbox validation and live eligible profile observation; API success alone is insufficient.

Proposed resources, not existing routes: `/api/v1/admin/growth/summary`, `/growth/funnel`, `/google/connections`, `/google/locations`, `/google/locations/{id}/booking-links`, `/google/locations/{id}/performance`, `/google/changes`. Do not expose staff-level OAuth callbacks or publishing under unauthenticated public routes.

Likely new tables: Google connection/token references; branch/location mapping; daily metric and monthly keyword snapshots; proposed profile changes/audit records; booking acquisition metadata. Reuse existing appointment/status/outbox tables. Retain only necessary provider data and apply clinic-scoped authorization to every resource. Avoid a generic integration framework until another provider actually needs it.

## External prerequisites and verification limits

Need approved clinic/location data, real public booking domain, production patient/staff authentication, Google profile manager access, Cloud project/API approval and OAuth configuration. PostHog implementation remains a separate ongoing workstream. Native healthcare slots require confirmed Google partner/country support.

This plan is based on local source review and official Google documentation. Deployment, clinic bookings, Google permissions, public button visibility, native slot support and PostHog receipt remain unverified.

## Official references

- [Place Actions API](https://developers.google.com/my-business/reference/placeactions/rest)
- [Location action links](https://developers.google.com/my-business/reference/placeactions/rest/v1/locations.placeActionLinks)
- [Google Business API prerequisites](https://developers.google.com/my-business/content/prereqs)
- [OAuth setup](https://developers.google.com/my-business/content/implement-oauth)
- [Performance metrics](https://developers.google.com/my-business/reference/performance/rpc/google.mybusiness.performance.v1)
- [Actions Center](https://developers.google.com/actions-center)
- [Appointment integration support and country checks](https://developers.google.com/actions-center/verticals/appointments/redirect/support)
