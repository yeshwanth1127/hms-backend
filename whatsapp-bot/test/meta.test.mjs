import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createDemoEngine } from '../engine.mjs';
import { createMetaSender, incomingMessages, verifyMetaSignature } from '../meta.mjs';
import { createWebhookServer } from '../server.mjs';

function signature(body, secret) {
  return `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`;
}

const payload = {
  object: 'whatsapp_business_account',
  entry: [{ changes: [{ value: {
    metadata: { phone_number_id: '123456' },
    messages: [{ id: 'wamid.01', from: '919000000001', type: 'text', text: { body: 'hi' } }],
  } }] }],
};

test('validates the raw Meta signature and parses only the configured number', () => {
  const body = Buffer.from(JSON.stringify(payload));
  assert.equal(verifyMetaSignature(body, signature(body, 'secret'), 'secret'), true);
  assert.equal(verifyMetaSignature(body, signature(body, 'wrong'), 'secret'), false);
  assert.equal(verifyMetaSignature(body, 'sha256=not-hex', 'secret'), false);
  assert.equal(verifyMetaSignature(body, ['sha256=invalid'], 'secret'), false);
  assert.deepEqual(incomingMessages(payload, '123456'), [
    { id: 'wamid.01', from: '919000000001', type: 'text', text: 'hi' },
  ]);
  assert.deepEqual(incomingMessages(payload, '999999'), []);
});

test('maps interactive choice IDs to stable demo actions', () => {
  const messages = [
    { id: 'button-1', from: '919000000001', type: 'interactive',
      interactive: { type: 'button_reply', button_reply: { id: 'menu.more', title: 'More options' } } },
    { id: 'list-001', from: '919000000001', type: 'interactive',
      interactive: { type: 'list_reply', list_reply: { id: 'menu.change', title: 'Change request' } } },
    { id: 'template-1', from: '919000000001', type: 'button',
      button: { payload: 'menu.book', text: 'Book a visit' } },
    { id: 'doctor-1', from: '919000000001', type: 'interactive',
      interactive: { type: 'list_reply', list_reply: { id: 'doctor.2', title: 'Sample Clinician B' } } },
    { id: 'specialty-1', from: '919000000001', type: 'interactive',
      interactive: { type: 'list_reply', list_reply: { id: 'specialty.skin-care', title: 'Skin care' } } },
    { id: 'booking-1', from: '919000000001', type: 'interactive',
      interactive: { type: 'list_reply', list_reply: { id: 'booking.TEST-0001', title: 'TEST-0001' } } },
    { id: 'receipt-1', from: '919000000001', type: 'interactive',
      interactive: { type: 'button_reply', button_reply: { id: 'receipt.visits', title: 'My visits' } } },
  ];
  const result = incomingMessages({ ...payload, entry: [{ changes: [{ value: {
    metadata: { phone_number_id: '123456' }, messages,
  } }] }] }, '123456');
  assert.deepEqual(result.map(({ text }) => text),
    ['more', 'change', 'book', 'doctor:2', 'specialty:skin-care', 'booking:TEST-0001', 'my appointments']);
});

test('uploads and sends a specialty PDF before its clinician list, then a clinician image', async () => {
  const requests = [];
  let nextMediaId = 0;
  const sender = createMetaSender({
    accessToken: 'test-token', phoneNumberId: '123456', graphVersion: 'v24.0',
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => url.endsWith('/media')
        ? { id: `media-${++nextMediaId}` } : { messages: [{ id: 'wamid.out' }] } };
    },
  });
  const engine = createDemoEngine();
  const from = '919000000001';
  engine.handleResponse({ id: 'in-1', from, text: 'book' });
  await sender.sendResponse(from, engine.handleResponse({ id: 'in-2', from, text: 'specialty:general-care' }));
  assert.equal(requests[0].options.body.get('file').type, 'application/pdf');
  assert.equal(requests[0].options.body.get('file').name, 'avocado-demo-general-care.pdf');
  assert.deepEqual(requests.slice(1, 3).map(({ options }) => JSON.parse(options.body).type),
    ['document', 'interactive']);
  assert.equal(JSON.parse(requests[1].options.body).document.id, 'media-1');
  assert.equal(JSON.parse(requests[2].options.body).interactive.type, 'list');

  await sender.sendResponse(from, engine.handleResponse({ id: 'in-3', from, text: 'doctor:1' }));
  assert.equal(requests[3].options.body.get('file').type, 'image/png');
  assert.deepEqual(requests.slice(4, 6).map(({ options }) => JSON.parse(options.body).type),
    ['image', 'interactive']);
  assert.equal(JSON.parse(requests[4].options.body).image.id, 'media-2');
});

test('a retried specialty reply resumes after the PDF if sending the list failed', async () => {
  const sentTypes = [];
  let failedList = false;
  const sender = createMetaSender({
    accessToken: 'test-token', phoneNumberId: '123456', graphVersion: 'v24.0',
    fetchImpl: async (url, options) => {
      if (url.endsWith('/media')) return { ok: true, json: async () => ({ id: 'pdf-media' }) };
      const body = JSON.parse(options.body);
      sentTypes.push(body.type);
      if (body.interactive?.type === 'list' && !failedList) {
        failedList = true;
        return { ok: false, status: 503 };
      }
      return { ok: true, json: async () => ({ messages: [{ id: 'wamid.out' }] }) };
    },
  });
  const engine = createDemoEngine();
  const from = '919000000001';
  engine.handleResponse({ id: 'in-1', from, text: 'book' });
  const reply = engine.handleResponse({ id: 'in-2', from, text: 'specialty:general-care' });
  await assert.rejects(sender.sendResponse(from, reply, 'in-2'), /HTTP 503/);
  await sender.sendResponse(from, reply, 'in-2');
  assert.deepEqual(sentTypes, ['document', 'interactive', 'interactive']);
});

test('sends through the official Graph API request shape', async () => {
  let request;
  const sender = createMetaSender({
    accessToken: 'test-token', phoneNumberId: '123456', graphVersion: 'v24.0',
    fetchImpl: async (url, options) => {
      request = { url, options };
      return { ok: true, json: async () => ({ messages: [{ id: 'wamid.out' }] }) };
    },
  });
  await sender('919000000001', 'TEST DEMO');
  assert.equal(request.url, 'https://graph.facebook.com/v24.0/123456/messages');
  assert.equal(JSON.parse(request.options.body).text.body, 'TEST DEMO');
});

test('uploads the bundled welcome image and sends button and list messages', async () => {
  const requests = [];
  const sender = createMetaSender({
    accessToken: 'test-token', phoneNumberId: '123456', graphVersion: 'v24.0',
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => url.endsWith('/media')
        ? { id: 'media-123' } : { messages: [{ id: 'wamid.out' }] } };
    },
  });
  const engine = createDemoEngine();
  const from = '919000000001';
  await sender.sendResponse(from, engine.handleResponse({ id: 'in-1', from, text: 'hi' }));
  assert.equal(requests[0].url, 'https://graph.facebook.com/v24.0/123456/media');
  assert.equal(requests[0].options.body.get('messaging_product'), 'whatsapp');
  assert.equal(requests[0].options.body.get('file').type, 'image/png');
  const welcome = JSON.parse(requests[1].options.body);
  assert.equal(welcome.interactive.header.image.id, 'media-123');
  assert.deepEqual(welcome.interactive.action.buttons.map((button) => button.reply.id),
    ['menu.book', 'menu.doctors', 'menu.more']);

  await sender.sendResponse(from, engine.handleResponse({ id: 'in-2', from, text: 'more' }));
  const more = JSON.parse(requests[2].options.body);
  assert.equal(more.interactive.type, 'list');
  assert.deepEqual(more.interactive.action.sections[0].rows.map((row) => row.id),
    ['menu.status', 'menu.doctors', 'menu.change', 'menu.cancel', 'menu.issue', 'menu.feedback']);
  await sender.sendResponse(from, engine.handleResponse({ id: 'in-3', from, text: 'hi' }));
  assert.equal(requests.filter(({ url }) => url.endsWith('/media')).length, 1);
});

test('uses a picture message then buttons if Meta rejects a combined card', async () => {
  const sent = [];
  const sender = createMetaSender({
    accessToken: 'test-token', phoneNumberId: '123456', graphVersion: 'v24.0',
    fetchImpl: async (url, options) => {
      if (url.endsWith('/media')) return { ok: true, json: async () => ({ id: 'media-123' }) };
      const body = JSON.parse(options.body);
      sent.push(body);
      if (body.interactive?.header) return { ok: false, status: 400 };
      return { ok: true, json: async () => ({ messages: [{ id: 'wamid.out' }] }) };
    },
  });
  const from = '919000000001';
  const welcome = createDemoEngine().handleResponse({ id: 'in-1', from, text: 'hi' });
  await sender.sendResponse(from, welcome);
  assert.deepEqual(sent.map((body) => body.type), ['interactive', 'image', 'interactive']);
  assert.equal(sent[1].image.id, 'media-123');
  assert.equal(sent[2].interactive.header, undefined);
});

test('webhook challenge, signature gate, and duplicate delivery', async (context) => {
  const sent = [];
  const { server } = createWebhookServer({
    verifyToken: 'verify-me', appSecret: 'secret', phoneNumberId: '123456',
    engine: createDemoEngine(),
    sendText: async (to, body) => { sent.push({ to, body }); },
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;

  const challenge = await fetch(`${base}/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=ok123`);
  assert.equal(challenge.status, 200);
  assert.equal(await challenge.text(), 'ok123');
  assert.equal((await fetch(`${base}/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=ok123`)).status, 403);

  const body = JSON.stringify(payload);
  assert.equal((await fetch(`${base}/webhook`, { method: 'POST', body })).status, 403);
  const signed = { method: 'POST', body, headers: { 'x-hub-signature-256': signature(body, 'secret') } };
  assert.equal((await fetch(`${base}/webhook`, signed)).status, 200);
  assert.equal((await fetch(`${base}/webhook`, signed)).status, 200);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].to, '919000000001');
  assert.match(sent[0].body, /TEST DEMO/);
});

test('signed webhook dispatches the picture-led welcome presentation', async (context) => {
  let delivered;
  const sendText = async () => { throw new Error('Plain text sender should not be used'); };
  sendText.sendResponse = async (to, reply) => { delivered = { to, reply }; };
  const { server } = createWebhookServer({
    verifyToken: 'verify-me', appSecret: 'secret', phoneNumberId: '123456', sendText,
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const body = JSON.stringify(payload);
  const response = await fetch(`http://127.0.0.1:${server.address().port}/webhook`, {
    method: 'POST', body,
    headers: { 'x-hub-signature-256': signature(body, 'secret') },
  });
  assert.equal(response.status, 200);
  assert.equal(delivered.to, '919000000001');
  assert.equal(delivered.reply.kind, 'buttons');
  assert.equal(delivered.reply.image, true);
});

test('simultaneous retries of one inbound ID dispatch a single reply', async (context) => {
  let sendCount = 0;
  const sendText = async () => {
    sendCount += 1;
    await new Promise((resolve) => setTimeout(resolve, 15));
  };
  const { server } = createWebhookServer({
    verifyToken: 'verify-me', appSecret: 'secret', phoneNumberId: '123456', sendText,
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const body = JSON.stringify(payload);
  const base = `http://127.0.0.1:${server.address().port}/webhook`;
  const sendWebhook = () => fetch(base, {
    method: 'POST', body,
    headers: { 'x-hub-signature-256': signature(body, 'secret') },
  });
  const responses = await Promise.all([sendWebhook(), sendWebhook()]);
  assert.deepEqual(responses.map((response) => response.status), [200, 200]);
  assert.equal(sendCount, 1);
});
