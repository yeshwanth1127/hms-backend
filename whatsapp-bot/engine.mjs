import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CATALOG = JSON.parse(readFileSync(new URL('./catalog.json', import.meta.url), 'utf8'));
const SPECIALTIES = Object.freeze(CATALOG.specialties);
const CLINICIANS = Object.freeze(CATALOG.clinicians.map((doctor) => ({
  ...doctor,
  specialty: SPECIALTIES.find((item) => item.id === doctor.specialtyId)?.name,
  imagePath: fileURLToPath(new URL(doctor.image, import.meta.url)),
})));

function pdfPathFor(specialty) {
  return fileURLToPath(new URL(`./demo-guides/${specialty.pdf}`, import.meta.url));
}

const MENU = [
  'TEST DEMO — no real appointments or medical advice.',
  'Reply with a number:',
  '1 Book a test slot',
  '2 Sample clinician details',
  '3 My appointments',
  '4 Raise a test issue',
  '5 Leave private feedback',
  'Send “hi” at any time to return to the start.',
].join('\n');

function welcome(hasBookings) {
  return {
    kind: 'buttons',
    text: MENU,
    body: `Welcome to Avocado Health 👋\nWhat can we help you with today?\n${hasBookings
      ? 'Your test requests are saved for this session. Tap My visits to see them.\n'
      : ''}\nTEST DEMO — no real appointments or medical advice.`,
    image: true,
    buttons: [
      { id: 'menu.book', title: 'Book a visit' },
      hasBookings
        ? { id: 'menu.status', title: 'My visits' }
        : { id: 'menu.doctors', title: 'Find a doctor' },
      { id: 'menu.more', title: 'More options' },
    ],
  };
}

const MORE_OPTIONS = {
  kind: 'list',
  text: 'TEST DEMO — more options:\nType “my appointments” to view test requests, “doctors” to browse profiles, “change” or “cancel booking” to manage a request, “issue” or “rate” for feedback. Send “hi” for the start.',
  body: 'What else can we help you with?\nTEST DEMO — local requests only.',
  buttonText: 'Choose an option',
  sections: [{ title: 'More options', rows: [
    { id: 'menu.status', title: 'My appointments' },
    { id: 'menu.doctors', title: 'Find a doctor' },
    { id: 'menu.change', title: 'Change appointment' },
    { id: 'menu.cancel', title: 'Cancel appointment' },
    { id: 'menu.issue', title: 'Raise an issue' },
    { id: 'menu.feedback', title: 'Leave feedback' },
  ] }],
};

function indiaDate(now, daysAhead) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now).map(({ type, value }) => [type, value]));
  const day = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day) + daysAhead);
  return new Date(day).toISOString().slice(0, 10);
}

function slotsFor(clinician, now, bookings, excludedReference) {
  const occupied = new Set([...bookings.values()]
    .filter((booking) => booking.status === 'active' && booking.reference !== excludedReference)
    .map((booking) => booking.slotId));
  return [1, 2].flatMap((offset) => clinician.times.map((time) => {
    const date = indiaDate(now, offset);
    return { id: `${clinician.id}:${date}:${time}`, date, time };
  })).filter((slot) => !occupied.has(slot.id));
}

function specialtyMenu(mode) {
  return {
    kind: 'list',
    text: `TEST DEMO — choose a specialty:\n${SPECIALTIES.map((specialty, index) =>
      `${index + 1} ${specialty.name}`).join('\n')}\nReply with a number or “menu”.`,
    body: mode === 'booking'
      ? 'Which specialty would you like to explore for a test request?'
      : 'Which specialty’s sample clinicians would you like to see?',
    buttonText: 'Choose specialty',
    sections: [{ title: 'Sample specialties', rows: SPECIALTIES.map((specialty) => ({
      id: `specialty.${specialty.id}`, title: specialty.name,
      description: `${CLINICIANS.filter((doctor) => doctor.specialtyId === specialty.id).length} fictional profiles`,
    })) }],
  };
}

function cliniciansFor(specialtyId) {
  return CLINICIANS.filter((doctor) => doctor.specialtyId === specialtyId);
}

function clinicianMenu(specialty) {
  const doctors = cliniciansFor(specialty.id);
  return {
    kind: 'list',
    text: `TEST DEMO — ${specialty.name} sample clinicians.\n${doctors.map((doctor, index) =>
      `${index + 1} ${doctor.name} — ${doctor.specialty}`).join('\n')}\nReply with a number for sample details, or “menu”.`,
    body: `The ${specialty.name} guide is above. Choose a fictional clinician.\nTEST DEMO — no real profiles.`,
    buttonText: 'View clinicians',
    sections: [{ title: specialty.name, rows: doctors.map((doctor, index) => ({
      id: `doctor.${index + 1}`, title: doctor.name, description: doctor.specialty,
    })) }],
  };
}

function slotMenu(slots, action) {
  if (!slots.length) return 'TEST DEMO — no sample slots remain. Reply “menu” to start again.';
  return {
    kind: 'list',
    text: `TEST DEMO — select a sample slot to ${action}:\n${slots.map((slot, index) =>
      `${index + 1} ${slot.date} at ${slot.time} IST`).join('\n')}\nReply with a number or “menu”.`,
    body: `Select a sample slot to ${action}.\nTEST DEMO — no real availability.`,
    buttonText: 'View test slots',
    sections: [{ title: 'Sample slots (IST)', rows: slots.map((slot, index) => ({
      id: `slot.${index + 1}`, title: `${slot.date} ${slot.time}`, description: 'Test slot only',
    })) }],
  };
}

function ratingMenu() {
  return {
    kind: 'list',
    text: 'TEST DEMO — rate this demo experience from 1 to 5. This is private and is not a public clinic review.',
    body: 'How was this demo experience?\nPrivate feedback; no public review is posted.',
    buttonText: 'Choose a rating',
    sections: [{ title: 'Demo rating', rows: [1, 2, 3, 4, 5].map((score) => ({
      id: `rating.${score}`, title: `${score} / 5`,
    })) }],
  };
}

function bookingSummary(booking) {
  const doctor = CLINICIANS.find((item) => item.id === booking.clinicianId);
  return `TEST DEMO — ${booking.reference}\n${doctor?.name ?? 'Sample clinician'}, ${booking.date} at ${booking.time} IST.\nAlias: ${booking.alias}. Status: ${booking.status}.\nThis is not a confirmed clinic appointment.`;
}

function choiceIndex(value, length, kind) {
  const selected = value.startsWith(`${kind}:`) ? value.slice(kind.length + 1) : value;
  if (!/^\d+$/.test(selected)) return -1;
  const index = Number(selected) - 1;
  return index >= 0 && index < length ? index : -1;
}

export function createDemoEngine({ now = () => new Date() } = {}) {
  const sessions = new Map();
  const bookings = new Map();
  const issues = [];
  const ratings = [];
  const repliesByMessageId = new Map();
  let bookingSequence = 0;
  let issueSequence = 0;

  function sessionFor(from) {
    if (!sessions.has(from)) sessions.set(from, { step: 'menu', draft: {}, lastInboundAt: null });
    return sessions.get(from);
  }

  function reset(session) {
    session.step = 'menu';
    session.draft = {};
  }

  function bookingsFor(from) {
    return [...bookings.values()].filter((booking) => booking.from === from).reverse();
  }

  function activeBookingsFor(from) {
    return bookingsFor(from).filter((booking) => booking.status === 'active');
  }

  function findOwnBooking(from, reference) {
    const booking = bookings.get(reference);
    return booking?.from === from ? booking : null;
  }

  function completionCard(booking, message) {
    return {
      kind: 'buttons',
      text: `${message}\n${bookingSummary(booking)}\nSend “hi” to return to the start, or “my appointments” to view your test requests.`,
      body: `${message}\n${bookingSummary(booking)}\n\nSend “hi” to return to the start.`,
      buttons: [
        { id: 'receipt.visits', title: 'My visits' },
        { id: 'receipt.menu', title: 'Main menu' },
      ],
    };
  }

  function appointmentMenu(from, session, action = 'view', page = 0) {
    const all = action === 'view' ? bookingsFor(from) : activeBookingsFor(from);
    if (!all.length) {
      reset(session);
      return action === 'view'
        ? 'TEST DEMO — no test appointments found. Send “hi” to return to the start or “book” to create one.'
        : 'TEST DEMO — no active test appointment to manage. Send “hi” to return to the start.';
    }
    const pageSize = 8;
    const totalPages = Math.ceil(all.length / pageSize);
    const currentPage = Math.max(0, Math.min(page, totalPages - 1));
    const visible = all.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
    session.step = 'selectBooking';
    session.draft = { action, page: currentPage, bookingRefs: visible.map((booking) => booking.reference) };
    const rows = visible.map((booking) => ({
      id: `booking.${booking.reference}`,
      title: booking.reference,
      description: `${booking.date} ${booking.time} · ${booking.status}`,
    }));
    if (currentPage > 0) rows.push({ id: 'booking.prev', title: 'Previous page' });
    if (currentPage + 1 < totalPages) rows.push({ id: 'booking.next', title: 'Next page' });
    const actionText = action === 'view' ? 'view' : action;
    return {
      kind: 'list',
      text: `TEST DEMO — choose an appointment to ${actionText} (page ${currentPage + 1}/${totalPages}):\n${visible.map((booking, index) =>
        `${index + 1} ${booking.reference} — ${booking.date} ${booking.time} IST (${booking.status})`).join('\n')}\n${currentPage > 0 ? 'Type “previous” for the previous page.\n' : ''}${currentPage + 1 < totalPages ? 'Type “next” for the next page.\n' : ''}Send “hi” to return to the start.`,
      body: `Choose a test appointment to ${actionText}. Page ${currentPage + 1} of ${totalPages}.\nTEST DEMO — local records only.`,
      buttonText: 'My appointments',
      sections: [{ title: 'Test appointments', rows }],
    };
  }

  function bookingDetails(session, booking) {
    session.step = 'bookingDetails';
    session.draft = { selectedReference: booking.reference };
    return {
      kind: 'buttons',
      text: `${bookingSummary(booking)}\n${booking.status === 'active'
        ? 'Reply “change selected” or “cancel selected” to manage it.'
        : 'This request is no longer active.'}\nSend “hi” to return to the start.`,
      body: `${bookingSummary(booking)}\nSend “hi” to return to the start.`,
      buttons: booking.status === 'active' ? [
        { id: 'booking.change', title: 'Change slot' },
        { id: 'booking.cancel', title: 'Cancel request' },
        { id: 'booking.menu', title: 'Main menu' },
      ] : [
        { id: 'menu.book', title: 'Book a visit' },
        { id: 'booking.menu', title: 'Main menu' },
      ],
    };
  }

  function startBooking(session) {
    session.step = 'chooseSpecialty';
    session.draft = { mode: 'booking' };
    return specialtyMenu('booking');
  }

  function startDoctorLookup(session) {
    session.step = 'chooseSpecialty';
    session.draft = { mode: 'details' };
    return specialtyMenu('details');
  }

  function showDoctorSlots(session, doctor) {
    const slots = slotsFor(doctor, now(), bookings);
    if (!slots.length) return 'TEST DEMO — this sample clinician has no slots left. Reply “book” to choose another.';
    session.step = 'chooseSlot';
    session.draft = { clinicianId: doctor.id, specialtyId: doctor.specialtyId, slots };
    const menu = slotMenu(slots, 'request');
    return {
      kind: 'sequence',
      text: `TEST DEMO — ${doctor.name} (${doctor.specialty}).\n${menu.text}`,
      messages: [
        { kind: 'image', imagePath: doctor.imagePath,
          caption: `TEST DEMO — ${doctor.name}\n${doctor.summary}\nFictional profile; no real availability.` },
        menu,
      ],
    };
  }

  function startChange(from, session, reference) {
    const active = activeBookingsFor(from);
    if (!reference && active.length > 1) return appointmentMenu(from, session, 'change');
    const booking = reference ? findOwnBooking(from, reference) : active[0];
    if (!booking || booking.status !== 'active') return appointmentMenu(from, session, 'change');
    const doctor = CLINICIANS.find((item) => item.id === booking.clinicianId);
    const slots = slotsFor(doctor, now(), bookings, booking.reference)
      .filter((slot) => slot.id !== booking.slotId);
    if (!slots.length) {
      reset(session);
      return 'TEST DEMO — no alternative sample slots remain. Your test request was not changed.';
    }
    session.step = 'changeSlot';
    session.draft = { slots, selectedReference: booking.reference };
    return slotMenu(slots, 'change your test request');
  }

  function startCancel(from, session, reference) {
    const active = activeBookingsFor(from);
    if (!reference && active.length > 1) return appointmentMenu(from, session, 'cancel');
    const booking = reference ? findOwnBooking(from, reference) : active[0];
    if (!booking || booking.status !== 'active') return appointmentMenu(from, session, 'cancel');
    session.step = 'confirmCancel';
    session.draft = { selectedReference: booking.reference };
    return {
      kind: 'buttons',
      text: `TEST DEMO — cancel ${booking.reference}? Reply “yes” or “no”.`,
      body: `Cancel test request ${booking.reference}? No real appointment will be affected.`,
      buttons: [
        { id: 'confirm.yes', title: 'Yes, cancel' },
        { id: 'confirm.no', title: 'No, keep it' },
      ],
    };
  }

  function process({ from, type = 'text', text = '' }) {
    const session = sessionFor(from);
    session.lastInboundAt = now();

    if (['image', 'document', 'video', 'audio', 'sticker'].includes(type)) {
      reset(session);
      const article = ['image', 'audio'].includes(type) ? 'an' : 'a';
      return `TEST DEMO — received ${article} ${type} message. This demo does not download, read, or forward media. Please describe what you need without sending medical records, or contact the clinic directly. Reply “menu” for options.`;
    }
    if (type !== 'text') {
      reset(session);
      return 'TEST DEMO — that message type is not supported yet. Reply “menu” for options.';
    }

    const raw = text.trim();
    const value = raw.toLowerCase().replace(/\s+/g, ' ');
    if (['menu', 'hi', 'hello', 'start', 'help', '0'].includes(value)) {
      reset(session);
      return welcome(bookingsFor(from).length > 0);
    }
    if (/\b(emergency|urgent|chest pain|suicid)/i.test(value)) {
      reset(session);
      return 'This test bot is not monitored for emergencies and cannot give medical advice. If you need urgent help, contact local emergency services or the clinic by phone.';
    }
    if (['book', 'book appointment', 'appointment'].includes(value)) return startBooking(session);
    if (value === 'book selected' && session.draft.lastDoctorId) {
      const doctor = CLINICIANS.find((item) => item.id === session.draft.lastDoctorId);
      return showDoctorSlots(session, doctor);
    }
    if (value === 'more doctors' && session.draft.specialtyId) {
      session.step = 'doctorDetails';
      return clinicianMenu(SPECIALTIES.find((item) => item.id === session.draft.specialtyId));
    }
    if (value === 'more') {
      reset(session);
      return MORE_OPTIONS;
    }
    if (['doctors', 'doctor', 'clinicians'].includes(value)) {
      return startDoctorLookup(session);
    }
    if (['my booking', 'my bookings', 'my request', 'my appointments', 'appointments', 'status'].includes(value)
      || (value === '3' && session.step === 'menu')) return appointmentMenu(from, session);
    if (value === 'change selected' && session.draft.selectedReference) {
      return startChange(from, session, session.draft.selectedReference);
    }
    if (value === 'cancel selected' && session.draft.selectedReference) {
      return startCancel(from, session, session.draft.selectedReference);
    }
    if (['change', 'reschedule', 'change booking'].includes(value)) return startChange(from, session);
    if (['cancel booking', 'cancel appointment'].includes(value)) return startCancel(from, session);
    if (['issue', 'complaint', 'problem'].includes(value)) {
      session.step = 'issueDescription';
      return 'TEST DEMO — briefly describe the issue. Do not include medical records or sensitive details. No clinic staff will see this demo issue.';
    }
    if (['rate', 'rating', 'feedback'].includes(value)) {
      session.step = 'ratingScore';
      return ratingMenu();
    }

    switch (session.step) {
      case 'menu': {
        if (value === '1') return startBooking(session);
        if (value === '2') {
          return startDoctorLookup(session);
        }
        if (value === '4') {
          session.step = 'issueDescription';
          return 'TEST DEMO — briefly describe the issue. No clinic staff will see it. Do not include medical records.';
        }
        if (value === '5') {
          session.step = 'ratingScore';
          return ratingMenu();
        }
        return `I did not understand that.\n${MENU}`;
      }
      case 'selectBooking': {
        if (['next', 'booking:next'].includes(value)) {
          return appointmentMenu(from, session, session.draft.action, session.draft.page + 1);
        }
        if (['previous', 'prev', 'booking:prev'].includes(value)) {
          return appointmentMenu(from, session, session.draft.action, session.draft.page - 1);
        }
        const selectedReference = value.startsWith('booking:')
          ? value.slice('booking:'.length).toUpperCase()
          : session.draft.bookingRefs[choiceIndex(value, session.draft.bookingRefs.length, 'booking')];
        if (!session.draft.bookingRefs.includes(selectedReference)) {
          return appointmentMenu(from, session, session.draft.action, session.draft.page);
        }
        const booking = findOwnBooking(from, selectedReference);
        if (!booking) return appointmentMenu(from, session, session.draft.action, session.draft.page);
        if (session.draft.action === 'change') return startChange(from, session, booking.reference);
        if (session.draft.action === 'cancel') return startCancel(from, session, booking.reference);
        return bookingDetails(session, booking);
      }
      case 'chooseSpecialty': {
        const selectedId = value.startsWith('specialty:') ? value.slice('specialty:'.length) : null;
        const index = selectedId
          ? SPECIALTIES.findIndex((item) => item.id === selectedId)
          : choiceIndex(value, SPECIALTIES.length, 'specialty');
        if (index < 0) return specialtyMenu(session.draft.mode);
        const specialty = SPECIALTIES[index];
        const mode = session.draft.mode;
        session.step = mode === 'booking' ? 'chooseDoctor' : 'doctorDetails';
        session.draft = { specialtyId: specialty.id, mode };
        const menu = clinicianMenu(specialty);
        return {
          kind: 'sequence',
          text: `TEST DEMO — ${specialty.name} guide: ${specialty.pdf}.\n${menu.text}`,
          messages: [
            { kind: 'document', path: pdfPathFor(specialty), filename: specialty.pdf,
              caption: `TEST DEMO — fictional ${specialty.name} clinician guide.` },
            menu,
          ],
        };
      }
      case 'doctorDetails': {
        const specialty = SPECIALTIES.find((item) => item.id === session.draft.specialtyId);
        const doctors = cliniciansFor(specialty.id);
        const index = choiceIndex(value, doctors.length, 'doctor');
        if (index < 0) return clinicianMenu(specialty);
        const doctor = doctors[index];
        session.draft.lastDoctorId = doctor.id;
        return {
          kind: 'buttons', imagePath: doctor.imagePath,
          text: `TEST DEMO — ${doctor.name} (${doctor.specialty}). ${doctor.summary}. Sample times: ${doctor.times.join(' and ')} IST on the next two demo dates. This is a fictional profile; qualifications, fees, and availability are not verified. Reply “book selected” to explore sample slots, or “menu”.`,
          body: `${doctor.name} — ${doctor.summary}.\nSample times: ${doctor.times.join(' and ')} IST. Fictional test profile.`,
          buttons: [
            { id: 'doctor.book', title: 'Book test slot' },
            { id: 'doctor.more', title: 'More doctors' },
            { id: 'doctor.menu', title: 'Main menu' },
          ],
        };
      }
      case 'chooseDoctor': {
        const specialty = SPECIALTIES.find((item) => item.id === session.draft.specialtyId);
        const doctors = cliniciansFor(specialty.id);
        const index = choiceIndex(value, doctors.length, 'doctor');
        if (index < 0) return clinicianMenu(specialty);
        return showDoctorSlots(session, doctors[index]);
      }
      case 'chooseSlot': {
        const index = choiceIndex(value, session.draft.slots.length, 'slot');
        if (index < 0) return slotMenu(session.draft.slots, 'request');
        session.draft.slot = session.draft.slots[index];
        session.step = 'enterAlias';
        return 'TEST DEMO — enter a short test name or alias (2–50 characters). Do not send patient or medical information.';
      }
      case 'enterAlias': {
        if (raw.length < 2 || raw.length > 50 || /[\d@]/.test(raw)) {
          return 'Use a short test name or alias of 2–50 characters, without numbers or an email address.';
        }
        const { clinicianId, slot } = session.draft;
        const doctor = CLINICIANS.find((item) => item.id === clinicianId);
        const available = slotsFor(doctor, now(), bookings).some((candidate) => candidate.id === slot.id);
        if (!available) {
          reset(session);
          return 'TEST DEMO — that sample slot was taken or expired. Reply “book” to choose another.';
        }
        bookingSequence += 1;
        const booking = {
          reference: `TEST-${String(bookingSequence).padStart(4, '0')}`,
          clinicianId, slotId: slot.id, date: slot.date, time: slot.time,
          alias: raw, status: 'active',
        };
        booking.from = from;
        bookings.set(booking.reference, booking);
        reset(session);
        return completionCard(booking, 'Your test request is saved.');
      }
      case 'changeSlot': {
        const index = choiceIndex(value, session.draft.slots.length, 'slot');
        if (index < 0) return slotMenu(session.draft.slots, 'change your test request');
        const slot = session.draft.slots[index];
        const booking = findOwnBooking(from, session.draft.selectedReference);
        if (!booking || booking.status !== 'active') {
          reset(session);
          return 'TEST DEMO — this request is no longer active. Send “hi” to return to the start.';
        }
        const doctor = CLINICIANS.find((item) => item.id === booking.clinicianId);
        const available = slotsFor(doctor, now(), bookings, booking.reference)
          .some((candidate) => candidate.id === slot.id);
        if (!available) {
          reset(session);
          return 'TEST DEMO — that replacement slot is no longer available. Reply “change” to try again.';
        }
        Object.assign(booking, { slotId: slot.id, date: slot.date, time: slot.time });
        reset(session);
        return completionCard(booking, 'Your test request was changed.');
      }
      case 'confirmCancel': {
        if (value === 'no') {
          reset(session);
          return 'TEST DEMO — your test request was kept. Send “hi” to return to the start.';
        }
        if (value !== 'yes') return 'Reply “yes” to cancel the test request or “no” to keep it.';
        const booking = findOwnBooking(from, session.draft.selectedReference);
        if (!booking || booking.status !== 'active') {
          reset(session);
          return 'TEST DEMO — this request is no longer active. Send “hi” to return to the start.';
        }
        booking.status = 'cancelled';
        reset(session);
        return completionCard(booking, 'Your test request was cancelled. No real clinic appointment was affected.');
      }
      case 'issueDescription': {
        if (raw.length < 3 || raw.length > 200) return 'Please use 3–200 characters, with no sensitive or medical details.';
        issueSequence += 1;
        const reference = `TEST-ISSUE-${String(issueSequence).padStart(4, '0')}`;
        issues.push({ from, reference, description: raw });
        reset(session);
        return `TEST DEMO — issue ${reference} saved only in this computer's memory. No clinic staff was notified.`;
      }
      case 'ratingScore': {
        const score = choiceIndex(value, 5, 'rating') + 1;
        if (score < 1) return ratingMenu();
        session.draft.rating = score;
        session.step = 'ratingComment';
        return 'TEST DEMO — optional private comment, or reply “skip”. Do not include medical details.';
      }
      case 'ratingComment': {
        if (raw.length > 200) return 'Please keep the comment under 200 characters, or reply “skip”.';
        ratings.push({ from, score: session.draft.rating, comment: value === 'skip' ? '' : raw });
        reset(session);
        return 'TEST DEMO — private feedback saved in local memory only. No public review was posted.';
      }
      default:
        reset(session);
        return welcome(bookingsFor(from).length > 0);
    }
  }

  function handleResponse(message) {
    if (!message?.from) throw new Error('A sender is required');
    if (message.id && repliesByMessageId.has(message.id)) return repliesByMessageId.get(message.id);
    const reply = process(message);
    const response = typeof reply === 'string' ? { kind: 'text', text: reply } : reply;
    if (message.id) {
      repliesByMessageId.set(message.id, response);
      if (repliesByMessageId.size > 2000) repliesByMessageId.delete(repliesByMessageId.keys().next().value);
    }
    return response;
  }

  function handle(message) {
    return handleResponse(message).text;
  }

  function followup(from) {
    const session = sessions.get(from);
    if (!session?.lastInboundAt || now().getTime() - session.lastInboundAt.getTime() >= 24 * 60 * 60 * 1000) {
      return null;
    }
    return 'TEST DEMO — how did the test booking flow work for you? Reply “rate” or “issue”. This is not a clinic follow-up.';
  }

  return {
    handle, handleResponse, followup,
    getBooking: (from) => bookingsFor(from)[0],
    getBookings: bookingsFor,
    getIssueCount: () => issues.length,
    getRatingCount: () => ratings.length,
  };
}
