# Local project work reconciled for main

1 October 2026. The canonical backend checkout is `hms-backend-whatsapp`, branch
`codex/whatsapp-outreach`, PR #2. The website is `brave-mendel`, repository
`Sachinskz/hospital-webpage`, branch `main`.

## Current work

- Backend booking/WhatsApp hardening, bot runtime, reception/outreach, the shadcn
  staff workspace, named authentication and module switches are in PR #2.
- Google Business and growth analytics were integrated into the same canonical
  shell. The optional PostHog aggregate reader is in commit `3c59f91` of PR #2.
- The remaining local appointment desk filters (India calendar date, doctor,
  clinic, doctor-name search and stable offset pagination) were recovered from
  the older backend checkout into the canonical appointment endpoint, retaining
  current authentication and status/consent safeguards. The date-boundary and
  pagination regression test is included.
- Parallel test runs now use separate temporary SQLite databases, preserving
  the useful test isolation change from the earlier growth checkout.
- The two remaining website consent lifecycle files are tested and pushed to
  website main in `3d155a9`. This covers returning visitors, revocation/re-grant
  and explicit collection enablement.
- Earlier research and implementation decisions are preserved in
  `GOOGLE_BUSINESS_GROWTH_PLAN.md` and
  `docs/archive/GROWTH_IMPLEMENTATION_2026-10-01.md`, with historical labels.

## Older checkout reconciliation

`hms-backend` and `hms-backend-google-growth` still contain their original local
working states. They are retained for recovery; they are not the deployment
source. Their inbound queue, media checks, production guards and growth module
work are already represented in the canonical implementation. Their former
shared-key/bearer/static-HTML desks, duplicate auth models, migration branches
and standalone integration harness have been superseded by the canonical staff
workspace and single migration head. Copying them over current source would
remove newer authentication, booking, consent and concurrency safeguards.

The growth integration packet was an intermediate handoff and has been applied
to the canonical model/router/migration/UI files. Old `output/` files are local
browser evidence, not runtime code or new feature work. No older runtime or
migration fork is added to the active application.

## Verification and exclusions

- Reconciled backend suite: 58 passed, 1 PostgreSQL-only skip locally.
- Website suite: 49 passed; production frontend build passed. Its existing
  preview/noindex gate remains closed.
- The PR's CI also builds packaged staff UI and both containers, tests the
  PostgreSQL outreach race, and starts the coupled backend/bot.

Credentials, provider keys, local databases, uploads, generated builds,
node_modules and preview account files remain outside Git. Production activation
and actual provider delivery are separate from publishing source to main.
