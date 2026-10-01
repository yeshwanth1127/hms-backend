> Historical implementation record, preserved during reconciliation. Its bearer-token setup, migration numbering and isolated harness are superseded by STAFF_WORKSPACE.md and the canonical migration chain through 0009_client_modules. Do not use this document as deployment instructions.

> Current entry point: `/staff/google_business/overview`; `/growth` redirects there. Staff sign in with username/password. The optional-module update at the end supersedes the historical bearer-token setup instructions below.

# Appointment growth: first working slice

Implemented 1 October 2026 in the isolated `codex/google-business-growth` worktree. The worktree includes the pre-existing uncommitted WhatsApp working state as its baseline. Those inherited changes are not new growth work and must not be blindly staged or discarded.

## Run and review

Apply `alembic upgrade head` against the intended development database before starting the backend. `create_all` does not add columns to an existing database. Migration `0005_growth_foundation` follows the inherited `0004_whatsapp_inbound` migration; `0006_growth_staff_access` adds named staff identities and revocable credentials.

Set `BOOKING_ALLOWED_ORIGINS` to a comma-separated list of approved HTTPS origins, without paths or trailing slashes, for example `https://booking.your-clinic.example`. The list defaults to empty and link preparation returns a configuration error until set. This permits preparing a URL; it does not verify that its page actually books appointments. Only add a prepared link to Google after the destination accepts `branch` (clinic slug) and `source=google_business`, uses real availability, authenticates patients and persists confirmations.

Open `/growth` on this backend. Enter an individually issued staff access credential. The page retains it in JavaScript memory only; locking revokes the credential server-side. Reloading clears browser access but does not revoke the credential. Every growth/Google API requires a valid bearer credential and the corresponding permission; `X-Admin-Key` is not accepted on these routes. The HTML shell is public and contains no protected data or credentials.

Owner and Growth Manager can read aggregate metrics, prepare Google links and inspect growth audit history. Receptionist has none of these permissions. Permissions are checked against the current database role and active state on each request. Disabled identities, expired/revoked credentials and unknown roles fail closed. Growth credentials cannot access the legacy patient-management API. Existing operations authentication is unchanged; do not give its shared administrator key to growth staff.

Issue an access credential with the operator-only CLI, after migrations:

```sh
python -m app.staff_access --name "Designated Growth Manager" --role growth_manager --hours 8 --output /private/absolute/path/staff-access.txt
```

The output file must not already exist; it is created with mode 600. The database stores only the SHA-256 digest of a randomly generated high-entropy token, not the token itself. Credentials expire after 8 hours by default (maximum 24 hours). Existing identities cannot silently change roles when issuing a credential. No default accounts, public registration or client-controlled role grants exist. This is an operator-provisioned development identity boundary; normal staff login/SSO and account administration still need integration with the eventual identity system. Roles currently span one backend clinic organization; per-branch and tenant isolation remain unimplemented.

The current development preview runs at `http://127.0.0.1:8017/growth` with an isolated SQLite database, illustrative seeded catalogue and the non-live `clinic.example` approved origin. It is not a production booking deployment.

## Delivered

- `/api/v1/admin/growth/summary`: SQL aggregate counts with branch, inclusive date range (at most 366 days), branch-local timezone, creation/visit cohort and explicit demo inclusion. Returns status, delivery-channel and acquisition-source breakdowns without patient fields. Empty rate denominators are null; absent Google/PostHog sources stay unavailable.
- Attendance uses ended visits with recorded outcomes. Checked-in/completed versus no-show form its denominator; cancelled and unresolved outcomes are separately exposed. No capacity or visitor conversion is fabricated.
- Appointment creation accepts only an enumerated coarse acquisition source. The server marks non-production confirmations as demo. Replayed idempotent confirmations retain the original attribution and demo state.
- Legacy rows migrate as demo/unverified and unknown-source to avoid counting prior test bookings as live clinic success. Reclassify verified historical production records only through a separately reviewed reconciliation; do not bulk clear this flag.
- Manual Google booking-link preparation for active physical branches, approved HTTPS origins, controlled query parameters, canonical branch/source routing, idempotent updates and audit history. No HTTP call is made to the booking URL or Google.
- `/api/v1/admin/google/booking-links` lists prepared links; PUT `/google/booking-links/{branch_id}` prepares or updates; `/google/changes` exposes bounded history. API publication and public Google visibility remain explicitly unverified.
- Legacy `/admin/analytics` adds `retained_confirmation_share` and deprecation metadata for `conversion_rate`. The old field remains for compatibility. The existing frontend admin card still requires a coordinated label/contract update; this new dashboard does not call it visitor conversion.

## Verification

Automated tests cover auth, demo/branch filtering, local-midnight boundaries, creation versus visit cohorts, missing denominators, sensitive-field exclusion, allowlisted source attribution, replay invariance, URL validation, audit deduplication and virtual-branch rejection. Existing booking and WhatsApp tests are included.

All 25 tests passed, including receptionist denial across every growth/Google resource, shared-key rejection, immediate role/disable checks, expiry, logout revocation and named audit actors. Fresh SQLite migration and browser login/manual link-save journey were verified locally. `alembic check` still reports twelve missing indexes on pre-existing catalogue, reservation, history and outbox tables; these originate in the initial migration and are outside this slice. No drift was reported for the new growth tables or attribution columns. PostgreSQL migration, real clinic operation, OAuth, Google publication, Google button visibility and PostHog ingestion remain unverified.

## Next implementation work

1. Production-safe website booking and integration of the clinic’s normal staff identity provider with these role/permission checks.
2. Google OAuth, encrypted token storage, explicit location-to-branch mapping and API capability discovery.
3. Audited Google appointment-link publishing with readback and real-profile observation.
4. Google daily performance imports and approved aggregate PostHog insights.
5. Supported profile edits, hours, services, photos/posts and staff-reviewed review replies.
6. Native healthcare inventory only after confirmed partner/country eligibility.

## New-profile onboarding

The clinic has no existing Google Business Profile. `/api/v1/admin/google/setup` and the dashboard explicitly report an uncreated/unconnected state. The owner must prepare factual physical-clinic information, create the profile under their Google account and complete Google-selected verification before connecting it. Do not create a fictional test clinic on Google. Draft UI previews do not establish a public listing, verified ownership or button eligibility. The Growth Manager’s backend role does not grant Google account/profile access; those permissions must be set separately in Google.

## Interactive Google appearance preview

The authenticated growth workspace now includes a browser-local draft editor and desktop/mobile profile illustration. Users can compare observed owner-view details, a proposed appointment link and a future native-slot concept, toggle photos/services/posts/reviews, and open an illustrative booking handoff. No draft values are persisted or transmitted to Google. No rating, patient review, clinic image, treatment claim or real appointment slot is invented.

`/api/v1/admin/google/capabilities` exposes ten planning areas with source links, implementation/eligibility boundaries and the existing growth-read permission. Receptionists are denied. Google setup now says `not_connected`, since the user created a profile and we observed an owner-view verification-processing state; this endpoint does not claim a live Google status sync.

The preview is not a pixel-exact Google layout or a provider capability check. Google determines public rendering and appointment actions. Native healthcare slots, publishing, account connection and reporting remain unimplemented. Current WhatsApp/text contact options require verified-profile/region eligibility; the retired Google Business Messages inbox is not a planned integration.

## WhatsApp and production walkthrough studio

The user has no bot business number yet. The visible WhatsApp action therefore opens only a browser-local proposed bot conversation. The clickthrough demonstrates service choice, sample slots, contact-verification simulation, review, a demo confirmation, lost-slot recovery and staff escalation. Website booking, hold expiry, directions, call fallback and future native Google slots also have local walkthroughs. No message, call, case, hold or appointment is created.

Four inline vector illustrations explain discovery, conversation, reservation and attendance. Two clinic-space drawings are clearly concept artwork, not actual photographs or evidence of the physical clinic. Replace them with approved real clinic photos before production.

Official research checked on 1 October 2026: Google lists healthcare in its Appointments Redirect merchant policy and India among supported redirect countries. This does not prove native time-chip rendering or partner acceptance for Avocado Health. Confirm the exact healthcare partner feature set directly with Google before promising visible slots. Relevant sources: https://developers.google.com/actions-center/verticals/appointments/redirect/policies/platform-policies and https://developers.google.com/actions-center/verticals/appointments/redirect/integration-steps/overview . WhatsApp contact requires a verified, eligible profile: https://support.google.com/business/answer/15013580 .

## Optional modules and shared staff UI — 1 October 2026

This phase supersedes the bearer access-credential UI/CLI described above. Normal staff access uses the same username/password, Argon2, HttpOnly cookie and CSRF contract as the WhatsApp session. Google Business and growth analytics are independent optional modules, default off, checked server-side with current staff permissions. Missing WhatsApp switch defaults on to preserve the existing bot; explicit false takes precedence. Admin can change switches; growth_manager may use enabled growth modules; staff/reception is excluded.

React/shadcn screens are in staff-web/src/modules/growth. Shared shell/auth ownership is with the WhatsApp session. The isolated App.tsx and auth copy are a local integration harness, not a second production login system. Integration packet at integration/google-growth/README.md includes unique migrations after canonical staff auth, feature files/model additions, role/module contracts and worker requirements; do not copy duplicate auth models/migrations. Canonical integration must gate WhatsApp routes and workers as well as its existing consent/outreach checks.

UX decision book: GROWTH_UX_DECISION_BOOK.md. Local validation: full backend suite 28 passed, frontend TypeScript/Vite production build passed, fresh SQLite migration passed. Browser verified normal sign-in, module-off sidebar change, persisted switch state after reload; provider/deployment verification remains separate. Per-clinic deployment, not multi-tenant SaaS isolation.

### Shared backend integration verified

Unique growth routes, models, migrations and React feature components were integrated by the WhatsApp session into hms-backend-whatsapp's canonical staff shell. The shared components were adapted to its shadcn Base UI controls. Canonical migration chain through 0009_client_modules passed on a fresh disposable SQLite database. Browser on localhost:8020 verified the actual canonical shell, normal sign-in, Google module alongside Appointments/Doctors/Schedules/WhatsApp, independent persisted opt-out, direct-route unavailable state, re-enablement and sample WhatsApp confirmation dialog. localhost isolates the cookie from the parallel127.0.0.1:8012 development session.

Isolated growth backend suite: 28 passed. Shared build passed; broader canonical backend/WhatsApp validation and PR2 commit/push/CI remain owned by the WhatsApp session. No deployment or provider publication occurred. Screenshots: output/integrated-google-business.png and output/integrated-module-opt-out.png.
