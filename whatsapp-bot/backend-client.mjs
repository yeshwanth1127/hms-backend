const PREFIX = '/api/v1/integrations/whatsapp';

export class BackendError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function createBackendClient({ baseUrl, serviceKey, fetchImpl = fetch }) {
  if (!baseUrl || !serviceKey) throw new Error('Live mode requires BACKEND_URL and BACKEND_WHATSAPP_SERVICE_KEY');
  const root = new URL(baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`);

  async function request(method, path, { query, body, form, binary = false } = {}) {
    const url = new URL(`${PREFIX}${path}`, root);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
    const headers = { 'X-Service-Key': serviceKey };
    if (body) headers['content-type'] = 'application/json';
    let response;
    try {
      response = await fetchImpl(url, {
        method, headers, body: body ? JSON.stringify(body) : form,
        signal: AbortSignal.timeout(15000),
      });
    } catch (error) {
      throw new BackendError(503, 'BACKEND_UNAVAILABLE', `Booking service unavailable: ${error.message}`);
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new BackendError(response.status, detail.error?.code ?? 'BACKEND_ERROR',
        detail.error?.message ?? `Booking service returned HTTP ${response.status}`);
    }
    if (binary) {
      return { bytes: Buffer.from(await response.arrayBuffer()), mimeType: response.headers.get('content-type')?.split(';')[0] };
    }
    if (response.status === 204) return null;
    return response.json();
  }

  return {
    loadConversation: (senderId) => request('GET', `/conversations/${encodeURIComponent(senderId)}`),
    saveConversation: (senderId, body) => request('PUT', `/conversations/${encodeURIComponent(senderId)}`, { body }),
    catalogue: () => request('GET', '/catalogue'),
    doctors: (department, branch) => request('GET', '/doctors', { query: { department, branch } }),
    availability: (doctorId, branchId, startDate, endDate, consultationType = 'in_person') => request('GET', '/availability', {
      query: { doctor_id: doctorId, branch_id: branchId, start_date: startDate, end_date: endDate, consultation_type: consultationType },
    }),
    hold: (body) => request('POST', '/slot-holds', { body }),
    releaseHold: (id, senderId) => request('DELETE', `/slot-holds/${encodeURIComponent(id)}`, { query: { sender_id: senderId } }),
    book: (body) => request('POST', '/appointments', { body }),
    appointments: (senderId, limit = 100) => request('GET', '/appointments', { query: { sender_id: senderId, limit } }),
    appointmentsPage: (senderId, limit = 8, offset = 0) => request('GET', '/appointments/page', {
      query: { sender_id: senderId, limit, offset },
    }),
    appointment: (id, senderId) => request('GET', `/appointments/${encodeURIComponent(id)}`, { query: { sender_id: senderId } }),
    appointmentByCode: (code, senderId) => request('GET', `/appointments/by-code/${encodeURIComponent(code)}`, {
      query: { sender_id: senderId },
    }),
    cancel: (id, body) => request('POST', `/appointments/${encodeURIComponent(id)}/cancel`, { body }),
    reschedule: (id, body) => request('POST', `/appointments/${encodeURIComponent(id)}/reschedule`, { body }),
    case: (body) => request('POST', '/cases', { body }),
    async attach(caseId, senderId, messageId, media) {
      const form = new FormData();
      form.set('sender_id', senderId);
      form.set('source_message_id', messageId);
      form.set('file', new Blob([media.bytes], { type: media.mimeType }), media.filename);
      return request('POST', `/cases/${encodeURIComponent(caseId)}/attachments`, { form });
    },
    asset: (id) => request('GET', `/assets/${encodeURIComponent(id)}`, { binary: true }),
    dueReminders: () => request('GET', '/reminders/due'),
    completeReminder: (id, body) => request('POST', `/reminders/${encodeURIComponent(id)}/complete`, { body }),
    enqueueInbound: (message) => request('POST', '/inbound', { body: {
      message_id: message.id, sender_id: message.from, payload: message,
    } }),
    inboundReady: () => request('GET', '/inbound/ready'),
    claimInbound: () => request('POST', '/inbound/claim'),
    markInboundSending: (id, claimToken) => request('POST', `/inbound/${encodeURIComponent(id)}/sending`, {
      body: { claim_token: claimToken },
    }),
    markInboundSent: (id, claimToken) => request('POST', `/inbound/${encodeURIComponent(id)}/sent`, {
      body: { claim_token: claimToken },
    }),
    markInboundFailed: (id, claimToken, error) => request('POST', `/inbound/${encodeURIComponent(id)}/failed`, {
      body: { claim_token: claimToken, error: String(error).slice(0, 240) },
    }),
  };
}
