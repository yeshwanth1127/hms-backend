import test from 'node:test';
import assert from 'node:assert/strict';
import { createDemoEngine } from '../engine.mjs';

function harness() {
  let time = new Date('2026-09-28T10:00:00.000Z');
  const engine = createDemoEngine({ now: () => time });
  let sequence = 0;
  const send = (text, from = '919000000001', type = 'text') =>
    engine.handle({ id: `message-${++sequence}`, from, text, type });
  return { engine, send, setTime: (value) => { time = new Date(value); } };
}

test('books, changes, and cancels a local test request without claiming a clinic confirmation', () => {
  const { engine, send } = harness();
  assert.match(send('hi'), /TEST DEMO/);
  assert.match(send('1'), /choose a specialty/i);
  assert.match(send('1'), /Sample Clinician A/);
  assert.match(send('1'), /sample slot/i);
  assert.match(send('1'), /test name or alias/i);
  const confirmation = send('Tester');
  assert.match(confirmation, /TEST-0001/);
  assert.match(confirmation, /not a confirmed clinic appointment/i);
  assert.match(confirmation, /Send “hi” to return to the start/i);
  const initialSlot = engine.getBooking('919000000001').slotId;

  assert.match(send('change'), /select a sample slot/i);
  assert.match(send('1'), /request was changed/i);
  assert.notEqual(engine.getBooking('919000000001').slotId, initialSlot);
  assert.match(send('cancel booking'), /Reply “yes” or “no”/);
  assert.match(send('yes'), /request was cancelled/i);
  assert.equal(engine.getBooking('919000000001').status, 'cancelled');
});

test('prevents two test phones from receiving the same sample slot', () => {
  const { engine, send } = harness();
  send('book'); send('1'); send('1'); send('1'); send('Tester One');
  const occupied = engine.getBooking('919000000001').slotId;
  send('book', '919000000002');
  send('1', '919000000002');
  const choices = send('1', '919000000002');
  assert.doesNotMatch(choices, /2026-09-29 at 10:00/);
  send('1', '919000000002');
  send('Tester Two', '919000000002');
  assert.notEqual(engine.getBooking('919000000002').slotId, occupied);
});

test('issues, ratings, and media stay in the local demo and have explicit boundaries', () => {
  const { engine, send, setTime } = harness();
  send('issue');
  assert.match(send('The menu did not work'), /TEST-ISSUE-0001/);
  assert.equal(engine.getIssueCount(), 1);
  send('rate'); send('4');
  assert.match(send('skip'), /No public review was posted/);
  assert.equal(engine.getRatingCount(), 1);
  assert.match(send('', '919000000001', 'image'), /does not download, read, or forward media/);
  assert.match(engine.followup('919000000001'), /not a clinic follow-up/);
  setTime('2026-09-30T10:00:00.000Z');
  assert.equal(engine.followup('919000000001'), null);
});

test('repeated inbound message IDs do not repeat a state change', () => {
  const { engine } = harness();
  const send = (id, text) => engine.handle({ id, from: '919000000001', text });
  send('1', 'book'); send('2', '1'); send('3', '1'); send('4', '1');
  const first = send('5', 'Tester');
  assert.equal(send('5', 'Tester'), first);
  assert.equal(engine.getBooking('919000000001').reference, 'TEST-0001');
});

test('welcome choices, more options, clinicians and slots have tappable presentations', () => {
  const engine = createDemoEngine();
  const from = '919000000001';
  const choice = (id, text) => engine.handleResponse({ id, from, text });
  const welcome = choice('1', 'hi');
  assert.equal(welcome.kind, 'buttons');
  assert.equal(welcome.image, true);
  assert.deepEqual(welcome.buttons.map((button) => button.id),
    ['menu.book', 'menu.doctors', 'menu.more']);
  assert.deepEqual(choice('2', 'more').sections[0].rows.map((row) => row.id),
    ['menu.status', 'menu.doctors', 'menu.change', 'menu.cancel', 'menu.issue', 'menu.feedback']);
  const specialties = choice('3', 'book');
  assert.equal(specialties.kind, 'list');
  assert.equal(specialties.sections[0].rows.length, 3);
  const doctors = choice('4', 'specialty:general-care');
  assert.equal(doctors.kind, 'sequence');
  assert.equal(doctors.messages[0].kind, 'document');
  assert.match(doctors.messages[0].path, /avocado-demo-general-care\.pdf$/);
  assert.equal(doctors.messages[1].kind, 'list');
  assert.equal(doctors.messages[1].sections[0].rows.length, 2);
  const slots = choice('5', 'doctor:1');
  assert.equal(slots.kind, 'sequence');
  assert.equal(slots.messages[0].kind, 'image');
  assert.equal(slots.messages[1].kind, 'list');
  assert.ok(slots.messages[1].sections[0].rows.length > 0);
  assert.match(choice('6', 'slot:1').text, /test name or alias/i);
});

test('hi returns to a personalized start and saved appointments can be opened and managed', () => {
  const { engine, send } = harness();
  send('hi'); send('1'); send('1'); send('1'); send('1');
  const receipt = send('Tester');
  assert.match(receipt, /TEST-0001/);
  const welcome = engine.handleResponse({ id: 'after-booking', from: '919000000001', text: 'hi' });
  assert.deepEqual(welcome.buttons.map((button) => button.id),
    ['menu.book', 'menu.status', 'menu.more']);
  const list = engine.handleResponse({ id: 'view-list', from: '919000000001', text: 'my appointments' });
  assert.equal(list.kind, 'list');
  assert.equal(list.sections[0].rows[0].id, 'booking.TEST-0001');
  const detail = engine.handleResponse({ id: 'view-detail', from: '919000000001', text: 'booking:TEST-0001' });
  assert.deepEqual(detail.buttons.map((button) => button.id),
    ['booking.change', 'booking.cancel', 'booking.menu']);
  assert.match(detail.body, /TEST-0001/);
  assert.match(send('change selected'), /select a sample slot/i);
});

test('one phone can retain multiple test appointments, with separate cancellation and no cross-phone access', () => {
  const { engine, send } = harness();
  const book = (alias) => {
    send('book'); send('1'); send('1'); send('1'); send(alias);
  };
  book('First');
  book('Second');
  assert.deepEqual(engine.getBookings('919000000001').map((booking) => booking.reference),
    ['TEST-0002', 'TEST-0001']);
  const list = engine.handleResponse({ id: 'multi-list', from: '919000000001', text: 'my appointments' });
  assert.deepEqual(list.sections[0].rows.map((row) => row.id),
    ['booking.TEST-0002', 'booking.TEST-0001']);
  assert.match(send('booking:TEST-0001'), /TEST-0001/);
  assert.match(send('cancel selected'), /cancel TEST-0001/i);
  assert.match(send('yes'), /cancelled/i);
  assert.equal(engine.getBookings('919000000001')[0].status, 'active');
  assert.equal(engine.getBookings('919000000001')[1].status, 'cancelled');
  assert.doesNotMatch(send('my appointments', '919000000002'), /TEST-0001/);
});

test('appointment list remains within WhatsApp row limits and pages older requests', () => {
  const engine = createDemoEngine({ now: () => new Date('2026-09-28T10:00:00.000Z') });
  const from = '919000000001';
  let id = 0;
  const send = (text) => engine.handleResponse({ id: `page-${++id}`, from, text });
  for (let index = 0; index < 9; index += 1) {
    send('book');
    send(String((index % 3) + 1));
    send('1');
    send('1');
    send(`Tester ${String.fromCharCode(65 + index)}`.replace(' ', ''));
  }
  const firstPage = send('my appointments');
  assert.equal(firstPage.sections[0].rows.length, 9);
  assert.equal(firstPage.sections[0].rows.at(-1).id, 'booking.next');
  const secondPage = send('booking:next');
  assert.deepEqual(secondPage.sections[0].rows.map((row) => row.id),
    ['booking.TEST-0001', 'booking.prev']);
  const olderBooking = send('booking:TEST-0001');
  assert.match(olderBooking.body, /TEST-0001/);
});

test('doctor lookup sends the specialty PDF before a pictured profile card', () => {
  const engine = createDemoEngine();
  const from = '919000000001';
  const choice = (id, text) => engine.handleResponse({ id, from, text });
  assert.equal(choice('1', 'doctors').kind, 'list');
  const list = choice('2', 'specialty:skin-care');
  assert.deepEqual(list.messages.map((message) => message.kind), ['document', 'list']);
  const card = choice('3', 'doctor:2');
  assert.equal(card.kind, 'buttons');
  assert.match(card.imagePath, /sample-e\.png$/);
  assert.match(card.text, /fictional profile/i);
  const slots = choice('4', 'book selected');
  assert.deepEqual(slots.messages.map((message) => message.kind), ['image', 'list']);
});
