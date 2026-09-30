import { BackendError } from './backend-client.mjs';
import { randomBytes } from 'node:crypto';

const PAGE_SIZE = 8;
const MAX_CACHE = 2000;

function asReply(value) { return typeof value === 'string' ? { kind: 'text', text: value } : value; }
function list(body, buttonText, rows, title = 'Choose one') {
  return { kind: 'list', text: body, body, buttonText, sections: [{ title, rows }] };
}
function buttons(body, options, imagePath) {
  return { kind: 'buttons', text: body, body, buttons: options, ...(imagePath ? { imagePath } : {}) };
}
function dateInZone(value, zone) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(value);
}
function daysFrom(dateString, offset) {
  const day = new Date(`${dateString}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + offset);
  return day.toISOString().slice(0, 10);
}
function when(value, zone) {
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: zone, weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(new Date(value));
}
function choice(message, prefix, options) {
  const id = message.choiceId;
  if (id?.startsWith(`${prefix}.`)) return id.slice(prefix.length + 1);
  const match = /^\d+$/.exec(message.text.trim());
  if (match) return options[Number(match[0]) - 1] ?? null;
  return null;
}
function idem(operation, message) {
  return `${operation}:${message.id}`.slice(0, 120);
}

export function createLiveEngine({ backend, downloadMedia, welcomeImagePath,
  clinicReady = false, requireReference = false, now = () => new Date() }) {
  if (!backend) throw new Error('Live engine requires a backend client');
  const sessions = new Map();
  const replies = new Map();
  const sessionFor = (sender) => {
    if (!sessions.has(sender)) sessions.set(sender, { step: 'menu', draft: {} });
    return sessions.get(sender);
  };
  const reset = (session) => { session.step = 'menu'; session.draft = {}; };
  const confirmId = (session, action) => `confirm.${action}.${session.draft.confirmToken}`;
  const beginConfirmation = (session) => {
    session.draft.confirmToken = randomBytes(12).toString('hex');
    session.draft.confirmExpiresAt = new Date(now().getTime() + 10 * 60 * 1000).toISOString();
  };
  const confirmationExpired = (session) => !session.draft.confirmExpiresAt
    || new Date(session.draft.confirmExpiresAt).getTime() <= now().getTime();
  const referenceRecent = (session) => {
    const age = now().getTime() - new Date(session.draft.verifiedAt ?? 0).getTime();
    return age >= 0 && age < 30 * 60 * 1000;
  };
  const confirmed = (session, message, action, fallback) =>
    message.choiceId === confirmId(session, action) || (!clinicReady && message.text?.trim().toLowerCase() === fallback);
  const pilotPrefix = clinicReady ? '' : 'LOCAL TEST — records in this backend are not a confirmed clinic visit.\n';

  async function hydrateReply(reply) {
    if (reply?.kind === 'sequence') return { ...reply, messages: await Promise.all(reply.messages.map(hydrateReply)) };
    if (reply?.media?.id && !reply.media.bytes) {
      const asset = await backend.asset(reply.media.id);
      return { ...reply, media: { ...reply.media, bytes: asset.bytes } };
    }
    return reply;
  }

  function forStorage(reply) {
    return JSON.parse(JSON.stringify(reply, (key, value) => key === 'bytes' ? undefined : value));
  }

  async function welcome(sender, session) {
    reset(session);
    const visits = requireReference ? [] : await backend.appointments(sender, 1);
    return buttons(`${pilotPrefix}Welcome to Avocado Health. What can we help you with today?\nFor urgent medical needs, call your clinic or local emergency service.`, [
      { id: 'menu.book', title: 'Book a visit' },
      requireReference ? { id: 'menu.status', title: 'Open a visit' }
        : visits.length ? { id: 'menu.status', title: 'My visits' } : { id: 'menu.doctors', title: 'Find a doctor' },
      { id: 'menu.more', title: 'More options' },
    ], welcomeImagePath);
  }

  async function specialties(session, mode = 'booking') {
    const catalogue = await backend.catalogue();
    session.step = 'specialty';
    session.draft = { mode, catalogue };
    const values = catalogue.departments.slice(0, 10);
    return list('Which specialty would you like?', 'Choose specialty', values.map((item) => ({
      id: `specialty.${item.slug}`, title: item.name.slice(0, 24), description: item.tagline?.slice(0, 72),
    })), 'Specialties');
  }

  function branches(session) {
    const values = session.draft.catalogue.branches.filter((item) => !item.is_virtual).slice(0, 10);
    session.step = 'branch';
    return list('Choose a clinic location.', 'Choose clinic', values.map((item) => ({
      id: `branch.${item.slug}`, title: item.name.slice(0, 24), description: item.area.slice(0, 72),
    })), 'Clinics');
  }

  async function doctorMenu(session) {
    const { department, branch } = session.draft;
    const doctors = await backend.doctors(department.slug, branch.slug);
    session.draft.doctors = doctors.slice(0, 10);
    session.step = 'doctor';
    if (!doctors.length) return `No doctors are listed for ${department.name} at ${branch.name}. Send “hi” to start again.`;
    return list(`Choose a doctor in ${department.name} at ${branch.name}.`, 'View doctors',
      session.draft.doctors.map((item) => ({ id: `doctor.${item.id}`, title: item.name.slice(0, 24), description: item.title.slice(0, 72) })),
      'Doctors');
  }

  async function slotMenu(session, doctor, action = 'booking', currentStart) {
    const zone = session.draft.branch.timezone;
    const today = dateInZone(now(), zone);
    const result = await backend.availability(doctor.id, session.draft.branch.id, today, daysFrom(today, 7));
    const slots = result.slots.filter((slot) => slot.starts_at !== currentStart).slice(0, 10);
    session.draft.slots = slots;
    session.draft.doctor = doctor;
    session.step = action === 'reschedule' ? 'replacementSlot' : 'slot';
    if (!slots.length) return `No available times were returned for ${doctor.name} at ${session.draft.branch.name}. Send “hi” to start again.`;
    return list(`Choose an available time for ${doctor.name}. Times shown in ${zone}.`, 'Choose time',
      slots.map((slot, index) => ({ id: `slot.${index + 1}`, title: when(slot.starts_at, zone).slice(0, 24), description: session.draft.branch.name.slice(0, 72) })),
      'Available times');
  }

  function appointmentSummary(item) {
    return `${clinicReady ? '' : 'LOCAL TEST RECORD\n'}${item.doctor_name}\n${when(item.reservation.starts_at, item.timezone)} · ${item.branch_name}\nReference: ${item.confirmation_code}\nStatus: ${item.status}`;
  }

  async function visits(sender, session, page = 0) {
    const requested = Math.max(0, page);
    let result = await backend.appointmentsPage(sender, PAGE_SIZE, requested * PAGE_SIZE);
    if (!result.total) { reset(session); return 'No WhatsApp appointments found. Send “hi” to start a booking.'; }
    const totalPages = Math.ceil(result.total / PAGE_SIZE);
    const current = Math.min(requested, totalPages - 1);
    if (current !== requested) result = await backend.appointmentsPage(sender, PAGE_SIZE, current * PAGE_SIZE);
    const visible = result.items;
    session.step = 'visits';
    session.draft = { page: current, visible };
    const rows = visible.map((item) => ({ id: `booking.${item.id}`, title: item.confirmation_code.slice(0, 24),
      description: `${when(item.reservation.starts_at, item.timezone)} · ${item.status}`.slice(0, 72) }));
    if (current > 0) rows.push({ id: 'booking.prev', title: 'Previous page' });
    if (current < totalPages - 1) rows.push({ id: 'booking.next', title: 'Next page' });
    return list(`${clinicReady ? 'Your WhatsApp appointments' : 'Local test appointments'} · page ${current + 1}/${totalPages}. Choose one for details.`, 'My visits', rows, 'Appointments');
  }

  async function detail(sender, session, id) {
    const item = await backend.appointment(id, sender);
    const verifiedAt = session.draft.verifiedAt;
    session.step = 'detail';
    session.draft = { appointment: item, ...(verifiedAt ? { verifiedAt } : {}) };
    return buttons(`${appointmentSummary(item)}\nSend “hi” to return to the start.`, item.status === 'confirmed' ? [
      { id: 'booking.change', title: 'Change slot' },
      { id: 'booking.cancel', title: 'Cancel visit' },
      { id: 'booking.menu', title: 'Main menu' },
    ] : [{ id: 'receipt.visits', title: requireReference ? 'Open a visit' : 'My visits' },
      { id: 'booking.menu', title: 'Main menu' }]);
  }

  async function startChange(session) {
    const item = session.draft.appointment;
    const catalogue = await backend.catalogue();
    const branch = catalogue.branches.find((value) => value.id === item.reservation.branch_id);
    const doctor = (await backend.doctors()).find((value) => value.id === item.reservation.doctor_id);
    if (!branch || !doctor) return 'This appointment cannot be changed in chat. Please contact the clinic.';
    session.draft = { appointment: item, branch, doctor,
      ...(session.draft.verifiedAt ? { verifiedAt: session.draft.verifiedAt } : {}) };
    return slotMenu(session, doctor, 'reschedule', item.reservation.starts_at);
  }

  async function process(message) {
    const sender = message.from;
    const session = sessionFor(sender);
    const raw = String(message.text ?? '').trim();
    const value = raw.toLowerCase().replace(/\s+/g, ' ');
    const id = message.choiceId;

    if (['image', 'document', 'video', 'audio'].includes(message.type)) {
      if (!message.mediaId || !downloadMedia) return 'I could not receive this attachment. Please try again or contact the clinic.';
      let media;
      try {
        media = await downloadMedia(message.mediaId, message.filename);
      } catch (error) {
        if (/Media exceeds|Invalid WhatsApp media ID|Untrusted WhatsApp media URL/.test(error.message)) {
          return 'That attachment could not be accepted. Please send a supported file under 16 MB or contact the clinic.';
        }
        throw error;
      }
      const intake = await backend.case({ sender_id: sender, kind: 'issue',
        description: message.caption?.trim() || `${message.type} attachment sent via WhatsApp`,
        idempotency_key: idem('media', message) });
      try {
        await backend.attach(intake.id, sender, message.id, media);
      } catch (error) {
        if (error instanceof BackendError && [413, 415].includes(error.status)) {
          reset(session);
          return `Case ${intake.id.slice(0, 8)} was recorded, but the file could not be attached. Please contact the clinic or send a supported file under 16 MB.`;
        }
        throw error;
      }
      reset(session);
      return `Your attachment was received for staff review. Case ${intake.id.slice(0, 8)}. Please do not use WhatsApp for emergencies.`;
    }
    if (message.type !== 'text') return 'That message type is not supported. Send “hi” for the menu.';
    if (['hi', 'hello', 'start', 'menu', 'help', '0'].includes(value) || id === 'booking.menu' || id === 'receipt.menu') return welcome(sender, session);
    if (requireReference && ['visits', 'detail', 'confirmCancel', 'replacementSlot', 'confirmReschedule'].includes(session.step)
        && !referenceRecent(session)) {
      reset(session);
      return 'For privacy, this visit session expired. Choose Open a visit and enter its booking reference again.';
    }
    if (/\b(emergency|urgent|chest pain|suicid)/i.test(value)) return 'This chat is not monitored for emergencies. Contact local emergency services or call the clinic now.';
    if (['book', 'book appointment'].includes(value) || id === 'menu.book') return specialties(session, 'booking');
    if (['doctors', 'doctor'].includes(value) || id === 'menu.doctors') return specialties(session, 'details');
    if (['my appointments', 'my visits', 'appointments'].includes(value) || id === 'menu.status' || id === 'receipt.visits') {
      if (requireReference) {
        session.step = 'visitReference';
        session.draft = {};
        return 'Enter the booking reference from your confirmation message (AVO-...).';
      }
      return visits(sender, session);
    }
    if (id === 'menu.more' || value === 'more') return list('Choose another service.', 'More options', [
      { id: 'menu.status', title: requireReference ? 'Open a visit' : 'My visits' },
      { id: 'menu.doctors', title: 'Find a doctor' },
      { id: 'menu.issue', title: 'Raise an issue' }, { id: 'menu.feedback', title: 'Leave feedback' },
    ], 'Services');
    if (id === 'menu.issue' || value === 'issue') { session.step = 'issue'; session.draft = {}; return 'Briefly describe the issue. A staff case will be created. For emergencies, call the clinic.'; }
    if (id === 'menu.feedback' || value === 'rate' || value === 'feedback') {
      session.step = 'rating'; session.draft = {};
      return list('Choose a private rating from 1 to 5.', 'Choose rating', [1, 2, 3, 4, 5].map((n) => ({ id: `rating.${n}`, title: `${n} / 5` })), 'Rating');
    }
    if (session.step === 'visitReference') {
      const code = raw.toUpperCase();
      if (!/^AVO-[0-9A-F]{8}([0-9A-F]{8})?$/.test(code)) return 'Please enter the full AVO- booking reference.';
      try {
        const item = await backend.appointmentByCode(code, sender);
        session.draft = { verifiedAt: now().toISOString() };
        return detail(sender, session, item.id);
      } catch (error) {
        if (error instanceof BackendError && error.status === 404) return 'No visit was found for that reference. Check the code or contact the clinic.';
        throw error;
      }
    }
    if (session.step === 'specialty') {
      const values = session.draft.catalogue.departments.slice(0, 10);
      const selected = choice(message, 'specialty', values.map((item) => item.slug));
      const department = values.find((item) => item.slug === selected);
      if (!department) return specialties(session, session.draft.mode);
      session.draft.department = department;
      const branchReply = branches(session);
      if (!department.guide_asset_id) return { kind: 'sequence', text: branchReply.text,
        messages: [asReply(`No specialty PDF has been uploaded for ${department.name} yet.`), branchReply] };
      const asset = await backend.asset(department.guide_asset_id);
      return { kind: 'sequence', text: branchReply.text, messages: [
        { kind: 'document', media: { id: department.guide_asset_id, bytes: asset.bytes,
          mimeType: asset.mimeType, filename: `${department.slug}.pdf` }, filename: `${department.slug}.pdf`,
          caption: `${department.name} doctor guide` }, branchReply,
      ] };
    }
    if (session.step === 'branch') {
      const values = session.draft.catalogue.branches.filter((item) => !item.is_virtual).slice(0, 10);
      const selected = choice(message, 'branch', values.map((item) => item.slug));
      const branch = values.find((item) => item.slug === selected);
      if (!branch) return branches(session);
      session.draft.branch = branch;
      return doctorMenu(session);
    }
    if (session.step === 'doctor') {
      const doctors = session.draft.doctors;
      const selected = choice(message, 'doctor', doctors.map((item) => item.id));
      const doctor = doctors.find((item) => item.id === selected);
      if (!doctor) return doctorMenu(session);
      const slotReply = await slotMenu(session, doctor);
      if (!doctor.photo_asset_id) return { kind: 'sequence', text: slotReply.text ?? slotReply,
        messages: [asReply(`${doctor.name}\n${doctor.title}\n${doctor.bio}`), asReply(slotReply)] };
      const asset = await backend.asset(doctor.photo_asset_id);
      return { kind: 'sequence', text: slotReply.text ?? slotReply, messages: [
        { kind: 'image', media: { id: doctor.photo_asset_id, bytes: asset.bytes,
          mimeType: asset.mimeType, filename: `${doctor.slug}.${asset.mimeType === 'image/png' ? 'png' : 'jpg'}` },
          caption: `${doctor.name}\n${doctor.title}\n${doctor.bio}`.slice(0, 1000) }, asReply(slotReply),
      ] };
    }
    if (session.step === 'slot' || session.step === 'replacementSlot') {
      const selected = choice(message, 'slot', session.draft.slots.map((_, index) => String(index + 1)));
      const slot = session.draft.slots[Number(selected) - 1];
      if (!slot) return slotMenu(session, session.draft.doctor, session.step === 'replacementSlot' ? 'reschedule' : 'booking');
      try {
        const hold = await backend.hold({ sender_id: sender, ...slot, idempotency_key: idem('hold', message) });
        session.draft.hold = hold;
        session.draft.slot = slot;
        if (session.step === 'replacementSlot') {
          session.step = 'confirmReschedule';
          beginConfirmation(session);
          return buttons(`Move ${session.draft.appointment.confirmation_code} to ${when(slot.starts_at, session.draft.branch.timezone)}?`, [
            { id: confirmId(session, 'yes'), title: 'Yes, change' },
            { id: confirmId(session, 'no'), title: 'Keep old time' },
          ]);
        }
        session.step = 'name';
        return 'Please reply with the patient name for this appointment. The selected time is held briefly.';
      } catch (error) {
        if (error instanceof BackendError && error.status === 409) return 'That time has just become unavailable. Choose another time or send “hi” to restart.';
        throw error;
      }
    }
    if (session.step === 'name') {
      if (raw.length < 2 || raw.length > 160) return 'Please send a name between 2 and 160 characters.';
      session.draft.patientName = raw;
      session.step = 'confirmBooking';
      beginConfirmation(session);
      return buttons(`Confirm ${session.draft.doctor.name} at ${when(session.draft.slot.starts_at, session.draft.branch.timezone)} for ${raw}? Choose whether you want an appointment reminder.`, [
        { id: confirmId(session, 'reminders'), title: 'Book + reminder' },
        { id: confirmId(session, 'only'), title: 'Book only' },
        { id: confirmId(session, 'no'), title: 'Do not book' },
      ]);
    }
    if (session.step === 'confirmBooking') {
      if (confirmationExpired(session)) { reset(session); return 'That booking confirmation expired. Send “hi” to choose a new time.'; }
      if (confirmed(session, message, 'no', 'no')) {
        await backend.releaseHold(session.draft.hold.id, sender);
        reset(session);
        return 'No appointment was created. Send “hi” to return to the start.';
      }
      const reminders = confirmed(session, message, 'reminders', 'reminder');
      if (!(reminders || confirmed(session, message, 'only', 'yes'))) return 'Please choose a current booking confirmation button.';
      try {
        const item = await backend.book({ sender_id: sender, hold_id: session.draft.hold.id,
          patient_name: session.draft.patientName, consent_to_reminders: reminders,
          idempotency_key: idem('book', message) });
        reset(session);
        return buttons(`${pilotPrefix}Appointment ${clinicReady ? 'confirmed' : 'recorded for testing'}.\n${appointmentSummary(item)}\nSend “hi” to return to the start.`, [
          { id: 'receipt.visits', title: requireReference ? 'Open a visit' : 'My visits' },
          { id: 'receipt.menu', title: 'Main menu' },
        ]);
      } catch (error) {
        if (error instanceof BackendError && error.status === 409) {
          reset(session);
          return 'That hold expired or the booking conflicted. No confirmation was issued. Send “hi” to choose another time.';
        }
        throw error;
      }
    }
    if (session.step === 'visits') {
      if (id === 'booking.next') return visits(sender, session, session.draft.page + 1);
      if (id === 'booking.prev') return visits(sender, session, session.draft.page - 1);
      const selected = choice(message, 'booking', session.draft.visible.map((item) => item.id));
      if (!session.draft.visible.some((item) => item.id === selected)) return visits(sender, session, session.draft.page);
      return detail(sender, session, selected);
    }
    if (session.step === 'detail') {
      if (id === 'booking.change' || value === 'change') return startChange(session);
      if (id === 'booking.cancel' || value === 'cancel') {
        session.step = 'confirmCancel';
        beginConfirmation(session);
        return buttons(`Cancel ${session.draft.appointment.confirmation_code}?`, [
          { id: confirmId(session, 'yes'), title: 'Yes, cancel' },
          { id: confirmId(session, 'no'), title: 'Keep visit' },
        ]);
      }
      return detail(sender, session, session.draft.appointment.id);
    }
    if (session.step === 'confirmCancel') {
      if (confirmationExpired(session)) { reset(session); return 'That cancellation choice expired. Send “hi” to open the appointment again.'; }
      if (confirmed(session, message, 'no', 'no')) return detail(sender, session, session.draft.appointment.id);
      if (!confirmed(session, message, 'yes', 'yes')) return 'Choose a current cancellation button or Keep visit.';
      const item = await backend.cancel(session.draft.appointment.id, { sender_id: sender, reason: 'Patient requested via WhatsApp' });
      reset(session);
      return buttons(`${pilotPrefix}Appointment cancelled.\n${appointmentSummary(item)}\nSend “hi” to start again.`, [
        { id: 'receipt.visits', title: requireReference ? 'Open a visit' : 'My visits' },
        { id: 'receipt.menu', title: 'Main menu' },
      ]);
    }
    if (session.step === 'confirmReschedule') {
      if (confirmationExpired(session)) { reset(session); return 'That change choice expired. Your original appointment remains in place. Send “hi” to start again.'; }
      if (confirmed(session, message, 'no', 'no')) {
        await backend.releaseHold(session.draft.hold.id, sender);
        return detail(sender, session, session.draft.appointment.id);
      }
      if (!confirmed(session, message, 'yes', 'yes')) return 'Choose a current change button or Keep old time.';
      try {
        const item = await backend.reschedule(session.draft.appointment.id, { sender_id: sender,
          new_hold_id: session.draft.hold.id, idempotency_key: idem('move', message) });
        reset(session);
        return buttons(`${pilotPrefix}Appointment changed.\n${appointmentSummary(item)}\nSend “hi” to start again.`, [
          { id: 'receipt.visits', title: requireReference ? 'Open a visit' : 'My visits' },
          { id: 'receipt.menu', title: 'Main menu' },
        ]);
      } catch (error) {
        if (error instanceof BackendError && error.status === 409) {
          reset(session);
          return 'The replacement time expired or conflicted. Your old appointment remains unchanged. Send “hi” to try again.';
        }
        throw error;
      }
    }
    if (session.step === 'issue') {
      if (raw.length < 3 || raw.length > 2000) return 'Please describe the issue in 3–2000 characters.';
      const item = await backend.case({ sender_id: sender, kind: 'issue', description: raw,
        idempotency_key: idem('case', message) });
      reset(session);
      return `Your issue was recorded for staff review. Case ${item.id.slice(0, 8)}. Send “hi” for the menu.`;
    }
    if (session.step === 'rating') {
      const selected = choice(message, 'rating', ['1', '2', '3', '4', '5']);
      const score = Number(selected);
      if (!Number.isInteger(score) || score < 1 || score > 5) return 'Choose a rating from 1 to 5.';
      session.step = 'ratingComment';
      session.draft = { rating: score };
      return 'Add an optional private comment, or reply “skip”.';
    }
    if (session.step === 'ratingComment') {
      if (raw.length > 2000) return 'Please keep the comment under 2000 characters.';
      const item = await backend.case({ sender_id: sender, kind: 'feedback',
        rating: session.draft.rating, description: value === 'skip' ? `Rating ${session.draft.rating}/5` : raw,
        idempotency_key: idem('feedback', message) });
      reset(session);
      return `Thank you. Your private feedback was recorded as case ${item.id.slice(0, 8)}. Send “hi” for the menu.`;
    }
    return welcome(sender, session);
  }

  return {
    async handleResponse(message) {
      if (!message?.from || !message?.id) throw new Error('Live messages require sender and ID');
      if (replies.has(message.id)) return replies.get(message.id);
      if (!sessions.has(message.from) && typeof backend.loadConversation === 'function') {
        const saved = await backend.loadConversation(message.from);
        sessions.set(message.from, saved.state ?? { step: 'menu', draft: {} });
        if (saved.last_message_id === message.id && saved.last_reply) {
          const prior = await hydrateReply(saved.last_reply);
          replies.set(message.id, prior);
          return prior;
        }
      }
      const session = sessionFor(message.from);
      const before = structuredClone(session);
      try {
        const response = asReply(await process(message));
        if (typeof backend.saveConversation === 'function') {
          await backend.saveConversation(message.from, {
            state: session, last_message_id: message.id, last_reply: forStorage(response),
          });
        }
        replies.set(message.id, response);
        if (replies.size > MAX_CACHE) replies.delete(replies.keys().next().value);
        return response;
      } catch (error) {
        sessions.set(message.from, before);
        throw error;
      }
    },
  };
}
