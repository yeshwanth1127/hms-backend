import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline';
import { createDemoEngine } from './engine.mjs';
import { createBackendClient } from './backend-client.mjs';
import { createLiveEngine } from './live-engine.mjs';
import { createMetaSender, incomingMessages, verifyMetaSignature } from './meta.mjs';
import { assertProductionConfig } from './production-config.mjs';

const MAX_WEBHOOK_BYTES = 1024 * 1024;

async function readBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_WEBHOOK_BYTES) throw new Error('Webhook body too large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function respond(response, status, body) {
  response.writeHead(status, { 'content-type': 'text/plain; charset=utf-8' });
  response.end(body);
}

export function createWebhookServer({ verifyToken, appSecret, phoneNumberId, sendText,
  engine = createDemoEngine(), enqueueInbound, onEnqueued, checkReady }) {
  if (!verifyToken || !appSecret || !phoneNumberId || typeof sendText !== 'function') {
    throw new Error('Webhook server requires verification token, app secret, phone-number ID, and sender');
  }
  const sentInboundIds = new Set();
  const inFlightById = new Map();
  const inFlightBySender = new Map();
  let lastSender = null;

  async function deliver(message) {
    if (sentInboundIds.has(message.id)) return;
    if (inFlightById.has(message.id)) return inFlightById.get(message.id);
    const previous = inFlightBySender.get(message.from);
    const pending = (async () => {
      if (previous) await previous.catch(() => {});
      if (sentInboundIds.has(message.id)) return;
      const reply = await engine.handleResponse(message);
      if (typeof sendText.sendResponse === 'function') {
        await sendText.sendResponse(message.from, reply, message.id);
      } else {
        await sendText(message.from, reply.text);
      }
      sentInboundIds.add(message.id);
      if (sentInboundIds.size > 2000) sentInboundIds.delete(sentInboundIds.values().next().value);
      lastSender = message.from;
    })();
    inFlightById.set(message.id, pending);
    inFlightBySender.set(message.from, pending);
    try {
      await pending;
    } finally {
      inFlightById.delete(message.id);
      if (inFlightBySender.get(message.from) === pending) inFlightBySender.delete(message.from);
    }
  }

  const server = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://localhost');
    if (request.method === 'GET' && url.pathname === '/health') return respond(response, 200, 'ok');
    if (request.method === 'GET' && url.pathname === '/health/ready') {
      try {
        if (checkReady) await checkReady();
        return respond(response, 200, 'ready');
      } catch {
        return respond(response, 503, 'not ready');
      }
    }
    if (request.method === 'GET' && url.pathname === '/webhook') {
      if (url.searchParams.get('hub.mode') === 'subscribe'
        && url.searchParams.get('hub.verify_token') === verifyToken
        && url.searchParams.has('hub.challenge')) {
        return respond(response, 200, url.searchParams.get('hub.challenge'));
      }
      return respond(response, 403, 'forbidden');
    }
    if (request.method !== 'POST' || url.pathname !== '/webhook') return respond(response, 404, 'not found');

    let rawBody;
    try {
      rawBody = await readBody(request);
    } catch {
      return respond(response, 413, 'body too large');
    }
    if (!verifyMetaSignature(rawBody, request.headers['x-hub-signature-256'], appSecret)) {
      return respond(response, 403, 'forbidden');
    }

    let payload;
    try {
      payload = JSON.parse(rawBody.toString('utf8'));
    } catch {
      return respond(response, 400, 'invalid json');
    }
    const messages = incomingMessages(payload, phoneNumberId);
    try {
      for (const message of messages) {
        if (enqueueInbound) {
          await enqueueInbound(message);
          onEnqueued?.();
        } else await deliver(message);
      }
      return respond(response, 200, 'ok');
    } catch (error) {
      console.error(`Webhook processing failed: ${error.message}`);
      return respond(response, 500, 'send failed');
    }
  });
  server.headersTimeout = 10000;
  server.requestTimeout = 15000;
  server.keepAliveTimeout = 5000;
  server.maxHeadersCount = 32;
  server.maxRequestsPerSocket = 100;

  return {
    server,
    async followupLastSender() {
      if (!lastSender) return { sent: false, reason: 'No test sender yet' };
      if (typeof engine.followup !== 'function') return { sent: false, reason: 'Manual follow-up is only available in demo mode' };
      const body = engine.followup(lastSender);
      if (!body) return { sent: false, reason: 'No open 24-hour test conversation' };
      await sendText(lastSender, body);
      return { sent: true };
    },
  };
}

export function createInboundWorker({ backend, engine, sendText, log = console }) {
  if (!backend?.claimInbound || !backend?.markInboundSending || !backend?.markInboundSent || !backend?.markInboundFailed) {
    throw new Error('Inbound worker requires a durable backend queue');
  }
  return async function processOne() {
    const job = await backend.claimInbound();
    if (!job) return false;
    const { message_id: id, claim_token: token, payload } = job;
    let sending = false;
    try {
      const reply = await engine.handleResponse(payload);
      await backend.markInboundSending(id, token);
      sending = true;
      if (typeof sendText.sendResponse === 'function') await sendText.sendResponse(job.sender_id, reply, id);
      else await sendText(job.sender_id, reply.text);
      await backend.markInboundSent(id, token);
    } catch (error) {
      // Once an outbound request starts, a timeout or crash cannot prove whether
      // Meta accepted it. Mark uncertain and require a human to inspect it.
      try { await backend.markInboundFailed(id, token, error.message); }
      catch (reportError) { log.error(`Inbound status update failed: ${reportError.message}`); }
      log.error(`Inbound ${sending ? 'delivery' : 'processing'} failed for ${id}: ${error.message}`);
    }
    return true;
  };
}

function startFromEnvironment() {
  assertProductionConfig(process.env);
  const config = {
    verifyToken: process.env.WA_VERIFY_TOKEN,
    appSecret: process.env.WA_APP_SECRET,
    phoneNumberId: process.env.WA_PHONE_NUMBER_ID,
    accessToken: process.env.WA_ACCESS_TOKEN,
    graphVersion: process.env.WA_GRAPH_VERSION,
    welcomeImagePath: process.env.WA_WELCOME_IMAGE_PATH || undefined,
  };
  const sendText = createMetaSender(config);
  const mode = process.env.WA_MODE ?? 'demo';
  if (!['demo', 'backend'].includes(mode)) throw new Error('WA_MODE must be demo or backend');
  const backend = mode === 'backend' ? createBackendClient({
    baseUrl: process.env.BACKEND_URL,
    serviceKey: process.env.BACKEND_WHATSAPP_SERVICE_KEY,
  }) : null;
  const engine = backend ? createLiveEngine({
    backend, downloadMedia: sendText.downloadMedia,
    welcomeImagePath: process.env.WA_WELCOME_IMAGE_PATH || undefined,
    clinicReady: process.env.WA_CLINIC_READY === 'true',
    requireReference: process.env.WA_ENV === 'production' || process.env.NODE_ENV === 'production',
  }) : createDemoEngine();
  let wakeWorker = () => {};
  const app = createWebhookServer({ ...config, sendText, engine,
    enqueueInbound: backend?.enqueueInbound,
    onEnqueued: () => wakeWorker(),
    checkReady: backend ? backend.inboundReady : undefined,
  });
  const port = Number(process.env.WA_LOCAL_PORT ?? 8787);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('WA_LOCAL_PORT must be a valid port');
  const host = process.env.WA_BIND_HOST || '127.0.0.1';
  const timers = [];
  const active = new Set();
  let stopping = false;
  const runTracked = (task) => {
    const pending = task();
    active.add(pending);
    pending.finally(() => active.delete(pending));
  };
  app.server.listen(port, host, () => {
    console.log(`WhatsApp ${mode} webhook listening on http://${host}:${port}/webhook`);
    if (mode === 'demo') console.log('Type “followup” here to send one demo check-in to the most recent tester.');
  });
  if (backend) {
    const processOne = createInboundWorker({ backend, engine, sendText });
    let busy = false;
    let retryAfter = 0;
    let failures = 0;
    let lastErrorLog = 0;
    const poll = async () => {
      if (busy || stopping || Date.now() < retryAfter) return;
      busy = true;
      try {
        while (!stopping && await processOne()) { /* drain the durable inbox */ }
        failures = 0;
      } catch (error) {
        failures += 1;
        retryAfter = Date.now() + Math.min(30000, 1000 * 2 ** Math.min(failures, 5));
        if (Date.now() - lastErrorLog > 30000) {
          console.error(`Inbound queue unavailable: ${error.message}`);
          lastErrorLog = Date.now();
        }
      } finally {
        busy = false;
      }
    };
    wakeWorker = () => runTracked(poll);
    timers.push(setInterval(wakeWorker, 10000));
    wakeWorker();
  }
  if (backend && process.env.WA_CLINIC_READY === 'true' && process.env.WA_REMINDER_TEMPLATE_NAME) {
    const poll = async () => {
      if (stopping) return;
      try {
        const jobs = await backend.dueReminders();
        for (const job of jobs) {
          let sending = false;
          try {
            const formatted = new Intl.DateTimeFormat('en-IN', {
              timeZone: job.timezone, dateStyle: 'medium', timeStyle: 'short',
            }).format(new Date(job.starts_at));
            sending = true;
            await sendText.sendTemplate(job.sender_id, process.env.WA_REMINDER_TEMPLATE_NAME,
              process.env.WA_REMINDER_TEMPLATE_LANGUAGE ?? 'en',
              [job.confirmation_code, job.doctor_name, formatted]);
            await backend.completeReminder(job.id, { status: 'sent' });
          } catch (error) {
            try {
              await backend.completeReminder(job.id, {
                status: sending ? 'uncertain' : 'failed', error: error.message.slice(0, 240),
              });
            } catch (reportError) {
              console.error(`Reminder status update failed: ${reportError.message}`);
            }
          }
        }
      } catch (error) {
        console.error(`Reminder poll failed: ${error.message}`);
      }
    };
    timers.push(setInterval(() => runTracked(poll), 60000));
    runTracked(poll);
  }
  const terminal = mode === 'demo' ? createInterface({ input: process.stdin, output: process.stdout }) : null;
  terminal?.on('line', async (line) => {
    if (line.trim().toLowerCase() !== 'followup') return;
    try {
      const result = await app.followupLastSender();
      console.log(result.sent ? 'Demo follow-up sent.' : result.reason);
    } catch (error) {
      console.error(`Demo follow-up failed: ${error.message}`);
    }
  });
  const shutdown = async () => {
    if (stopping) return;
    stopping = true;
    timers.forEach(clearInterval);
    terminal?.close();
    const closed = new Promise((resolve) => app.server.close(resolve));
    let deadline;
    const settled = await Promise.race([
      Promise.allSettled([closed, ...active]).then(() => true),
      new Promise((resolve) => { deadline = setTimeout(() => resolve(false), 45000); }),
    ]);
    clearTimeout(deadline);
    if (!settled) process.exit(1);
  };
  process.once('SIGTERM', shutdown);
  process.once('SIGINT', shutdown);
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) startFromEnvironment();
