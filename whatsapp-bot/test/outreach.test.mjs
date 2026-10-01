import test from 'node:test';
import assert from 'node:assert/strict';
import { createMetaSender, incomingStatuses } from '../meta.mjs';
import { createOutreachWorker, createInboundWorker } from '../server.mjs';

test('Meta status parsing is bounded and only trusts the configured phone', () => {
  const payload = { object: 'whatsapp_business_account', entry: [{ changes: [{ value: { metadata: { phone_number_id: '100' }, statuses: [
    { id: 'wamid.read', status: 'read', timestamp: '1000' }, { id: 'wamid.invalid', status: 'unknown', timestamp: '1000' }, { id: 'wamid.badtime', status: 'sent', timestamp: 'NaN' },
  ] } }] }] };
  assert.deepEqual(incomingStatuses(payload, '100'), [{ meta_message_id: 'wamid.read', status: 'read', timestamp: 1000 }]);
  assert.deepEqual(incomingStatuses(payload, '101'), []);
});

test('templates send PDF headers and sender-bound quick replies; sync rejects unsafe pagination', async () => {
  const calls = [];
  const sender = createMetaSender({ accessToken: 'test-token', phoneNumberId: '123', graphVersion: 'v23.0', fetchImpl: async (url, options) => {
    calls.push({ url: String(url), options });
    if (String(url).includes('message_templates')) return Response.json({ data: [], paging: { next: 'https://evil.example/templates' } });
    return Response.json(String(url).endsWith('/media') ? { id: 'media-1' } : { messages: [{ id: 'wamid.sent' }] });
  } });
  await sender.sendTemplate('919700000001', 'clinic_guide', 'en', ['Clinic'], { header: { type: 'DOCUMENT', source: { id: 'asset-1', bytes: Buffer.from('%PDF'), mimeType: 'application/pdf', filename: 'guide.pdf' } }, buttons: [{ index: 1, payload: 'outreach.stop.job-123' }] });
  const payload = JSON.parse(calls[1].options.body);
  assert.equal(payload.template.components[0].parameters[0].document.id, 'media-1');
  assert.equal(payload.template.components[2].parameters[0].payload, 'outreach.stop.job-123');
  await assert.rejects(sender.listTemplates('100'), /Unsafe or incomplete/);
  assert.equal(calls.length, 3);
});

test('outreach worker prepares media, authorizes immediately before send and never sends when consent changed', async () => {
  const calls = [], job = { id: 'job-1', claim_token: 'token', sender_id: '919700000001', purpose: 'campaign', asset_id: 'asset-1', header_type: 'IMAGE', template: { name: 'clinic_offer', language: 'en' }, parameters: [], buttons: [] };
  const backend = { claimOutreach: async () => job, asset: async () => { calls.push('asset'); return { bytes: Buffer.from('image'), mimeType: 'image/png' }; }, authorizeOutreach: async () => { calls.push('authorize'); return { send: false }; }, completeOutreach: async () => calls.push('complete'), failOutreach: async () => calls.push('failed') };
  const sendText = async () => assert.fail('Consent gate must prevent the send');
  sendText.sendTemplate = sendText;
  assert.equal(await createOutreachWorker({ backend, sendText })(), true);
  assert.deepEqual(calls, ['asset', 'authorize']);
  backend.authorizeOutreach = async () => { calls.push('authorize'); return { send: true }; };
  sendText.sendTemplate = async () => { calls.push('send'); throw new Error('timeout'); };
  await createOutreachWorker({ backend, sendText, log: { error() {} } })();
  assert.deepEqual(calls.slice(-4), ['asset', 'authorize', 'send', 'failed']);
  assert.ok(!calls.includes('complete'));
});

test('paused reception completes inbound work without a bot message', async () => {
  const calls = [];
  const backend = { claimInbound: async () => ({ message_id: 'wamid.pause', sender_id: '919700000001', claim_token: 'token', payload: {} }), markInboundSending: async () => calls.push('sending'), markInboundSent: async () => calls.push('sent'), markInboundFailed: async () => assert.fail('Must complete') };
  await createInboundWorker({ backend, engine: { handleResponse: async () => ({ kind: 'silent' }) }, sendText: async () => assert.fail('Paused bot must not reply') })();
  assert.deepEqual(calls, ['sending', 'sent']);
});

test('signed webhook persists delivery receipts before acknowledging and refuses a forged update', async context => {
  const { createHmac } = await import('node:crypto');
  const { createWebhookServer } = await import('../server.mjs');
  const receipts = [];
  const { server } = createWebhookServer({ verifyToken: 'verify', appSecret: 'secret', phoneNumberId: '123', sendText: async () => assert.fail('Status callbacks must not send messages'), recordDelivery: async receipt => receipts.push(receipt) });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  context.after(() => new Promise(resolve => server.close(resolve)));
  const body = JSON.stringify({ object: 'whatsapp_business_account', entry: [{ changes: [{ value: { metadata: { phone_number_id: '123' }, statuses: [{ id: 'wamid.signed-status', status: 'delivered', timestamp: '1234' }] } }] }] });
  const url = `http://127.0.0.1:${server.address().port}/webhook`;
  assert.equal((await fetch(url, { method: 'POST', body, headers: { 'x-hub-signature-256': 'sha256=wrong' } })).status, 403);
  assert.equal(receipts.length, 0);
  assert.equal((await fetch(url, { method: 'POST', body, headers: { 'x-hub-signature-256': 'sha256=' + createHmac('sha256', 'secret').update(body).digest('hex') } })).status, 200);
  assert.deepEqual(receipts, [{ meta_message_id: 'wamid.signed-status', status: 'delivered', timestamp: 1234 }]);
});
