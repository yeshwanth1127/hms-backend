# HMS WhatsApp service

The WhatsApp runtime now lives in this backend repository. It needs Node 22 or newer and has no npm dependencies. FastAPI owns clinic data, uploads, conversations, appointments, support cases and the durable delivery queue. This service verifies Meta signatures, sends interactive menus/media and processes that queue. No website checkout is needed.

## Local backend and phone test

From the repository root:

```sh
cp .env.example .env
cp whatsapp-bot/.env.example whatsapp-bot/.env
```

Fill the bot's Meta values privately. Use the same service key in both files. Keep `WA_CLINIC_READY=false` while using the seeded catalogue and Meta test number.

```sh
docker compose --profile whatsapp up --build
```

This development profile runs the API, PostgreSQL, Redis and one bot. The bot waits for the API migration and readiness check. Ports are bound to localhost: API `8000`, webhook `8787`. Open `/whatsapp-assets` on the API for staff PDF/photo uploads. Expose **only** port 8787 through an HTTPS tunnel for the local phone test; register `https://YOUR-TUNNEL/webhook` with Meta and subscribe to messages. Test recipients must be verified in Meta. Tokens may expire; changing `.env` requires restarting/recreating the bot.

Without Docker, start the API using the root README, then:

```sh
npm --prefix whatsapp-bot start
```

`BACKEND_URL` in the example is `http://127.0.0.1:8000`; change it if the API uses another port. The Compose profile supplies its internal API URL and shared key automatically.

## Local tests

```sh
uv sync --extra dev
uv run pytest
npm --prefix whatsapp-bot test
npm --prefix whatsapp-bot run test:integration
```

The integration test starts an isolated FastAPI process with a temporary SQLite database and generated test keys. It exercises signed webhook enqueueing, duplicate handling, the real Node client/worker, booking, restart recovery, visit management, media and cases. Meta sending is captured locally; no WhatsApp messages are sent. CI also builds the containers and repeats the HTTP integration against disposable PostgreSQL. `HMS_TEST_DATABASE_URL` is an optional test override; never point it at clinic data. Phone acceptance remains a separate check.

`npm --prefix whatsapp-bot run simulate` runs the fictional, in-memory demo without Meta or FastAPI. Bundled portraits, welcome image and `demo-guides/` belong to that demo. Backend mode reads the uploaded clinic PDFs/photos from FastAPI; it never uses demo doctor records.

## Deploy

Build the standalone image from the repository root:

```sh
docker build -t hms-whatsapp-bot -f whatsapp-bot/Dockerfile whatsapp-bot
```

The image defaults to production, runs as the Node user and executes preflight before serving. Deploy one replica behind HTTPS, alongside the private HTTPS API, PostgreSQL and ClamAV. Mount an approved welcome image read-only, inject production environment values and allow at least 45 seconds for shutdown. The development Compose profile must not be used for clinic production.

See [production deployment](./PRODUCTION_DEPLOYMENT.md) and [API contracts](../WHATSAPP_CONTRACT.md). Production guards reject test configuration and fail closed on upload scanning. Ambiguous outbound sends are quarantined for staff review. Reminder sends require consent and an approved template. Payments remain disabled.
