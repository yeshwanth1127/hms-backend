import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { assertProductionConfig } from '../production-config.mjs';
import { runPreflight } from '../preflight.mjs';
import { createInboundWorker, createWebhookServer } from '../server.mjs';

const image = fileURLToPath(new URL('../doctors/sample-a.png', import.meta.url));
const valid = {
  WA_ENV: 'production', WA_MODE: 'backend', WA_CLINIC_READY: 'true', WA_LIVE_NUMBER_CONFIRMED: 'true',
  BACKEND_URL: 'https://core.example.com', WA_WELCOME_IMAGE_PATH: image,
  WA_VERIFY_TOKEN: 'v'.repeat(32), WA_APP_SECRET: 's'.repeat(32),
  WA_ACCESS_TOKEN: 'a'.repeat(64), BACKEND_WHATSAPP_SERVICE_KEY: 'k'.repeat(32),
  WA_PHONE_NUMBER_ID: '123456', WA_GRAPH_VERSION: 'v25.0',
};

test('production startup refuses demo mode, plaintext backend, weak secrets and bundled demo artwork', () => {
  assert.doesNotThrow(() => assertProductionConfig(valid));
  for (const change of [
    { WA_MODE: 'demo' }, { WA_CLINIC_READY: 'false' }, { WA_LIVE_NUMBER_CONFIRMED: 'false' },
    { BACKEND_URL: 'http://core.example.com' }, { WA_APP_SECRET: 'dev-secret' },
    { WA_WELCOME_IMAGE_PATH: fileURLToPath(new URL('../welcome.png', import.meta.url)) },
  ]) assert.throws(() => assertProductionConfig({ ...valid, ...change }), /Unsafe production/);
});

test('preflight checks backend queue, approved catalogue media, and a live Meta number', async () => {
  const fetchImpl = async (url) => {
    const path = new URL(url).pathname;
    const result = path.endsWith('/inbound/ready') ? { ready: true }
      : path.endsWith('/catalogue') ? { branches: [{ id: 'branch-1', is_virtual: false }],
        departments: [{ slug: 'cardiology', guide_asset_id: 'guide-1' }] }
        : path.endsWith('/doctors') ? [{ photo_asset_id: 'photo-1', branches: [{ id: 'branch-1' }] }]
          : { display_phone_number: '+91 90000 00001' };
    return { ok: true, json: async () => result };
  };
  assert.deepEqual(await runPreflight(valid, fetchImpl), {
    branches: 1, specialties: 1, phoneEnding: '0001',
  });
  await assert.rejects(runPreflight(valid, async (url) => ({ ok: true,
    json: async () => new URL(url).hostname === 'graph.facebook.com'
      ? { display_phone_number: '+1 555-138-6019' }
      : fetchImpl(url).then((response) => response.json()),
  })), /test number/);
});

test('signed webhook persists an inbound message before acknowledging Meta', async (context) => {
  const queued = [];
  let wakeups = 0;
  const { server } = createWebhookServer({
    verifyToken: 'verify-me', appSecret: 'secret', phoneNumberId: '123456',
    sendText: async () => assert.fail('Webhook must not send inline in backend mode'),
    enqueueInbound: async (message) => queued.push(message),
    onEnqueued: () => { wakeups += 1; },
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const body = JSON.stringify({ object: 'whatsapp_business_account', entry: [{ changes: [{ value: {
    metadata: { phone_number_id: '123456' },
    messages: [{ id: 'wamid.prod-1', from: '919000000001', type: 'text', text: { body: 'hi' } }],
  } }] }] });
  const signed = `sha256=${createHmac('sha256', 'secret').update(body).digest('hex')}`;
  const url = `http://127.0.0.1:${server.address().port}/webhook`;
  assert.equal((await fetch(url, { method: 'POST', body, headers: { 'x-hub-signature-256': signed } })).status, 200);
  assert.equal(queued.length, 1);
  assert.equal(wakeups, 1);
  assert.equal(queued[0].id, 'wamid.prod-1');
});

test('worker marks outbound errors uncertain and retries only pre-send failures', async () => {
  const transitions = [];
  let jobs = [{ message_id: 'wamid.1', sender_id: '919000000001',
    claim_token: 'token', payload: { id: 'wamid.1', from: '919000000001', text: 'hi' } }];
  const backend = {
    claimInbound: async () => jobs.shift() ?? null,
    markInboundSending: async () => transitions.push('sending'),
    markInboundSent: async () => transitions.push('sent'),
    markInboundFailed: async () => transitions.push('failed'),
  };
  const engine = { handleResponse: async () => ({ kind: 'text', text: 'hello' }) };
  const log = { error: () => {} };
  const failSend = createInboundWorker({ backend, engine,
    sendText: async () => { throw new Error('ambiguous timeout'); }, log });
  assert.equal(await failSend(), true);
  assert.deepEqual(transitions, ['sending', 'failed']);
  transitions.length = 0;
  jobs = [{ message_id: 'wamid.2', sender_id: '919000000001',
    claim_token: 'token', payload: { id: 'wamid.2', from: '919000000001', text: 'hi' } }];
  const failPrepare = createInboundWorker({ backend,
    engine: { handleResponse: async () => { throw new Error('backend unavailable'); } },
    sendText: async () => assert.fail('No send after preparation failure'), log });
  assert.equal(await failPrepare(), true);
  assert.deepEqual(transitions, ['failed']);
  transitions.length = 0;
  jobs = [{ message_id: 'wamid.3', sender_id: '919000000001',
    claim_token: 'token', payload: { id: 'wamid.3', from: '919000000001', text: 'hi' } }];
  const succeed = createInboundWorker({ backend, engine, sendText: async () => {}, log });
  assert.equal(await succeed(), true);
  assert.deepEqual(transitions, ['sending', 'sent']);
});
