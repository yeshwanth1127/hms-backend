import { BackendError } from './backend-client.mjs';
import { randomBytes } from 'node:crypto';

const PAGE_SIZE = 8;
const MAX_CACHE = 2000;

function asReply(value) { return typeof value === 'string' ? { kind: 'text', text: value } : value; }
function list(body, buttonText, rows, title = 'Choose one') {
  body = body.slice(0, 1024);
  return { kind: 'list', text: body, body, buttonText, sections: [{ title, rows }] };
}
function buttons(body, options, imagePath) {
  body = body.slice(0, 1024);
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
    await abandon(sender, session);
    reset(session);
    const visits = requireReference ? [] : await backend.appointments(sender, 1);
    return buttons(`${pilotPrefix}Welcome to Avocado Health. What can we help you with today?\nFor urgent medical needs, call your clinic or local emergency service.`, [
      { id: 'menu.book', title: 'Book a visit' },
      requireReference ? { id: 'menu.status', title: 'Open a visit' }
        : visits.length ? { id: 'menu.status', title: 'My visits' } : { id: 'menu.doctors', title: 'Find a doctor' },
      { id: 'menu.more', title: 'More options' },
    ], welcomeImagePath);
  }

  function pageRows(values, prefix, page, render, extra = []) {
    const size = 7, current = Math.max(0, Math.min(page, Math.max(0, Math.ceil(values.length / size) - 1)));
    const rows = values.slice(current * size, (current + 1) * size).map(render);
    if (current > 0) rows.push({ id: `page.${prefix}.${current - 1}`, title: 'Previous page' });
    if ((current + 1) * size < values.length) rows.push({ id: `page.${prefix}.${current + 1}`, title: 'More options' });
    rows.push(...extra);
    return { rows, current };
  }
  async function abandon(sender, session) {
    if (session.draft.hold) await backend.releaseHold(session.draft.hold.id, sender);
    delete session.draft.hold;
  }
  async function preferences(sender, session) {
    const prefs = await backend.preferences(sender);
    session.step = 'preferences';
    return list(`Message preferences\nVisit reminders and follow-ups: ${prefs.service_messages && !prefs.stopped_all ? 'on' : 'off'}\nClinic offers: ${prefs.marketing && !prefs.stopped_all ? 'on' : 'off'}\nVisit messages require reminder consent on that booking. Offers are optional. Send STOP to stop all proactive messages, or STOP OFFERS for offers only.`, 'Preferences', [
      { id: `prefs.service.${prefs.service_messages && !prefs.stopped_all ? 'off' : 'on'}`, title: prefs.service_messages && !prefs.stopped_all ? 'Turn visit messages off' : 'Allow visit messages', description: 'Reminders and clinic follow-ups; no medical advice' },
      { id: `prefs.marketing.${prefs.marketing && !prefs.stopped_all ? 'off' : 'on'}`, title: prefs.marketing && !prefs.stopped_all ? 'Turn offers off' : 'Allow clinic offers', description: 'Optional clinic news and offers; withdraw anytime' },
      { id: 'prefs.branch', title: 'Preferred clinic' }, { id: 'prefs.interest', title: 'Offer interests' },
      { id: 'prefs.language', title: 'Outreach language', description: 'Booking chat currently uses English' },
      { id: 'receipt.menu', title: 'Main menu' },
    ], 'Your choices');
  }
  async function preferenceChoices(session, field, page = 0) {
    const catalogue = await backend.catalogue();
    session.step = `preference${field}`;
    const choices = field === 'branch' ? catalogue.branches.filter(b => !b.is_virtual) : catalogue.departments;
    const result = pageRows(choices, `preference${field}`, page, item => ({ id: `prefs.set${field}.${field === 'branch' ? item.id : item.slug}`, title: item.name.slice(0, 24) }), [{ id: `prefs.set${field}.all`, title: field === 'branch' ? 'All clinics' : 'All specialties' }]);
    return list(field === 'branch' ? 'Which clinic should your offers cover?' : 'Choose an offer interest, or all specialties. Consent stays unchanged.', 'Choose preference', result.rows, 'Offer preferences');
  }
  async function reception(sender, session, message) {
    await abandon(sender, session);
    const item = await backend.reception({ sender_id: sender, source_message_id: message.id,
      text: `Reception request${session.draft.doctor ? ` for ${session.draft.doctor.name}` : ''}` });
    reset(session);
    const info = (await backend.preferences(sender)).reception;
    return buttons(`Your reception request is recorded. Case ${item.case_id.slice(0, 8)}.\n${info.hours}\n${info.response}${info.phone ? `\nCall: ${info.phone}` : ''}\nThe bot is paused while reception helps you. Send your question now. Choose Resume bot when you want to book again. This chat is not for emergencies.`, [
      { id: 'reception.resume', title: 'Resume bot' }, { id: 'menu.preferences', title: 'Message preferences' },
    ]);
  }
  async function specialties(session, mode = 'booking', page = 0) {
    const catalogue = session.draft.catalogue ?? await backend.catalogue();
    session.step = 'specialty';
    session.draft = { mode, catalogue };
    const result = pageRows(catalogue.departments, 'specialty', page, item => ({
      id: `specialty.${item.slug}`, title: item.name.slice(0, 24), description: item.tagline?.slice(0, 72),
    }), [{ id: 'nav.back', title: 'Back to start' }]);
    session.draft.specialtyPage = result.current;
    return list('Which specialty would you like?', 'Choose specialty', result.rows, 'Specialties');
  }
  function branches(session, page = 0) {
    const values = session.draft.catalogue.branches.filter(item => !item.is_virtual);
    session.step = 'branch';
    const result = pageRows(values, 'branch', page, item => ({ id: `branch.${item.slug}`, title: item.name.slice(0, 24), description: item.area.slice(0, 72) }), [{ id: 'nav.back', title: 'Back to specialties' }]);
    session.draft.branchPage = result.current;
    return list('Choose a clinic location.', 'Choose clinic', result.rows, 'Clinics');
  }
  async function doctorMenu(session, page = 0) {
    const { department, branch } = session.draft;
    const doctors = await backend.doctors(department.slug, branch.slug);
    session.draft.doctors = doctors;
    session.step = 'doctor';
    if (!doctors.length) return buttons(`No doctors are listed for ${department.name} at ${branch.name}. Reception can help you find another option.`, [{ id: 'nav.back', title: 'Other clinic' }, { id: 'menu.reception', title: 'Ask reception' }]);
    const result = pageRows(doctors, 'doctor', page, item => ({ id: `doctor.${item.id}`, title: item.name.slice(0, 24), description: `${item.title} · ₹${item.consultation_fee}`.slice(0, 72) }), [{ id: 'nav.back', title: 'Other clinic' }]);
    session.draft.doctorPage = result.current;
    return list(`Choose a doctor in ${department.name} at ${branch.name}.`, 'View doctors', result.rows, 'Doctors');
  }
  async function slotMenu(session, doctor, action = 'booking', currentStart, day, page = 0) {
    const zone = session.draft.branch.timezone;
    const today = dateInZone(now(), zone);
    const result = await backend.availability(doctor.id, session.draft.branch.id, day ?? today, day ?? daysFrom(today, 30));
    const available = result.slots.filter(slot => slot.starts_at !== currentStart);
    const chosenDay = day ?? (available[0] ? dateInZone(new Date(available[0].starts_at), zone) : today);
    const slots = available.filter(slot => dateInZone(new Date(slot.starts_at), zone) === chosenDay);
    Object.assign(session.draft, { slots, doctor, chosenDay, slotAction: action, currentStart, slotToken: randomBytes(8).toString('hex') });
    session.step = action === 'reschedule' ? 'replacementSlot' : 'slot';
    if (!slots.length) return buttons(`No available times for ${doctor.name} on ${chosenDay}. A reception request does not reserve a visit.`, [
      { id: 'slots.date', title: 'Choose another date' }, { id: 'nav.back', title: 'Other doctors' }, { id: 'menu.reception', title: 'Ask reception' },
    ]);
    const resultPage = pageRows(slots, 'slot', page, (slot) => ({ id: `slot.${slots.indexOf(slot) + 1}.${session.draft.slotToken}`, title: when(slot.starts_at, zone).slice(0, 24), description: session.draft.branch.name.slice(0, 72) }), [{ id: 'slots.date', title: 'Choose another date' }]);
    session.draft.slotPage = resultPage.current;
    return list(`Choose a time for ${doctor.name} on ${chosenDay}. Times in ${zone}. Send “back” for other doctors.`, 'Choose time', resultPage.rows, 'Available times');
  }
  function dateMenu(session) {
    session.step = 'chooseDate';
    const today = dateInZone(now(), session.draft.branch.timezone);
    return list('Choose a date, or type YYYY-MM-DD for a date within the next 30 days.', 'Choose date', Array.from({ length: 7 }, (_, n) => ({ id: `date.${daysFrom(today, n)}`, title: daysFrom(today, n) })).concat([{ id: 'nav.back', title: 'Back to times' }]), 'Visit dates');
  }
  function appointmentSummary(item) {
    return `${clinicReady ? '' : 'LOCAL TEST RECORD\n'}${item.doctor_name}\n${when(item.reservation.starts_at, item.timezone)} · ${item.branch_name}\nReference: ${item.confirmation_code}\nStatus: ${item.status}\n${item.address ? `${item.address.slice(0, 180)}\n` : ''}${item.consultation_fee != null ? `Consultation: ₹${item.consultation_fee} · Pay at clinic\n` : ''}${item.directions_url ? `Directions: ${item.directions_url}\n` : ''}${item.arrival_instructions ? `${item.arrival_instructions.slice(0, 180)}\n` : ''}`;
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

    const verification = /^VERIFY WEB ([A-F0-9]{20})$/i.exec(raw);
    if (message.type === 'text' && verification) {
      if (!backend.verifyWebBooking) return 'Website verification is unavailable. Please contact reception.';
      try {
        const result = await backend.verifyWebBooking({ sender_id: sender, code: verification[1].toUpperCase() });
        return result.message;
      } catch (error) {
        if (error instanceof BackendError && [404, 503, 403].includes(error.status)) return 'Verification is unavailable or expired. Return to the clinic website and try again.';
        throw error;
      }
    }
    const prefs = backend.preferences ? await backend.preferences(sender) : null;
    if (message.type === 'text' && (/^(stop|unsubscribe|stop all)$/.test(value) || /^(stop offers|stop marketing)$/.test(value) || id?.startsWith('outreach.stop.'))) {
      if (!backend.changePreferences) return 'Message preferences are unavailable. Please contact the clinic.';
      if (id?.startsWith('outreach.stop.')) {
        try { await backend.engageOutreach(id.slice('outreach.stop.'.length), sender, 'stop'); }
        catch (error) { if (!(error instanceof BackendError && error.status === 404)) throw error; }
      }
      const all = /^(stop|unsubscribe|stop all)$/.test(value);
      await backend.changePreferences(sender, { source_message_id: message.id, ...(all ? { stopped_all: true } : { marketing: false }) });
      return buttons(all ? 'All proactive WhatsApp messages are turned off. You can still message us to book or ask for help.' : 'Clinic offers are turned off. Your visit-message preference is unchanged.', [{ id: 'menu.preferences', title: 'Message preferences' }, { id: 'receipt.menu', title: 'Main menu' }]);
    }
    if (message.type === 'text' && /\b(emergency|urgent|chest pain|suicid)/i.test(value)) return 'This chat is not monitored for emergencies. Contact local emergency services or call the clinic now.';
    if (id === 'menu.preferences' || value === 'preferences') { await abandon(sender, session); return preferences(sender, session); }
    if (id?.startsWith('prefs.') && prefs) {
      const [, field, setting] = id.split('.');
      if (['service', 'marketing'].includes(field) && ['on', 'off'].includes(setting)) {
        await backend.changePreferences(sender, { source_message_id: message.id, [field === 'service' ? 'service_messages' : field]: setting === 'on', ...(setting === 'on' ? { stopped_all: false } : {}) });
        return preferences(sender, session);
      }
      if (field === 'branch') return preferenceChoices(session, 'branch');
      if (field === 'interest') return preferenceChoices(session, 'interest');
      if (field === 'language') return list('Choose a language for approved outreach messages. Booking chat currently uses English.', 'Choose language', ['en', 'hi', 'kn'].map(l => ({ id: `prefs.setlanguage.${l}`, title: ({ en: 'English', hi: 'Hindi', kn: 'Kannada' })[l] })), 'Outreach language');
      if (['setbranch', 'setinterest', 'setlanguage'].includes(field)) {
        const choices = field === 'setbranch' ? { branch_id: setting === 'all' ? '' : setting } : field === 'setinterest' ? { interests: setting === 'all' ? [] : [setting] } : { language: setting };
        await backend.changePreferences(sender, { source_message_id: message.id, ...choices });
        return preferences(sender, session);
      }
    }
    const preferencePage = /^page\.preference(branch|interest)\.(\d+)$/.exec(id ?? '');
    if (preferencePage && session.step === `preference${preferencePage[1]}`) return preferenceChoices(session, preferencePage[1], Number(preferencePage[2]));
    if (id === 'reception.resume' || value === 'resume bot') { await backend.resumeReception(sender); return welcome(sender, session); }
    if (id === 'menu.reception' || value === 'reception' || value === 'human') return reception(sender, session, message);
    if (prefs?.handoff && message.type === 'text') {
      await backend.receptionMessage({ sender_id: sender, source_message_id: message.id, text: raw });
      return { kind: 'silent', text: '' };
    }
    if (id?.startsWith('outreach.')) {
      const [, action, jobId] = id.split('.');
      try { await backend.engageOutreach(jobId, sender); }
      catch (error) { if (error instanceof BackendError && error.status === 404) return 'That action expired. Send “hi” for the menu.'; throw error; }
      if (action === 'feedback') {
        session.step = 'rating'; session.draft = {};
        return list('How was your clinic visit? Choose a private rating.', 'Choose rating', [1, 2, 3, 4, 5].map(n => ({ id: `rating.${n}`, title: `${n} / 5` })), 'Visit feedback');
      }
      if (action === 'contact') return reception(sender, session, message);
      if (action === 'book') { session.outreach = { id: jobId, at: now().toISOString() }; return specialties(session, 'booking'); }
      return welcome(sender, session);
    }
    if (id?.startsWith('receipt.manage.')) {
      if (!session.receipt || id !== `receipt.manage.${session.receipt.token}` || now().getTime() - new Date(session.receipt.at).getTime() >= 30 * 60 * 1000) return 'For privacy, this shortcut expired. Choose Open a visit and enter your booking reference.';
      session.draft = { verifiedAt: now().toISOString() };
      return detail(sender, session, session.receipt.id);
    }
    if (requireReference && ['visits', 'detail', 'confirmCancel', 'replacementSlot', 'confirmReschedule'].includes(session.step)
        && !referenceRecent(session)) {
      reset(session);
      return 'For privacy, this visit session expired. Choose Open a visit and enter its booking reference again.';
    }
    if (id === 'nav.back' || value === 'back') {
      await abandon(sender, session);
      if (session.step === 'branch') return specialties(session, session.draft.mode);
      if (session.step === 'doctor') return branches(session);
      if (['slot', 'name', 'confirmBooking', 'doctorDetail'].includes(session.step)) return doctorMenu(session);
      if (session.step === 'chooseDate') return slotMenu(session, session.draft.doctor, session.draft.slotAction, session.draft.currentStart, session.draft.chosenDay);
      if (['replacementSlot', 'confirmReschedule'].includes(session.step)) return detail(sender, session, session.draft.appointment.id);
      return welcome(sender, session);
    }
    const paging = /^page\.(specialty|branch|doctor|slot)\.(\d+)$/.exec(id ?? '');
    if (paging) {
      const page = Number(paging[2]);
      if (paging[1] === 'specialty' && session.step === 'specialty') return specialties(session, session.draft.mode, page);
      if (paging[1] === 'branch' && session.step === 'branch') return branches(session, page);
      if (paging[1] === 'doctor' && session.step === 'doctor') return doctorMenu(session, page);
      if (paging[1] === 'slot' && ['slot', 'replacementSlot'].includes(session.step)) return slotMenu(session, session.draft.doctor, session.draft.slotAction, session.draft.currentStart, session.draft.chosenDay, page);
      return 'This menu expired. Send “hi” to start again.';
    }
    if (id === 'slots.date' && ['slot', 'replacementSlot'].includes(session.step)) return dateMenu(session);
    if (session.step === 'chooseDate') {
      const day = id?.startsWith('date.') ? id.slice(5) : raw;
      const today = dateInZone(now(), session.draft.branch.timezone);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(Date.parse(`${day}T00:00:00Z`)) || new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day || day < today || day > daysFrom(today, 30)) return 'Enter a valid YYYY-MM-DD within the next 30 days, or choose a date from the list.';
      return slotMenu(session, session.draft.doctor, session.draft.slotAction, session.draft.currentStart, day);
    }
    if (session.step === 'doctorDetail') {
      if (id === 'doctor.book') return slotMenu(session, session.draft.doctor);
      return doctorMenu(session);
    }
    if (['image', 'document', 'video', 'audio'].includes(message.type)) {
      await abandon(sender, session);
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
      if (prefs?.handoff) await backend.receptionMessage({ sender_id: sender, source_message_id: message.id, text: message.caption || "Attachment sent for reception" });
      const intake = prefs?.handoff ? { id: prefs.handoff.case_id } : await backend.case({ sender_id: sender, kind: 'issue',
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
      if (prefs?.handoff) return { kind: 'silent', text: '' };
      reset(session);
      return `Your attachment was received for staff review. Case ${intake.id.slice(0, 8)}. Please do not use WhatsApp for emergencies.`;
    }
    if (message.type !== 'text') return 'That message type is not supported. Send “hi” for the menu.';
    if (['hi', 'hello', 'start', 'menu', 'help', '0'].includes(value) || id === 'booking.menu' || id === 'receipt.menu') return welcome(sender, session);
    if (/\b(emergency|urgent|chest pain|suicid)/i.test(value)) return 'This chat is not monitored for emergencies. Contact local emergency services or call the clinic now.';
    if (['book', 'book appointment'].includes(value) || id === 'menu.book') { await abandon(sender, session); return specialties(session, 'booking'); }
    if (['doctors', 'doctor'].includes(value) || id === 'menu.doctors') { await abandon(sender, session); return specialties(session, 'details'); }
    if (['my appointments', 'my visits', 'appointments'].includes(value) || id === 'menu.status' || id === 'receipt.visits') {
      await abandon(sender, session);
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
      { id: 'menu.reception', title: 'Talk to reception' }, { id: 'menu.preferences', title: 'Message preferences' },
    ], 'Services');
    if (id === 'menu.issue' || value === 'issue') { await abandon(sender, session); session.step = 'issue'; session.draft = {}; return 'Briefly describe the issue. A staff case will be created. For emergencies, call the clinic.'; }
    if (id === 'menu.feedback' || value === 'rate' || value === 'feedback') {
      await abandon(sender, session);
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
      const values = session.draft.catalogue.departments;
      const selected = choice(message, 'specialty', values.slice((session.draft.specialtyPage ?? 0) * 7, ((session.draft.specialtyPage ?? 0) + 1) * 7).map((item) => item.slug));
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
      const values = session.draft.catalogue.branches.filter((item) => !item.is_virtual);
      const selected = choice(message, 'branch', values.slice((session.draft.branchPage ?? 0) * 7, ((session.draft.branchPage ?? 0) + 1) * 7).map((item) => item.slug));
      const branch = values.find((item) => item.slug === selected);
      if (!branch) return branches(session);
      session.draft.branch = branch;
      return doctorMenu(session);
    }
    if (session.step === 'doctor') {
      const doctors = session.draft.doctors;
      const selected = choice(message, 'doctor', doctors.slice((session.draft.doctorPage ?? 0) * 7, ((session.draft.doctorPage ?? 0) + 1) * 7).map((item) => item.id));
      const doctor = doctors.find((item) => item.id === selected);
      if (!doctor) return doctorMenu(session);
      session.draft.doctor = doctor;
      const slotReply = session.draft.mode === 'details' ? buttons(`${doctor.name}\n${doctor.title}\nConsultation: ₹${doctor.consultation_fee} · Pay at clinic\n${doctor.bio}`.slice(0, 1000), [{ id: 'doctor.book', title: 'Book this doctor' }, { id: 'nav.back', title: 'Other doctors' }]) : await slotMenu(session, doctor);
      if (session.draft.mode === 'details') session.step = 'doctorDetail';
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
      if (message.choiceId?.startsWith('slot.') && clinicReady && !message.choiceId.endsWith(`.${session.draft.slotToken}`)) return 'That time menu expired. Choose a time from the latest menu, or send “hi” to restart.';
      const selected = choice(message, 'slot', session.draft.slots.slice((session.draft.slotPage ?? 0) * 7, ((session.draft.slotPage ?? 0) + 1) * 7).map((_, index) => String((session.draft.slotPage ?? 0) * 7 + index + 1)))?.split('.')[0];
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
      return buttons(`Patient: ${raw}\nDoctor: ${session.draft.doctor.name}\n${when(session.draft.slot.starts_at, session.draft.branch.timezone)}\n${session.draft.branch.name}${session.draft.branch.address ? `\n${session.draft.branch.address}` : ''}\nConsultation: ₹${session.draft.doctor.consultation_fee} · Pay at clinic. No payment is taken in this chat.\nChoose whether to allow visit reminders and clinic follow-ups. Offers require separate consent.`, [
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
          expected_fee: session.draft.doctor.consultation_fee,
          ...(session.outreach && now().getTime() - new Date(session.outreach.at).getTime() < 30 * 60 * 1000 ? { outreach_id: session.outreach.id } : {}),
          idempotency_key: idem('book', message) });
        reset(session);
        session.receipt = { id: item.id, token: randomBytes(12).toString('hex'), at: now().toISOString() };
        delete session.outreach;
        return buttons(`${pilotPrefix}Appointment ${clinicReady ? 'confirmed' : 'recorded for testing'}.\n${appointmentSummary(item)}\nSend “hi” to return to the start.`, [
          { id: `receipt.manage.${session.receipt.token}`, title: 'Manage this visit' },
          { id: 'receipt.visits', title: requireReference ? 'Open a visit' : 'My visits' },
          { id: 'receipt.menu', title: 'Main menu' },
        ]);
      } catch (error) {
        if (error instanceof BackendError && error.status === 409) {
          reset(session);
          return 'The price or available time changed. No confirmation was issued. Send “hi” to review the current fee and choose a new time.';
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
