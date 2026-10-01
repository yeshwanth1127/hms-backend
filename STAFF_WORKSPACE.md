# Staff workspace deployment

The backend now serves a shared shadcn React interface at `/staff/whatsapp`,
`/staff/appointments`, `/staff/doctors`, `/staff/schedules` and `/staff/settings`.
Optional Google Business and growth analytics use the same named account session.
`/whatsapp-assets` and `/growth` redirect into this workspace.

## Local development

```sh
uv sync --locked --extra dev
uv run --locked alembic upgrade head
npm --prefix staff-web ci
npm --prefix staff-web run build
uv run --locked python -m app.staff_cli create --username clinic.admin --name "Clinic administrator"
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The CLI prompts for the password twice without echoing it. It must have 12–128
characters. There are **no default accounts**. Open `http://127.0.0.1:8000/staff/whatsapp`
and sign in with that username and password. Administrator users can add staff
and growth-manager accounts in Settings. Use separate accounts for each person.

The development Compose profile builds the UI inside the API image. After it
starts, provision an administrator with:

```sh
docker compose exec api python -m app.staff_cli create --username clinic.admin --name "Clinic administrator"
```

For frontend hot reload, run `npm --prefix staff-web run dev`; the Vite proxy
expects a backend on port 8012. Serve the built interface from the API for the
same-origin browser acceptance checks. Developer UI hostnames/ports must match
the configured `STAFF_ORIGIN` for state-changing requests. Cookies share a host
across ports; do not use two unrelated preview databases on the same hostname.

## Production

- Run migrations before account provisioning.
- Use PostgreSQL and persistent media, the existing strong service secrets and
  production ClamAV socket. Existing WhatsApp production gates still apply.
- Set `APP_ENV=production` and `STAFF_ORIGIN=https://staff.your-clinic.example` to
  the actual origin. The reverse proxy must preserve host and provide HTTPS.
- Serve UI and API on the same origin; do not put the staff app on a public asset
  CDN that forwards cookies or provider/service credentials.
- `Dockerfile` compiles staff-web in a Node stage and copies built assets and UX
  books into the API image. No separate frontend service is required.
- Apply a reverse-proxy login rate limit in addition to the persisted backend
  account/IP limiter; configure trusted proxy handling explicitly. The backend
  does not trust arbitrary X-Forwarded-For headers.
- Sessions are opaque, database-backed, eight-hour absolute/30-minute idle,
  HttpOnly, SameSite Strict and Secure in production. Mutations require CSRF and
  matching origin. Passwords use Argon2id.
- Back up the database and media. Never commit credentials or preview-account
  files. No MFA, SSO or multi-tenant isolation is claimed by this release.

## Recovery and revocation

```sh
uv run --locked python -m app.staff_cli reset --username clinic.admin
uv run --locked python -m app.staff_cli disable --username former.staff
```

Reset/disable revokes existing sessions. Disabling is reversible through an
operator database change; the CLI does not delete accounts or audit records.
Self-service password change in Settings also revokes every session.

## Roles and module configuration

| Role | Permission |
| --- | --- |
| admin | Core clinic and enabled optional modules; staff/module management |
| staff | Core clinic and enabled WhatsApp |
| growth_manager | Enabled Google Business and growth analytics only |

Module state is per clinic deployment, not per tenant in a shared database.
WhatsApp defaults on for compatibility when no record exists; the two growth
modules default off. `GET /api/v1/staff/modules` reports availability and account
access. Only administrators may `PUT /api/v1/staff/modules/{key}`. Disabling a
module retains saved data. Backend endpoints and worker claims/sending recheck
WhatsApp enablement. Signed intake and provider outcomes still persist while off.
Patient outreach switches are independent and remain off by default; a module
switch alone does not enable campaigns or clinical follow-ups.

## Shared authentication contract

- `POST /api/v1/staff/login` — `{username,password}` -> `{user,csrf_token,environment}`
  and the HttpOnly session cookie.
- `GET /api/v1/staff/session` — refresh workspace identity/CSRF without changing
  the session's stable CSRF token across tabs.
- `POST /api/v1/staff/logout` — CSRF required; revokes the session.
- `POST /api/v1/staff/password` — `{current_password,new_password}`, CSRF required;
  revokes all sessions and signs out.
- `GET /api/v1/staff/users`, `POST /api/v1/staff/users` — administrator-only.
- `GET /api/v1/staff/design-guide` — authenticated UX decision book.

Legacy `X-Admin-Key` callers remain supported for server integrations and tests;
the key is never used by staff-web. Named sessions supply appointment actor IDs
and override any caller-supplied reception/campaign actor labels. Growth APIs
never accept the shared admin key as a staff identity.

## Verification boundaries

Tests exercise real password verification/cookie authentication, roles, CSRF,
expiry, revocation, module lifecycle and backend booking operations. Browser
checks use an isolated local database with illustrative catalogue/templates.
Actual Meta delivery, hospital content approval, provider billing and clinical
acceptance are separate production gates. See `STAFF_WORKSPACE_UX_DECISION_BOOK.md`,
`GROWTH_UX_DECISION_BOOK.md` and `WHATSAPP_OUTREACH.md`.
