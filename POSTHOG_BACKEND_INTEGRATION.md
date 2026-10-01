# PostHog in the optional growth module

Implemented 1 October 2026. Frontend SDK/event contract exists; no project/API credentials supplied. Provider receipt and live aggregate queries are unverified.

The Growth analytics screen combines two separate sources: persisted backend appointment/attendance records, and PostHog anonymous website activity. The latter uses fixed aggregate HogQL through a backend endpoint. Never ship the personal read key in browser code, accept arbitrary caller SQL, forward full provider payloads, or equate a UI preview with a confirmed appointment.

## Activate after project setup

1. Create/select the clinic PostHog project and confirm US/EU cloud region. Configure the website with its public capture token (`VITE_POSTHOG_KEY`), ingestion host (`VITE_POSTHOG_HOST`), and explicit deployment switch (`VITE_POSTHOG_ENABLED=true`). Website consent is still required. Keep replay/autocapture disabled under the existing event contract.
2. Create a personal API key restricted to that project with Query Read (`query:read`). Put it in the backend's secret store as `POSTHOG_READ_KEY`; not a VITE variable or source file.
3. Set backend `POSTHOG_PROJECT_ID` to the numeric project ID, `POSTHOG_API_HOST=https://us.posthog.com` or `https://eu.posthog.com`, and `POSTHOG_GROWTH_ENABLED=true`. The app API host differs from the browser ingestion host (`us.i.posthog.com`/`eu.i.posthog.com`). This first implementation supports cloud hosts only; self-hosting requires a reviewed host configuration change.
4. Enable the existing Growth analytics module in staff Settings → Modules. Growth manager/admin roles may read; clinic staff/reception cannot. Disabling the module blocks the read endpoint, including direct requests. This staff module switch controls dashboard reads; disabling website collection is a separate deployment switch and visitor-consent decision.
5. With consent on a labelled test deployment, verify received events in PostHog, then compare a small aggregate query against its UI. Confirm there are no contact or clinical values in payloads before live collection.

## Endpoint and definitions

`GET /api/v1/admin/growth/website-activity` accepts validated start/end dates, reporting timezone and `traffic=production|demo`. Default range is the last 30 calendar dates including today. Maximum 91 days. UTC boundaries derive from that timezone. The UI currently uses its own last 30-day whole-website scope; appointment/clinic/date filters above do not silently apply to website activity. Current events contain no branch ID.

Only seven event names are queried: page_viewed, booking_intent_clicked, booking_flow_started, booking_preview_completed, booking_validation_failed, contact_intent_clicked and search_used. Response rows contain only an allowlisted event, fixed display label, event count and count of anonymous distinct IDs. Never sum per-event visitor counts to obtain total visitors. No person IDs or raw event properties are returned.

Production requires environment=production and is_demo=false. Demo activity requires is_demo=true. Current frontend envelope intentionally marks every event is_demo=true; consequently production results will remain empty even on a production hostname until the real booking/event contract changes. Do not simply flip this flag while booking still uses local OTP/preview completion.

These counts are activity summaries, not an ordered funnel. visitor_to_appointment_conversion remains null. A genuine conversion metric needs authoritative website booking integration plus a consent-safe correlated flow/confirmation contract and an ordered funnel denominator. Appointments and attendance remain the backend's source of truth. No server capture event or outbound patient data transmission is introduced in this phase.

Provider failures, denied keys and malformed responses show unavailable rather than invented zero counts. Only successful empty queries produce zeros. API host is allowlisted, redirects/proxies are disabled, timeout is bounded and errors omit keys/vendor bodies. Queries run only on authorized page load or manual refresh; no scheduler/export pipeline.

## Frontend lifecycle follow-up

In brave-mendel, saved consent now initializes on the first tracked event after reload. Revocation silences captures; re-grant clears persisted SDK opt-out without double initialization. Explicit VITE_POSTHOG_ENABLED is required in all environments. These changes are locally tested and separate from the backend PR. No live PostHog credentials or SDK transport were used during testing.

## Verification

Backend tests exercise missing configuration/no network, module/role gating, UTC calendar boundaries, separate demo/production clauses, redaction, invalid counts/schema and provider timeout handling. Frontend SDK is mocked for consent/reload/re-grant tests. Actual PostHog SQL execution and cloud reception remain pending credentials; mocked results are not provider verification.

Sources: [Query API](https://posthog.com/docs/api/queries), [official query documentation source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/api/queries.mdx), [personal API keys](https://posthog.com/docs/api/personal-api-keys).
