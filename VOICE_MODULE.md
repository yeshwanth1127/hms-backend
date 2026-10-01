# Voice module

The existing FastAPI backend owns Sarvam admission, booking rules, call history and administrator recording access. The existing `staff-web` shadcn build includes both `/staff/voice` and `/talk/`; there is no third application repository or service to run.

## What changed

- The optional `voice` module is **disabled by default**. A named clinic admin enables it under Settings > Modules. Staff can read call history; only administrators can request recordings or read recording-access logs. Growth managers have no Voice access. Scope is one clinic per deployment/database, matching the other optional modules.
- Web admission requires explicit recording consent, a notice version, an allowed origin and server configuration. Durable DB quotas default to 5 admissions/IP/hour, 200/clinic/UTC day and 10 concurrent sessions. A fixed DB gate serializes admission across workers. Limits include failed admissions after connection issuance, preventing unlimited paid session minting. Admission cookies are opaque, HttpOnly and single use; production adds Secure. An existing live cookie cannot start another call. The approved published agent version is pinned on the server.
- Appointment lookup requires **phone plus booking reference** and returns only visit details, without name, contact information, symptoms or reservation owner keys. This is possession of a reference, not OTP identity verification. Missing-reference callers must use reception rather than asking the agent to enumerate appointments. Unknown branch/specialty filters return no matches.
- Trusted lifecycle calls bind the admitted runtime session to the provider interaction ID. Slot holds and confirmations require `owner_key=voice:<runtime_session_id>` for an active tracked call. Booking and call correlation commit atomically. One booking per call is supported; repeat requests return the original booking. Replayed event IDs cannot double-count activity. Browser termination is an abandonment hint; only the trusted runtime reports completion.
- Expired sessions become abandoned when admission/history is requested. The browser closes its microphone/socket at the session limit. Configure and verify a matching provider-side maximum call duration; backend expiration cannot remotely close a socket in a modified/malicious browser. Disabling Voice blocks new calls and booking tools; authenticated end/event callbacks continue to finish historical records. Disabling does not remotely terminate a provider call already connected.

## Setup

1. Apply migrations with `alembic upgrade head`; build with `cd staff-web && npm ci --ignore-scripts && npm run build`. The Docker image runs these builds/migrations too. Use `HMS_VOICE_DATABASE_URL=<dedicated PostgreSQL test URL> python -m pytest tests/test_voice_module.py` for the persisted concurrency checks. The test fixture creates and removes its own unique schema; do not point it at production. Never use development credentials in production.
2. Configure `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_APP_ID`, `SARVAM_APP_VERSION` and `VOICE_SERVICE_API_KEY` in the backend. Compose forwards these fields. Publish an approved agent version; do not use a floating latest version. The browser never receives either secret.
3. Configure the trusted Sarvam HTTPS tools/hooks below. Keep `X-Service-Key` in provider-side tool configuration, never in agent variables, prompts or the browser bundle. Callback bodies must be mapped from the provider's runtime metadata, not caller-spoken IDs. Verify this mapping against a redacted provider event export.
4. Enable provider call recording and confirm the clinic's consent notice and provider retention settings. The website requires consent before initializing the SDK/microphone. For phone calls, collect consent in the telephony flow before recording; only report `recording_consent=true` after that disclosure/acceptance. Legacy/no-consent calls cannot be played through the workspace.
5. Verify the analytics response for a **completed synthetic call**. Set `SARVAM_RECORDING_URL_FIELD` to its exact dot-separated URL field (for example `recording.url` is only a test fixture, not a claim about Sarvam's schema). Set `VOICE_RECORDING_HOSTS` to exact trusted CDN/storage hosts from that verified response. Blank settings disable playback; unknown shapes fail closed. URLs must be HTTPS, public DNS, no credentials, no alternate ports and no redirects. Do not allow arbitrary customer-controlled storage hosts. Validate and review the provider's DNS/host control: host validation does not pin DNS across requests.
6. Enable Voice in staff module settings after the configuration above is checked. Set limits appropriate to the clinic's budget.

The public Sarvam docs [document the recording endpoint](https://docs.sarvam.ai/conversations/api/analytics/recordings), but show no usable recording response schema. Field/host configuration deliberately requires provider evidence. [Web SDK](https://docs.sarvam.ai/conversations/deploy/sdks/web) and [on-start/on-end hooks](https://docs.sarvam.ai/conversations/build/on-start-on-end-hooks) describe the relevant integration capabilities.

## Trusted runtime contract

All requests below require `X-Service-Key: <VOICE_SERVICE_API_KEY>` and JSON bodies. Paths retain the existing `/api/v1/integrations/voice` namespace.

**On start:** `POST /sessions`

```json
{
  "runtime_session_id": "<agent variable runtime_session_id>",
  "channel": "web_voice",
  "interaction_id": "<trusted provider interaction_id>",
  "agent_version": 7,
  "provider_reference": "<trusted reference_id that matches the issued connection>"
}
```

`runtime_session_id` is sent as both the SDK custom user identifier and an agent variable. `agent_version` must match the published server-approved version. `interaction_id` must be the provider's actual interaction identifier used by the recording analytics API. A web call must have a successfully issued local connection first, and its trusted provider reference must match that connection. The reference is required for web callbacks. The trusted start hook must succeed before booking tools run. A failed callback should stop booking and offer reception; do not pretend the call was tracked or a booking was made.

For an inbound phone call the trusted runtime may create the session with `channel=phone` and a unique runtime ID, actual interaction ID, pinned agent version and `recording_consent` boolean. Phone capacity uses the concurrent cap; web IP/day admission budgets do not rate-limit telephony. The telephony provider must enforce its own inbound/admission budget.

**Turn/tool event:** `POST /sessions/<runtime_session_id>/events`

```json
{
  "event_id": "<stable provider event ID>",
  "kind": "turn",
  "tool_name": "dialogue",
  "intent": "find_doctor",
  "outcome": "success"
}
```

Use a stable event ID on retries, never a newly generated ID for the same delivery. Tool events may include `appointment_id` only if the appointment belongs to that session. Booking confirmation already increments the tool count automatically; do not send a redundant confirmation tool event. No transcripts or spoken symptoms are saved to call history.

**On end:** `PATCH /sessions/<runtime_session_id>`

```json
{"event_id": "<stable provider end event ID>", "status": "completed"}
```

Other outcomes: `error`, `abandoned`. The same event is idempotent; conflicting final outcomes are rejected. Keep callbacks authenticated even when the module is disabled so existing records can finish. Retry transient callback failures with the same event ID. Provider hooks are deployment configuration; no live hook export was available in the local repositories.

**Booking:** use the existing doctors/availability/holds/appointment tools, with `owner_key=voice:<runtime_session_id>` on every hold/confirmation. Announce confirmation only after the appointment API succeeds. Lookup must now send both `patient_phone` and `confirmation_code`, and templates must use `appointments[*].starts_at`, `doctor_name`, `branch_name`, `consultation_type`, `status`, `confirmation_code` (the old nested reservation/patient fields were removed).

## Website routing

Use the existing website launcher's default `/talk/` URL. Proxy `/talk` and `/talk/`, `/staff/` and `/api/` to the backend; the talk entry loads its shared assets under `/staff/assets/`. The remaining website routes go to the website frontend. For Nginx, add these locations to the **existing clinic HTTPS server block**, keeping its existing certificate and frontend configuration:

```nginx
location = /talk { proxy_pass http://127.0.0.1:8000; }
location = /talk/ { proxy_pass http://127.0.0.1:8000; }
location ^~ /staff/ { proxy_pass http://127.0.0.1:8000; }
location ^~ /api/ { proxy_pass http://127.0.0.1:8000; }
```

For each proxy location, forward the original host and HTTPS scheme (`proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme;`) and configure Uvicorn to trust forwarding headers **only from the actual local reverse proxy**. Do not expose its port directly or trust arbitrary internet forwarding headers. Otherwise origin checks and per-IP quotas can see the proxy address instead of the patient. The production `STAFF_ORIGIN` must match the clinic HTTPS origin.

The old website PM2 `avocado-voice` job at `/var/www/avocado-web:5568` becomes unnecessary once routing is switched. Stop it only after validating the new proxy/build. For local development, point the website's public `VITE_VOICE_URL` to `http://127.0.0.1:8000/talk/`; configure `VOICE_WEBSITE_BOOKING_URL` to the website's local booking page. That public link is never used as a backend fetch target.

## Recording access and retention

Administrators explicitly request playback using CSRF-protected `POST /api/v1/staff/voice/sessions/<local_session_id>/recording`. The server resolves the provider interaction, downloads bounded audio (max 50 MB), and returns bytes with no-store caching. Provider credentials are sent only to Sarvam's fixed API origin, never to the recording host. Signed provider URLs never reach the UI/history/log. Temporary browser blobs are revoked when the review dialog closes. Each authorized request records the named admin, call, time and outcome; this logs delivery, not proof the audio was listened to.

Workspace playback expires after `VOICE_RECORDING_ACCESS_DAYS` (default 30, maximum 90) from first trusted session binding. No audio files are persisted by this backend. **This deadline does not delete Sarvam's recording**, and audio already delivered to an administrator cannot be revoked. Configure provider retention/deletion separately and verify it before relying on a retention promise. Pending callbacks, missing consent, expired access and unconfigured playback all have explicit UI/API states.

## Dependency and verification notes

The pinned SDK is `sarvam-conv-ai-sdk@0.0.42` through its official `/browser` entry. It transitively installs Node `speaker`, which has unresolved high advisory [GHSA-w5fc-gj3h-26rx](https://github.com/advisories/GHSA-w5fc-gj3h-26rx). Install scripts are disabled; the production Python stage contains only built browser assets, not Node packages. The browser build excludes Node/speaker code and strips SDK console output (including signed URLs/transcripts). The npm audit warning remains; do not import/run the Node SDK entry. Recheck the vendor SDK when a patched release is available.

Local tests cover admission/expiry/quotas, version restrictions, authenticated tracking, duplicate events, atomic booking linkage, lookup privacy, module/role/CSRF restrictions, recording expiry, audit outcomes and provider URL validation. These tests use synthetic data and mock provider responses. They do not prove a live Sarvam call, real recording playback, phone consent, deployed routing, provider deletion or clinical acceptance. See the verification result below for actual checks completed on this branch.

## Verification on 2026-10-01

- **PASS:** backend suite, 78 passed / 2 conditional PostgreSQL tests skipped in the SQLite run. The new Voice concurrency test was run separately on PostgreSQL; the unchanged WhatsApp outreach concurrency test was not run.
- **PASS:** all 20 Voice tests against native PostgreSQL 17, with independent connections, isolated test schemas, real quota serialization, capacity reclamation and single-use mint races. Provider responses remained mocked.
- **PASS:** Alembic upgrade from an empty PostgreSQL database through `0010_voice_module`; SQLite upgrade tests from both existing migration branches and preservation of legacy clinic data.
- **PASS:** staff/talk TypeScript and production build, including build-time rejection of Node audio dependencies; website TypeScript/production build and PM2 config syntax.
- **PASS:** local browser consent gate, admin recording player (one-second synthetic WAV, loaded duration/ready state) and matching named-admin delivery audit. No real call or microphone capture was performed.
- **WARN:** lint exits successfully with React/Fast Refresh warnings. npm audit reports the unresolved SDK/speaker advisory described above.
- **UNVERIFIABLE:** Docker image/Compose execution (daemon unavailable), live Sarvam hooks/version/recording schema and download host, provider call-duration enforcement and deletion/retention, real microphone/telephony behavior, and deployed HTTPS routing. Voice remains opt-in and playback fails closed until recording configuration is supplied.
