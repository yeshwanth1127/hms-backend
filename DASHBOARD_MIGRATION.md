# One clinic workspace

`/admin` now opens `/staff/appointments`. The website's former dashboard and its administrator-key sign-in have been removed. All dashboard pages use the backend's staff session, CSRF checks, named roles and shadcn components with Lucide icons.

## Feature audit

| Former dashboard feature | Current workspace |
| --- | --- |
| Overview appointment total and upcoming count | Overview |
| Confirmed share (formerly labelled conversion), confirmed count | Overview, labelled retained confirmations; it is not visitor conversion |
| Active doctors and schedule counts | Overview |
| Pending notifications and live slot holds | Overview and Operations |
| Voice booking and session counts | Overview and Voice |
| Daily booking history, status distribution, recent appointment details | Overview; shadcn charts plus readable count tables |
| Date in IST, Today / All dates | Appointments / nurse desk |
| Search patient, phone, doctor or reference | Appointments / nurse desk; server search |
| Doctor, branch and status filters | Appointments / nurse desk |
| 50-row pagination, loading/error states, refresh timestamp | Appointments / nurse desk |
| Patient panel: phone, email, reason, reference, time, doctor, branch, visit type, channel | Appointments / nurse desk |
| Check in, complete, cancel, no-show | Appointments / nurse desk; cancellation/no-show requires a reason; future completion/no-show is disabled |
| Fee editing, activation, virtual consultations, specialties | Doctors |
| Doctor filter, recurring weekday, effective dates, clinic, visit type, hours, duration, add/remove rule | Schedules |
| Branch directory and active states | Hospital catalogue |
| Departments and doctor coverage | Hospital catalogue |
| Event type, linked record, time and status in notification outbox | Operations; processed events are not labelled patient delivery confirmations |
| API readiness | Operations; a real database readiness request replaces the hard-coded Healthy label |
| Call history, outcomes, channel, last intent, turns, tools, linked booking | Voice; list and call detail |
| Completed calls and aggregate tool activity | Voice, over its labelled 30-day reporting window |
| Crash recovery / reload | Shared workspace error boundary and API error/retry states |
| Sign-in, sign-out, mobile navigation | Shared staff workspace; named accounts replace browser-stored administrator keys |

Existing WhatsApp, Google Business, Growth analytics, media/content, reception, campaigns, follow-ups, delivery history, staff accounts and module settings remain in the same workspace. Google capabilities that have not been implemented remain explicitly marked as planning/manual setup; demo mode does not pretend Google OAuth or publication is connected.

## Local demo

Build the workspace once with `npm ci --prefix staff-web && npm run build --prefix staff-web`. Start `python scripts/demo.py` with the backend environment. It binds to `127.0.0.1:8014` and exclusively uses `.local/clinic-demo/clinic.db` and `.local/clinic-demo/uploads`.

In the website's gitignored `.env.local`, set:

```
HMS_BACKEND_PROXY=http://127.0.0.1:8014
VITE_VOICE_URL=/talk/
```

Run the website normally and open `http://localhost:5173/admin`. Use `demo.admin` / `DemoClinic2026!`. Reception (`demo.reception`) and growth (`demo.growth`) have the same disposable local password and real role restrictions.

All four optional modules start enabled. The fixture provides 84 fictional appointments, 18 calls, 12 contacts/conversations, reception cases, campaigns, delivery examples, follow-ups, 10 doctors, 5 clinics, 9 specialties, schedules, sample media, Google booking-link examples and 30 days of synthetic website activity. All appointments are explicitly `is_demo=true`; production growth filters exclude them.

**Clear demo data** removes every operational/catalogue table, including recordings access logs and analytics fixture rows, and the demo media files. Accounts, active sessions and module switches remain so the owner can use **Reload demo data**. Reload replaces samples rather than duplicating them. Clearing persists through a server restart; the runner seeds automatically only once during initialization.

Controls fail closed outside `APP_ENV=demo`, without `DEMO_MODE=true`, against a different database/media directory, or without the dedicated workspace marker. Backend provider requests, new voice admission, voice-runtime integration and WhatsApp-worker integration are blocked in demo mode. Audio playback uses a synthetic sample tone through the real permission/audit endpoint. No live provider connection is implied.

To return to normal local backend work, change `HMS_BACKEND_PROXY` to the normal backend address and restart Vite. Demo records never enter that database. Do not use the demo runner, sample accounts or fixture configuration for deployment.

## Validation

Both website and staff production builds passed. The backend suite passed 80 tests; two PostgreSQL-specific tests were skipped without a running PostgreSQL test database. The website suite passed 45 tests. The demo tests additionally check staff roles, CSRF, database isolation, blocked external transport, complete clear/reload, duplicate prevention and retained module settings.

Browser checks against the real local API covered the legacy redirect, named sign-in, nurse filters/pagination and patient details, schedule creation for virtual care, call recording playback with its access audit, WhatsApp pages, growth reports, catalogue, readiness/outbox and staff settings. Clearing through the UI removed all operational rows and sample files; restarting kept the clinic empty, and explicit reload restored the fixtures.

Sarvam calling, provider callbacks, real recording URLs and production deployment still need provider configuration and live verification. Sample audio and synthetic delivery receipts are demo evidence only.
