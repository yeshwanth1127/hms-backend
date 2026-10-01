# Clinic staff workspace

React, TypeScript and actual shadcn/ui components (Base UI Nova), served by the
FastAPI backend at `/staff/`. DM Sans is bundled locally.

```sh
npm ci
npm run build
```

The production build writes to `../app/staff_static`; Docker builds and packages
it automatically. `npm run dev` proxies API requests to port 8012. The browser
uses the backend's HttpOnly staff session and CSRF contract. No service or Meta
credentials belong in frontend environment variables.

See `../STAFF_WORKSPACE.md` for account provisioning, migrations and deployment,
and `../STAFF_WORKSPACE_UX_DECISION_BOOK.md` for the design decisions. The latter
also appears in the signed-in workspace's Design & UX guide.
