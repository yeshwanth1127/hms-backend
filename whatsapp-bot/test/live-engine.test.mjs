import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveEngine } from '../live-engine.mjs';
import { BackendError } from '../backend-client.mjs';

const department = { id: 'dept-1', slug: 'cardiology', name: 'Cardiology', tagline: 'Heart care', guide_asset_id: 'guide-1' };
const branch = { id: 'branch-1', slug: 'indiranagar', name: 'Indiranagar Clinic', area: 'Indiranagar', timezone: 'Asia/Kolkata', is_virtual: false };
const doctor = { id: 'doctor-1', slug: 'doctor-one', name: 'Dr. One', title: 'Cardiologist', bio: 'Heart care', consultation_fee: 1000, photo_asset_id: 'photo-1' };
const slots = [
  { doctor_id: doctor.id, branch_id: branch.id, consultation_type: 'in_person', starts_at: '2026-10-02T04:00:00Z', ends_at: '2026-10-02T04:30:00Z' },
  { doctor_id: doctor.id, branch_id: branch.id, consultation_type: 'in_person', starts_at: '2026-10-02T04:30:00Z', ends_at: '2026-10-02T05:00:00Z' },
];

function fakeBackend() {
  const prefs = { service_messages: false, marketing: false, stopped_all: false, handoff: null };
  const appointments = [];
  const calls = [];
  const conversations = new Map();
  return {
    calls, appointments,
    preferences: async () => ({ ...prefs, reception: { hours: '9 am–6 pm', response: 'We reply during opening hours.', phone: '08012345678' } }),
    changePreferences: async (_sender, body) => { Object.assign(prefs, body); if (body.stopped_all) { prefs.marketing = false; prefs.service_messages = false; } calls.push(['preferences', body]); return prefs; },
    reception: async () => { prefs.handoff = { case_id: 'case-reception', status: 'waiting' }; return prefs.handoff; },
    receptionMessage: async body => { calls.push(['receptionMessage', body]); },
    resumeReception: async () => { prefs.handoff = null; },
    engageOutreach: async (...args) => { calls.push(['engagement', args]); },
    loadConversation: async (sender) => structuredClone(conversations.get(sender) ?? {
      state: { step: 'menu', draft: {} }, last_message_id: null, last_reply: null,
    }),
    saveConversation: async (sender, body) => { conversations.set(sender, structuredClone(body)); },
    catalogue: async () => ({ branches: [branch], departments: [department] }),
    doctors: async () => [doctor],
    asset: async (id) => ({ bytes: Buffer.from(id), mimeType: id === 'guide-1' ? 'application/pdf' : 'image/png' }),
    availability: async () => ({ slots, timezone: branch.timezone }),
    hold: async (body) => { calls.push(['hold', body]); return { id: `hold-${calls.length}`, ...body, status: 'active' }; },
    releaseHold: async (id) => { calls.push(['release', id]); },
    book: async (body) => {
      calls.push(['book', body]);
      const item = { id: 'appointment-1', confirmation_code: 'AVO-1234567890ABCDEF', doctor_name: doctor.name,
        branch_name: branch.name, timezone: branch.timezone, status: 'confirmed',
        reservation: { ...slots[0], id: body.hold_id } };
      appointments.push(item);
      return item;
    },
    appointments: async () => appointments,
    appointmentsPage: async (_sender, limit, offset) => ({ total: appointments.length,
      items: appointments.slice(offset, offset + limit) }),
    appointment: async (id) => appointments.find((item) => item.id === id),
    appointmentByCode: async (code) => {
      const item = appointments.find((value) => value.confirmation_code === code);
      if (!item) throw new BackendError(404, 'APPOINTMENT_NOT_FOUND', 'Appointment was not found');
      return item;
    },
    reschedule: async (id, body) => { calls.push(['reschedule', body]); appointments[0].reservation = { ...slots[1], id: body.new_hold_id }; return appointments[0]; },
    cancel: async () => { appointments[0].status = 'cancelled'; return appointments[0]; },
    case: async (body) => { calls.push(['case', body]); return { id: 'case-12345678', status: 'open' }; },
    attach: async (...args) => { calls.push(['attach', args]); return { id: 'attachment-1' }; },
  };
}

test('backend mode sends uploaded guide and doctor photo, then books and manages the authoritative appointment', async () => {
  const backend = fakeBackend();
  const engine = createLiveEngine({ backend, clinicReady: true, now: () => new Date('2026-09-29T10:00:00Z') });
  let n = 0;
  let lastReply;
  const send = async (choiceId, text = '') => {
    if (/^slot\.\d+$/.test(choiceId ?? '')) { const menu = lastReply?.kind === 'sequence' ? lastReply.messages.at(-1) : lastReply; choiceId = menu.sections?.flatMap(section => section.rows).find(row => row.id.startsWith(choiceId + '.'))?.id ?? choiceId; }
    lastReply = await engine.handleResponse({ id: `wamid.${++n}`, from: '919811111111', type: 'text', choiceId, text }); return lastReply; };
  assert.equal((await send(null, 'hi')).kind, 'buttons');
  assert.equal((await send('menu.book')).kind, 'list');
  const guide = await send('specialty.cardiology');
  assert.equal(guide.messages[0].kind, 'document');
  assert.equal(guide.messages[1].kind, 'list');
  assert.equal((await send('branch.indiranagar')).kind, 'list');
  const profile = await send('doctor.doctor-1');
  assert.equal(profile.messages[0].kind, 'image');
  assert.equal(profile.messages[1].kind, 'list');
  assert.match((await send('slot.1')).text, /patient name/i);
  const bookingPrompt = await send(null, 'Test Patient');
  assert.equal(bookingPrompt.kind, 'buttons');
  const booked = await send(bookingPrompt.buttons[0].id);
  assert.match(booked.body, /Appointment confirmed/);
  assert.equal(backend.calls.find((item) => item[0] === 'book')[1].consent_to_reminders, true);
  assert.equal((await send(null, 'hi')).buttons[1].id, 'menu.status');
  assert.equal((await send('menu.status')).kind, 'list');
  assert.match((await send('booking.appointment-1')).body, /AVO-1234/);
  assert.equal((await send('booking.change')).kind, 'list');
  const changePrompt = await send('slot.1');
  assert.equal(changePrompt.kind, 'buttons');
  assert.match((await send(changePrompt.buttons[0].id)).body, /Appointment changed/);
  await send('receipt.visits');
  await send('booking.appointment-1');
  const cancelPrompt = await send('booking.cancel');
  assert.match((await send(cancelPrompt.buttons[0].id)).body, /Appointment cancelled/);
});

test('production rejects stale confirmation buttons and typed yes', async () => {
  const backend = fakeBackend();
  const engine = createLiveEngine({ backend, clinicReady: true, now: () => new Date('2026-09-29T10:00:00Z') });
  let n = 0;
  let lastReply;
  const send = async (choiceId, text = '') => {
    if (/^slot\.\d+$/.test(choiceId ?? '')) { const menu = lastReply?.kind === 'sequence' ? lastReply.messages.at(-1) : lastReply; choiceId = menu.sections?.flatMap(section => section.rows).find(row => row.id.startsWith(choiceId + '.'))?.id ?? choiceId; }
    lastReply = await engine.handleResponse({ id: `wamid.safe-${++n}`, from: '919811111111', type: 'text', choiceId, text }); return lastReply; };
  await send(null, 'hi');
  await send('menu.book');
  await send('specialty.cardiology');
  await send('branch.indiranagar');
  await send('doctor.doctor-1');
  await send('slot.1');
  const prompt = await send(null, 'Test Patient');
  assert.match((await send('confirm.only', 'yes')).text, /current booking confirmation/i);
  assert.equal((await backend.appointments()).length, 0);
  assert.match((await send(prompt.buttons[1].id)).body, /Appointment confirmed/);
  await send('menu.status');
  await send('booking.appointment-1');
  const cancel = await send('booking.cancel');
  assert.match((await send(prompt.buttons[1].id)).text, /current cancellation button/i);
  assert.equal((await backend.appointments())[0].status, 'confirmed');
  assert.match((await send(cancel.buttons[0].id)).body, /Appointment cancelled/);
});

test('an old booking confirmation expires without creating an appointment', async () => {
  const backend = fakeBackend();
  let time = new Date('2026-09-29T10:00:00Z');
  const engine = createLiveEngine({ backend, clinicReady: true, now: () => time });
  let n = 0;
  let lastReply;
  const send = async (choiceId, text = '') => {
    if (/^slot\.\d+$/.test(choiceId ?? '')) { const menu = lastReply?.kind === 'sequence' ? lastReply.messages.at(-1) : lastReply; choiceId = menu.sections?.flatMap(section => section.rows).find(row => row.id.startsWith(choiceId + '.'))?.id ?? choiceId; }
    lastReply = await engine.handleResponse({ id: `wamid.expiry-${++n}`, from: '919811111111', type: 'text', choiceId, text }); return lastReply; };
  await send(null, 'hi');
  await send('menu.book');
  await send('specialty.cardiology');
  await send('branch.indiranagar');
  await send('doctor.doctor-1');
  await send('slot.1');
  const prompt = await send(null, 'Test Patient');
  time = new Date('2026-09-29T10:11:00Z');
  assert.match((await send(prompt.buttons[1].id)).text, /expired/i);
  assert.equal((await backend.appointments()).length, 0);
});

test('production visit management requires a booking reference and expires that access', async () => {
  const backend = fakeBackend();
  let time = new Date('2026-09-29T10:00:00Z');
  const engine = createLiveEngine({ backend, clinicReady: true, requireReference: true, now: () => time });
  let n = 0;
  let lastReply;
  const send = async (choiceId, text = '') => {
    if (/^slot\.\d+$/.test(choiceId ?? '')) { const menu = lastReply?.kind === 'sequence' ? lastReply.messages.at(-1) : lastReply; choiceId = menu.sections?.flatMap(section => section.rows).find(row => row.id.startsWith(choiceId + '.'))?.id ?? choiceId; }
    lastReply = await engine.handleResponse({ id: `wamid.reference-${++n}`, from: '919811111111', type: 'text', choiceId, text }); return lastReply; };
  assert.equal((await send(null, 'hi')).buttons[1].title, 'Open a visit');
  await send('menu.book');
  await send('specialty.cardiology');
  await send('branch.indiranagar');
  await send('doctor.doctor-1');
  await send('slot.1');
  const confirmation = await send(null, 'Test Patient');
  await send(confirmation.buttons[1].id);
  await send(null, 'hi');
  assert.match((await send('menu.status')).text, /booking reference/i);
  assert.match((await send(null, 'AVO-FFFFFFFFFFFFFFFF')).text, /No visit was found/i);
  assert.match((await send(null, 'AVO-1234567890ABCDEF')).body, /AVO-1234/);
  const cancel = await send('booking.cancel');
  time = new Date('2026-09-29T10:31:00Z');
  assert.match((await send(cancel.buttons[0].id)).text, /session expired/i);
  assert.equal((await backend.appointments())[0].status, 'confirmed');
  assert.equal((await send(null, 'hi')).kind, 'buttons');
});

test('backend mode records issues, feedback, and a media attachment for staff', async () => {
  const backend = fakeBackend();
  const engine = createLiveEngine({ backend, downloadMedia: async () => ({ bytes: Buffer.from('image'), mimeType: 'image/png', filename: 'image.png' }) });
  let n = 0;
  let lastReply;
  const send = async (choiceId, text = '') => {
    if (/^slot\.\d+$/.test(choiceId ?? '')) { const menu = lastReply?.kind === 'sequence' ? lastReply.messages.at(-1) : lastReply; choiceId = menu.sections?.flatMap(section => section.rows).find(row => row.id.startsWith(choiceId + '.'))?.id ?? choiceId; }
    lastReply = await engine.handleResponse({ id: `wamid.${++n}`, from: '919811111111', type: 'text', choiceId, text }); return lastReply; };
  await send('menu.issue');
  assert.match((await send(null, 'Please call me')).text, /staff review/);
  await send('menu.feedback');
  await send('rating.5');
  assert.match((await send(null, 'Helpful')).text, /private feedback/);
  const media = await engine.handleResponse({ id: 'wamid.media-1', from: '919811111111', type: 'image', mediaId: '12345' });
  assert.match(media.text, /attachment was received/);
  assert.equal(backend.calls.filter((item) => item[0] === 'case').length, 3);
  assert.equal(backend.calls.filter((item) => item[0] === 'attach').length, 1);
});

test('backend mode restores a choice and media reply after a bot restart', async () => {
  const backend = fakeBackend();
  const first = createLiveEngine({ backend });
  await first.handleResponse({ id: 'wamid.restart-1', from: '919811111111', type: 'text', choiceId: 'menu.book', text: '' });
  const second = createLiveEngine({ backend });
  const message = { id: 'wamid.restart-2', from: '919811111111', type: 'text',
    choiceId: 'specialty.cardiology', text: '' };
  const reply = await second.handleResponse(message);
  assert.equal(reply.messages[0].kind, 'document');
  const third = createLiveEngine({ backend });
  const replay = await third.handleResponse(message);
  assert.equal(replay.messages[0].kind, 'document');
  assert.deepEqual(replay.messages[0].media.bytes, Buffer.from('guide-1'));
  assert.equal((await third.handleResponse({ id: 'wamid.restart-3', from: '919811111111', type: 'text',
    choiceId: 'branch.indiranagar', text: '' })).kind, 'list');
});


test('separate opt-ins, STOP, reception pause and resume preserve the patient’s choices', async () => {
  const backend = fakeBackend(), engine = createLiveEngine({ backend });
  let n = 0;
  const send = (choiceId, text = '') => engine.handleResponse({ id: `wamid.preferences-${++n}`, from: '919811111111', type: 'text', choiceId, text });
  const prefs = await send('menu.preferences');
  assert.match(prefs.body, /Visit reminders and follow-ups: off/);
  await send('prefs.service.on');
  assert.equal((await backend.preferences()).service_messages, true);
  assert.equal((await backend.preferences()).marketing, false);
  await send('prefs.marketing.on');
  await send(null, 'STOP OFFERS');
  assert.equal((await backend.preferences()).service_messages, true);
  assert.equal((await backend.preferences()).marketing, false);
  const handoff = await send('menu.reception');
  assert.match(handoff.body, /bot is paused/);
  assert.equal((await send(null, 'I need to change my visit')).kind, 'silent');
  assert.equal(backend.calls.at(-1)[0], 'receptionMessage');
  assert.equal((await send('reception.resume')).kind, 'buttons');
  await send(null, 'STOP');
  assert.equal((await backend.preferences()).service_messages, false);
  assert.equal((await send(null, 'hi')).kind, 'buttons');
});

test('doctor browsing does not force booking and slot menus paginate, accept dates and reject stale taps', async () => {
  const backend = fakeBackend();
  const many = Array.from({ length: 18 }, (_, n) => ({ ...slots[0], starts_at: new Date(Date.parse(slots[0].starts_at) + n * 1800000).toISOString(), ends_at: new Date(Date.parse(slots[0].ends_at) + n * 1800000).toISOString() }));
  backend.availability = async () => ({ slots: many });
  const engine = createLiveEngine({ backend, clinicReady: true, now: () => new Date('2026-10-01T04:00:00Z') });
  let n = 0;
  const send = (choiceId, text = '') => engine.handleResponse({ id: `wamid.dates-${++n}`, from: '919811111111', type: 'text', choiceId, text });
  await send('menu.doctors'); await send('specialty.cardiology'); await send('branch.indiranagar');
  const profile = await send('doctor.doctor-1');
  assert.equal(profile.messages.at(-1).kind, 'buttons');
  assert.match(profile.messages.at(-1).body, /₹1000/);
  const times = await send('doctor.book');
  const oldId = times.sections[0].rows[0].id;
  assert.ok(times.sections[0].rows.length <= 10);
  assert.ok(times.sections[0].rows.some(row => row.id === 'page.slot.1'));
  const second = await send('page.slot.1');
  assert.notEqual(second.sections[0].rows[0].id, oldId);
  assert.match((await send(oldId)).text, /menu expired/);
  await send('slots.date');
  assert.match((await send(null, '2026-02-30')).text, /valid YYYY-MM-DD/);
  await send('date.2026-10-02');
  const selected = await send('page.slot.0');
  await send(selected.sections[0].rows[0].id);
  await send(null, 'hi');
  assert.equal(backend.calls.at(-1)[0], 'release');
});

test('the receipt manage action expires and quoted fees are passed to the authoritative backend', async () => {
  const backend = fakeBackend(); let time = new Date('2026-10-01T04:00:00Z');
  const engine = createLiveEngine({ backend, clinicReady: true, requireReference: true, now: () => time });
  let n = 0;
  const send = (choiceId, text = '') => engine.handleResponse({ id: `wamid.receipt-${++n}`, from: '919811111111', type: 'text', choiceId, text });
  await send('menu.book'); await send('specialty.cardiology'); await send('branch.indiranagar');
  const doctorReply = await send('doctor.doctor-1');
  await send(doctorReply.messages.at(-1).sections[0].rows[0].id);
  const confirmation = await send(null, 'Test Patient');
  assert.match(confirmation.body, /No payment is taken/);
  const receipt = await send(confirmation.buttons[1].id);
  assert.equal(backend.calls.find(row => row[0] === 'book')[1].expected_fee, 1000);
  const manage = receipt.buttons[0].id;
  await send(null, 'hi');
  assert.match((await send(manage)).body, /AVO-/);
  time = new Date('2026-10-01T04:31:00Z');
  assert.match((await send(manage)).text, /shortcut expired/);
});
