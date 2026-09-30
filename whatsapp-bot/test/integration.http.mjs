import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, randomBytes } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { createBackendClient } from '../backend-client.mjs';
import { createLiveEngine } from '../live-engine.mjs';
import { createInboundWorker, createWebhookServer } from '../server.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const bot = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.HMS_TEST_PYTHON || join(root, '.venv/bin/python');

async function unusedPort() {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

test('signed WhatsApp webhook and worker use real HMS bookings, uploads and persisted state', { timeout: 45000 }, async (context) => {
  const directory = await mkdtemp(join(tmpdir(), 'hms-wa-http-'));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const key = randomBytes(32).toString('hex');
  // CI may supply a disposable PostgreSQL database. Never point this at clinic data.
  const env = { ...process.env, APP_ENV: 'development', DATABASE_URL: process.env.HMS_TEST_DATABASE_URL || `sqlite:///${join(directory, 'test.db')}`,
    MEDIA_DIR: join(directory, 'uploads'), ADMIN_API_KEY: key, VOICE_SERVICE_API_KEY: key,
    WHATSAPP_SERVICE_API_KEY: key, WHATSAPP_OWNER_SECRET: randomBytes(32).toString('hex') };
  const migrated = spawnSync(python, ['-m', 'alembic', 'upgrade', 'head'], { cwd: root, env, encoding: 'utf8' });
  assert.equal(migrated.status, 0, migrated.stderr || migrated.error?.message);
  const port = await unusedPort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const api = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port), '--no-access-log'],
    { cwd: root, env, stdio: ['ignore', 'ignore', 'pipe'] });
  let diagnostics = '';
  api.stderr.on('data', (chunk) => { diagnostics = (diagnostics + chunk.toString()).slice(-4000); });
  context.after(async () => {
    if (api.exitCode !== null) return;
    const exited = new Promise((resolve) => api.once('exit', resolve));
    api.kill('SIGTERM');
    let timer;
    try { await Promise.race([exited, new Promise((resolve) => { timer = setTimeout(() => { api.kill('SIGKILL'); resolve(); }, 5000); })]); }
    finally { clearTimeout(timer); }
  });
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    ready = await fetch(`${baseUrl}/api/health/ready`).then((r) => r.ok).catch(() => false);
    if (ready) break;
    if (api.exitCode !== null) break;
    await delay(50);
  }
  assert.ok(ready, `Isolated API did not start: ${diagnostics}`);
  const backend = createBackendClient({ baseUrl, serviceKey: key });
  assert.equal((await backend.inboundReady()).ready, true);
  const catalog = await backend.catalogue();
  const department = catalog.departments.find((d) => d.slug === 'cardiology');
  const branch = catalog.branches.find((b) => b.slug === 'indiranagar');
  const doctor = (await backend.doctors(department.slug, branch.slug))[0];
  const pdf = await readFile(join(bot, 'demo-guides/avocado-demo-heart-care.pdf'));
  const photo = await readFile(join(bot, 'doctors/sample-a.png'));
  for (const [path, bytes, mime, filename] of [
    [`departments/${department.id}/guide`, pdf, 'application/pdf', 'guide.pdf'],
    [`doctors/${doctor.id}/photo`, photo, 'image/png', 'portrait.png'],
  ]) {
    const form = new FormData();
    form.set('file', new Blob([bytes], { type: mime }), filename);
    const result = await fetch(`${baseUrl}/api/v1/admin/${path}`, { method: 'POST', headers: { 'X-Admin-Key': key }, body: form });
    assert.equal(result.status, 201, await result.text());
  }
  let engine = createLiveEngine({ backend, clinicReady: false, requireReference: true,
    downloadMedia: async () => ({ bytes: photo, mimeType: 'image/png', filename: 'patient.png' }) });
  const sent = [];
  const sendText = async () => assert.fail('Expected structured reply');
  sendText.sendResponse = async (from, reply, id) => sent.push({ from, reply, id });
  let worker = createInboundWorker({ backend, engine, sendText });
  const appSecret = randomBytes(32).toString('hex');
  const { server } = createWebhookServer({ appSecret, verifyToken: 'test-verification', phoneNumberId: '123456',
    engine, sendText, enqueueInbound: backend.enqueueInbound, checkReady: backend.inboundReady });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const webhook = `http://127.0.0.1:${server.address().port}/webhook`;
  const sender = '919000000001';
  let sequence = 0;
  const bodyFor = (message) => JSON.stringify({ object: 'whatsapp_business_account', entry: [{ changes: [{ value: {
    metadata: { phone_number_id: '123456' }, messages: [message],
  } }] }] });
  const post = (body, signature = `sha256=${createHmac('sha256', appSecret).update(body).digest('hex')}`) =>
    fetch(webhook, { method: 'POST', headers: { 'x-hub-signature-256': signature }, body });
  const send = async (choiceId, text = '', extra = {}) => {
    const id = `wamid.http-${++sequence}`;
    const message = choiceId
      ? { id, from: sender, type: 'interactive', interactive: { type: 'button_reply', button_reply: { id: choiceId, title: 'test' } } }
      : { id, from: sender, type: 'text', text: { body: text }, ...extra };
    const body = bodyFor(message);
    assert.equal((await post(body)).status, 200);
    assert.equal(await worker(), true);
    assert.equal(sent.at(-1)?.id, id, 'Worker must dispatch the claimed message');
    assert.equal(await worker(), false);
    return { reply: sent.at(-1).reply, body, id };
  };
  assert.equal((await post(bodyFor({ id: 'wamid.invalid', from: sender, type: 'text', text: { body: 'hi' } }), 'sha256=invalid')).status, 403);
  const welcome = await send(null, 'hi');
  assert.equal(welcome.reply.kind, 'buttons');
  assert.equal((await post(welcome.body)).status, 200);
  assert.equal(await worker(), false, 'Duplicate webhook must not send again');
  assert.equal(sent.length, 1);
  await send('menu.book');
  const guide = (await send(`specialty.${department.slug}`)).reply;
  assert.equal(guide.messages[0].kind, 'document');
  assert.deepEqual(guide.messages[0].media.bytes, pdf);
  // Recreate the engine and worker to exercise recovery from backend state.
  engine = createLiveEngine({ backend, clinicReady: false, requireReference: true,
    downloadMedia: async () => ({ bytes: photo, mimeType: 'image/png', filename: 'patient.png' }) });
  worker = createInboundWorker({ backend, engine, sendText });
  await send(`branch.${branch.slug}`);
  const profile = (await send(`doctor.${doctor.id}`)).reply;
  assert.equal(profile.messages[0].kind, 'image');
  assert.deepEqual(profile.messages[0].media.bytes, photo);
  assert.equal(profile.messages[1].kind, 'list');
  await send('slot.1');
  const prompt = (await send(null, 'Integration Patient')).reply;
  const booking = await send(prompt.buttons.find((b) => b.title === 'Book only').id);
  assert.match(booking.reply.body, /recorded for testing/);
  let visits = await backend.appointments(sender);
  assert.equal(visits.length, 1);
  assert.equal(visits[0].origin_channel, 'whatsapp');
  assert.equal(visits[0].consent_to_reminders, false);
  const reference = visits[0].confirmation_code;
  const originalStart = visits[0].reservation.starts_at;
  assert.match(reference, /^AVO-[0-9A-F]{16}$/);
  assert.equal((await post(booking.body)).status, 200);
  assert.equal(await worker(), false);
  assert.equal((await backend.appointments(sender)).length, 1);
  await assert.rejects(backend.appointmentByCode(reference, '919000000002'), { status: 404 });
  await send(null, 'hi');
  assert.match((await send('menu.status')).reply.text, /booking reference/);
  await send(null, reference);
  await send('booking.change');
  const change = (await send('slot.1')).reply;
  assert.match((await send(change.buttons[0].id)).reply.body, /Appointment changed/);
  visits = await backend.appointments(sender);
  assert.notEqual(visits[0].reservation.starts_at, originalStart);
  await send('receipt.visits');
  await send(null, reference);
  const cancel = (await send('booking.cancel')).reply;
  assert.match((await send(cancel.buttons[0].id)).reply.body, /Appointment cancelled/);
  assert.equal((await backend.appointments(sender))[0].status, 'cancelled');
  await send('menu.issue');
  await send(null, 'Please help with a test visit');
  await send('menu.feedback');
  await send('rating.5');
  await send(null, 'skip');
  assert.match((await send(null, '', { type: 'image', image: { id: 'test-media-123', caption: 'Test attachment' } })).reply.text, /attachment was received/);
  const cases = await fetch(`${baseUrl}/api/v1/admin/whatsapp-cases`, { headers: { 'X-Admin-Key': key } }).then((r) => r.json());
  assert.equal(cases.length, 3);
  assert.ok(cases.some((c) => c.kind === 'feedback' && c.rating === 5));
  assert.ok(cases.some((c) => c.attachments.length === 1));
  const issues = await fetch(`${baseUrl}/api/v1/admin/whatsapp-delivery-issues`, { headers: { 'X-Admin-Key': key } }).then((r) => r.json());
  assert.equal(issues.inbound.length, 0);
  assert.equal(issues.counts.inbound.sent, sequence);
});
