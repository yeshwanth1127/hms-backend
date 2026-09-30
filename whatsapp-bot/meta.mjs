import { createHmac, timingSafeEqual } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { basename, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_WELCOME_IMAGE = fileURLToPath(new URL('./welcome.png', import.meta.url));

export function choiceTextForId(id) {
  const choices = {
    'menu.book': 'book', 'menu.doctors': 'doctors', 'menu.more': 'more',
    'menu.status': 'my appointments', 'menu.change': 'change',
    'menu.cancel': 'cancel booking', 'menu.issue': 'issue',
    'menu.feedback': 'feedback', 'confirm.yes': 'yes', 'confirm.no': 'no',
    'doctor.book': 'book selected', 'doctor.more': 'more doctors', 'doctor.menu': 'menu',
    'booking.change': 'change selected', 'booking.cancel': 'cancel selected',
    'booking.menu': 'hi', 'booking.prev': 'booking:prev', 'booking.next': 'booking:next',
    'receipt.visits': 'my appointments', 'receipt.menu': 'hi',
  };
  if (Object.hasOwn(choices, id)) return choices[id];
  const specialty = /^specialty\.([a-z-]+)$/.exec(id ?? '');
  if (specialty) return `specialty:${specialty[1]}`;
  const numbered = /^(doctor|slot|rating)\.([1-9]\d*)$/.exec(id ?? '');
  if (numbered) return `${numbered[1]}:${numbered[2]}`;
  const booking = /^booking\.(TEST-[0-9]+)$/.exec(id ?? '');
  return booking ? `booking:${booking[1]}` : null;
}

export function verifyMetaSignature(rawBody, signatureHeader, appSecret) {
  if (!appSecret || typeof signatureHeader !== 'string' || !signatureHeader.startsWith('sha256=')) return false;
  const suppliedHex = signatureHeader.slice('sha256='.length);
  if (!/^[a-f0-9]{64}$/i.test(suppliedHex)) return false;
  const expected = createHmac('sha256', appSecret).update(rawBody).digest();
  return timingSafeEqual(expected, Buffer.from(suppliedHex, 'hex'));
}

export function incomingMessages(payload, expectedPhoneNumberId) {
  if (payload?.object !== 'whatsapp_business_account') return [];
  return (Array.isArray(payload.entry) ? payload.entry : []).flatMap((entry) => (Array.isArray(entry?.changes) ? entry.changes : []).flatMap((change) => {
    const value = change?.value ?? {};
    if (String(value.metadata?.phone_number_id ?? '') !== String(expectedPhoneNumberId)) return [];
    return (Array.isArray(value.messages) ? value.messages : []).filter((message) =>
      message && typeof message.from === 'string' && /^[0-9]{7,20}$/.test(message.from)
      && typeof message.id === 'string' && message.id.length >= 8 && message.id.length <= 120).map((message) => {
      const mediaType = ['image', 'document', 'video', 'audio', 'sticker'].includes(message.type);
      return {
        id: message.id,
        from: message.from,
        ...(message.interactive?.button_reply?.id || message.interactive?.list_reply?.id || message.button?.payload
          ? { choiceId: message.interactive?.button_reply?.id ?? message.interactive?.list_reply?.id ?? message.button?.payload }
          : {}),
        ...(mediaType ? { mediaId: message[message.type]?.id ?? null,
          mediaMimeType: message[message.type]?.mime_type ?? null,
          filename: message.document?.filename ?? null,
          caption: message[message.type]?.caption ?? null } : {}),
        type: mediaType ? message.type : (
          message.type === 'text' || message.type === 'interactive' || message.type === 'button'
            ? 'text' : message.type
        ),
        text: message.text?.body
          ?? choiceTextForId(message.interactive?.button_reply?.id)
          ?? choiceTextForId(message.interactive?.list_reply?.id)
          ?? choiceTextForId(message.button?.payload)
          ?? message.interactive?.button_reply?.title
          ?? message.interactive?.list_reply?.title
          ?? message.button?.text
          ?? '',
      };
    });
  }));
}

export function createMetaSender({ accessToken, phoneNumberId, graphVersion,
  welcomeImagePath = DEFAULT_WELCOME_IMAGE, fetchImpl = fetch }) {
  if (!accessToken || !/^\d+$/.test(String(phoneNumberId)) || !/^v\d+\.\d+$/.test(graphVersion ?? '')) {
    throw new Error('Meta sender requires an access token, numeric phone-number ID, and Graph API version');
  }
  const url = `https://graph.facebook.com/${graphVersion}/${phoneNumberId}/messages`;
  const mediaIds = new Map();
  const sequenceProgress = new Map();

  async function postJson(payload) {
    const response = await fetchImpl(url, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${accessToken}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) {
      const error = new Error(`Meta message send failed with HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    const receipt = await response.json();
    if (!receipt?.messages?.[0]?.id) throw new Error('Meta accepted a message without a message ID');
    return receipt;
  }

  async function uploadMedia(source) {
    const cacheKey = typeof source === 'string' ? source : `asset:${source.id}`;
    const cached = mediaIds.get(cacheKey);
    if (cached && cached.expiresAt <= Date.now()) mediaIds.delete(cacheKey);
    if (!mediaIds.has(cacheKey)) {
      const pending = (async () => {
        const extension = typeof source === 'string' ? extname(source).toLowerCase() : '';
        const mimeType = typeof source === 'object' ? source.mimeType : extension === '.png' ? 'image/png'
          : ['.jpg', '.jpeg'].includes(extension) ? 'image/jpeg'
            : extension === '.pdf' ? 'application/pdf' : null;
        if (!['image/png', 'image/jpeg', 'application/pdf'].includes(mimeType)) throw new Error('Media must be a PNG, JPEG, or PDF file');
        const bytes = typeof source === 'string' ? await readFile(source) : source.bytes;
        const filename = typeof source === 'string' ? basename(source) : source.filename;
        const form = new FormData();
        form.set('messaging_product', 'whatsapp');
        form.set('type', mimeType);
        form.set('file', new Blob([bytes], { type: mimeType }), filename);
        const response = await fetchImpl(`https://graph.facebook.com/${graphVersion}/${phoneNumberId}/media`, {
          method: 'POST',
          headers: { authorization: `Bearer ${accessToken}` },
          body: form,
          signal: AbortSignal.timeout(30000),
        });
        if (!response.ok) throw new Error(`Meta media upload failed with HTTP ${response.status}`);
        const data = await response.json();
        if (!data.id) throw new Error('Meta media upload returned no media ID');
        return data.id;
      })().catch((error) => { mediaIds.delete(cacheKey); throw error; });
      mediaIds.set(cacheKey, { promise: pending, expiresAt: Date.now() + 6 * 60 * 60 * 1000 });
    }
    return mediaIds.get(cacheKey).promise;
  }

  async function downloadMedia(mediaId, filename) {
    if (!/^[A-Za-z0-9_-]{4,160}$/.test(String(mediaId))) throw new Error('Invalid WhatsApp media ID');
    const metaResponse = await fetchImpl(`https://graph.facebook.com/${graphVersion}/${mediaId}`, {
      headers: { authorization: `Bearer ${accessToken}` }, signal: AbortSignal.timeout(15000), redirect: 'error',
    });
    if (!metaResponse.ok) throw new Error(`Meta media lookup failed with HTTP ${metaResponse.status}`);
    const info = await metaResponse.json();
    if (Number(info.file_size) > 16 * 1024 * 1024) throw new Error('Media exceeds the 16 MB intake limit');
    const mediaUrl = new URL(info.url);
    if (mediaUrl.protocol !== 'https:' || !/(^|\.)(facebook\.com|fbsbx\.com|fbcdn\.net)$/.test(mediaUrl.hostname)) {
      throw new Error('Untrusted WhatsApp media URL');
    }
    const response = await fetchImpl(mediaUrl, {
      headers: { authorization: `Bearer ${accessToken}` }, signal: AbortSignal.timeout(30000), redirect: 'error',
    });
    if (!response.ok) throw new Error(`Meta media download failed with HTTP ${response.status}`);
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16 * 1024 * 1024) { await reader.cancel(); throw new Error('Media exceeds the 16 MB intake limit'); }
      chunks.push(value);
    }
    const mimeType = String(info.mime_type ?? response.headers.get('content-type') ?? '').split(';')[0].toLowerCase();
    const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'application/pdf': 'pdf',
      'audio/ogg': 'ogg', 'audio/mpeg': 'mp3', 'video/mp4': 'mp4' }[mimeType] ?? 'bin';
    return { bytes: Buffer.concat(chunks), mimeType, filename: filename ?? `whatsapp-${mediaId}.${extension}` };
  }

  async function sendText(to, body) {
    return postJson({
        messaging_product: 'whatsapp',
        recipient_type: 'individual',
        to,
        type: 'text',
        text: { preview_url: false, body },
    });
  }

  sendText.sendResponse = async (to, reply, deliveryId) => {
    if (reply.kind === 'text') return sendText(to, reply.text);
    if (reply.kind === 'sequence') {
      let result;
      const start = deliveryId ? (sequenceProgress.get(deliveryId) ?? 0) : 0;
      for (let index = start; index < reply.messages.length; index += 1) {
        result = await sendText.sendResponse(to, reply.messages[index]);
        if (deliveryId) {
          sequenceProgress.set(deliveryId, index + 1);
          if (sequenceProgress.size > 2000) sequenceProgress.delete(sequenceProgress.keys().next().value);
        }
      }
      return result;
    }
    if (reply.kind === 'document') {
      const mediaId = await uploadMedia(reply.media ?? reply.path);
      return postJson({
        messaging_product: 'whatsapp', recipient_type: 'individual', to,
        type: 'document', document: { id: mediaId, filename: reply.filename, caption: reply.caption },
      });
    }
    if (reply.kind === 'image') {
      const mediaId = await uploadMedia(reply.media ?? reply.imagePath);
      return postJson({
        messaging_product: 'whatsapp', recipient_type: 'individual', to,
        type: 'image', image: { id: mediaId, caption: reply.caption },
      });
    }
    const interactive = reply.kind === 'buttons' ? {
      type: 'button',
      body: { text: reply.body },
      action: { buttons: reply.buttons.map(({ id, title }) => ({
        type: 'reply', reply: { id, title },
      })) },
    } : {
      type: 'list',
      body: { text: reply.body },
      action: { button: reply.buttonText, sections: reply.sections },
    };
    const payload = {
      messaging_product: 'whatsapp', recipient_type: 'individual', to,
      type: 'interactive', interactive,
    };
    if (reply.image || reply.imagePath || reply.media) {
      const mediaId = await uploadMedia(reply.media ?? reply.imagePath ?? welcomeImagePath);
      interactive.header = { type: 'image', image: { id: mediaId } };
      try {
        return await postJson(payload);
      } catch (error) {
        if (error.status !== 400) throw error;
        delete interactive.header;
        await postJson({
          messaging_product: 'whatsapp', recipient_type: 'individual', to,
          type: 'image', image: { id: mediaId, caption: reply.imagePath
            ? reply.body : 'Avocado Health — TEST DEMO' },
        });
      }
    }
    return postJson(payload);
  };

  sendText.downloadMedia = downloadMedia;
  sendText.sendTemplate = async (to, name, language, parameters) => postJson({
    messaging_product: 'whatsapp', recipient_type: 'individual', to, type: 'template',
    template: { name, language: { code: language }, components: [{ type: 'body',
      parameters: parameters.map((value) => ({ type: 'text', text: String(value) })) }] },
  });

  return sendText;
}
