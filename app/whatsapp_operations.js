(() => {
  const $ = id => document.getElementById(id), base = '/api/v1/admin/whatsapp';
  let previewUrl, previewGeneration = 0;
  let request, inventory, templates = [], assets = [], campaigns = [], config;
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; };
  const report = (text, error = false) => { $('status').textContent = text; $('status').className = error ? 'status error' : 'status'; };
  const json = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const call = (path, body, method = 'POST') => request(base + path, { ...json(body), method });
  const money = paise => `₹${(paise / 100).toFixed(2)}`;
  const busy = async (button, action) => { if (!request) return report('Open the clinic desk first.', true); button.disabled = true; try { await action(); } catch (e) { report(e.message, true); } finally { button.disabled = false; } };
  function button(text, action) { const el = node('button', text); el.type = 'button'; el.addEventListener('click', () => busy(el, action)); return el; }
  function input(label, type = 'text', value = '') { const root = node('label', label), el = node(type === 'textarea' ? 'textarea' : 'input'); if (type !== 'textarea') el.type = type; el.value = value; root.append(el); return { root, el }; }
  function select(label, choices, value) { const root = node('label', label), el = node('select'); el.setAttribute('aria-label', label); for (const [id, text] of choices) { const option = node('option', text); option.value = id; el.append(option); } if (value != null) el.value = value; root.append(el); return { root, el }; }
  function options(target, values, empty) { target.replaceChildren(); if (empty) { const el = node('option', empty); el.value = ''; target.append(el); } for (const [id, label] of values) { const el = node('option', label); el.value = id; target.append(el); } }
  const approved = category => templates.filter(t => t.status === 'APPROVED' && t.spec && (!category || t.category === category));
  const templateLabel = t => `${t.name} · ${t.language} · ${t.category}`;
  const time = value => new Date(value).toLocaleString();
  document.querySelectorAll('[data-pane]').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('[data-pane]').forEach(other => { other.setAttribute('aria-selected', String(other === tab)); $('pane-' + other.dataset.pane).hidden = other !== tab; });
  }));
  async function reception() {
    const rows = await request(base + '/reception');
    $('reception-inbox').replaceChildren(...rows.map(item => {
      const card = node('article', null, 'card desk-form'); card.append(node('span', `${item.status.toUpperCase()} · CASE ${item.case_id.slice(0, 8)}`, 'eyebrow'), node('h3', `+${item.sender_id}`));
      card.append(node('p', item.can_reply ? 'Patient’s 24-hour reply window is open.' : 'Reply window closed. Ask the patient to message again.', 'detail'));
      const actor = input('Staff name', 'text', item.assigned_to ?? ''); actor.el.minLength = 2; actor.el.maxLength = 100;
      const log = node('div', null, 'message-preview'); for (const message of item.messages) log.append(node('p', `${message.direction === 'inbound' ? 'Patient' : message.actor || 'Staff'} · ${time(message.created_at)}\n${message.text}`));
      const text = input('Reply', 'textarea'); text.el.maxLength = 2000;
      const actions = node('div', null, 'actions');
      const staff = () => { if (actor.el.value.trim().length < 2) throw new Error('Enter the staff member’s name.'); return actor.el.value.trim(); };
      actions.append(button('Take conversation', async () => { await call(`/reception/${item.sender_id}`, { status: 'active', assigned_to: staff() }, 'PATCH'); report('Conversation assigned.'); await reception(); }), button('Reply on WhatsApp', async () => { if (!text.el.value.trim()) throw new Error('Enter a reply.'); await call(`/reception/${item.sender_id}/reply`, { actor: staff(), text: text.el.value.trim(), idempotency_key: 'staff-ui:' + crypto.randomUUID() }); report('Reply queued. Check the delivery record for its result.'); await reception(); }), button('Close & resume bot', async () => { await call(`/reception/${item.sender_id}`, { status: 'closed', assigned_to: staff() }, 'PATCH'); report('Reception case closed. The patient can use the bot again.'); await reception(); }));
      actions.children[1].disabled = !item.can_reply; card.append(actor.root, log, text.root, actions); return card;
    }));
    if (!rows.length) $('reception-inbox').append(node('div', 'No waiting reception requests.', 'empty'));
  }
  function currentTemplate() { return templates.find(t => t.id === $('campaign-template').value); }
  function templateChanged(preserve = false) {
    const previous = preserve ? Array.from($('template-parameters').querySelectorAll('input')).map(el => el.value) : [];
    const t = currentTemplate(); $('template-parameters').replaceChildren();
    $('template-help').textContent = t ? `${t.spec.parameters} body fields. Header: ${t.spec.header || 'none'}. Synced ${time(t.synced_at)}.` : 'No supported approved templates. Configure the business account ID and template permissions, then sync.';
    for (let n = 1; n <= (t?.spec.parameters ?? 0); n++) { const value = input(`Template field ${n}`); value.el.name = `parameter-${n}`; value.el.required = true; value.el.maxLength = 200; value.el.value = previous[n - 1] ?? ''; $('template-parameters').append(value.root); }
    options($('campaign-asset'), assets.filter(a => t?.spec.header === 'IMAGE' ? a.mime_type.startsWith('image/') : t?.spec.header === 'DOCUMENT' ? a.mime_type === 'application/pdf' : false).map(a => [a.id, a.filename]), 'No attachment');
    previewMedia();
    if (t?.spec.buttons?.length) $('template-help').textContent += ' Reply actions: ' + t.spec.buttons.map(b => `button ${b.index + 1} → ${b.action}`).join(', ') + '. Verify each action on the test phone.';
    const body = t?.components.find(c => c.type === 'BODY')?.text; $('campaign-preview').textContent = body || 'Choose an approved template.';
  }
  async function previewMedia(assetId) {
    const generation = ++previewGeneration;
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
    const root = $('campaign-media-preview'); root.replaceChildren();
    const selected = assets.find(a => a.id === (typeof assetId === 'string' ? assetId : $('campaign-asset').value));
    if (!selected) return;
    try {
      const blob = await request(base + `/assets/${selected.id}`, { responseType: 'blob' });
      if (generation !== previewGeneration) return;
      previewUrl = URL.createObjectURL(blob);
      if (selected.mime_type.startsWith('image/')) { const image = node('img', null, 'campaign-image'); image.src = previewUrl; image.alt = selected.filename; root.append(image); }
      else { const link = node('a', `Download and review ${selected.filename}`); link.href = previewUrl; link.download = selected.filename; root.append(link); }
    } catch (error) { report(error.message, true); }
  }
  async function refreshAssets() { assets = await request(base + '/campaign-assets'); templateChanged(true); }
  const zone = $('campaign-drop'), file = $('campaign-file');
  zone.addEventListener('click', () => file.click()); zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } });
  async function upload(file) { if (!request || !file) return; try { report('Uploading campaign media…'); const form = new FormData(); form.append('file', file); const asset = await request(base + '/campaign-assets', { method: 'POST', body: form }); await refreshAssets(); $('campaign-asset').value = asset.id; await previewMedia(); report('Attachment uploaded. Draft content still requires approval.'); } catch (e) { report(e.message, true); } }
  file.addEventListener('change', () => upload(file.files[0])); zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragging'); }); zone.addEventListener('dragleave', () => zone.classList.remove('dragging')); zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('dragging'); upload(e.dataTransfer.files[0]); });
  $('campaign-asset').addEventListener('change', previewMedia);
  $('campaign-template').addEventListener('change', () => templateChanged());
  $('campaign-form').addEventListener('submit', e => { e.preventDefault(); const form = e.currentTarget; busy(form.querySelector('button[type=submit]'), async () => {
    const t = currentTemplate(); if (!t) throw new Error('Choose an approved template first.');
    const item = await call('/campaigns', { title: form.elements.title.value, template_id: t.id, parameters: Array.from({ length: t.spec.parameters }, (_, n) => form.elements[`parameter-${n + 1}`].value), asset_id: form.elements.asset.value || null, audience: { branch_id: form.elements.branch.value || null, interest: form.elements.interest.value || null }, scheduled_at: new Date(form.elements.scheduled.value).toISOString(), rate_paise: Math.round(Number(form.elements.rate.value) * 100), budget_paise: Math.round(Number(form.elements.budget.value) * 100) });
    const preview = await request(base + `/campaigns/${item.id}/preview`); $('campaign-preview').textContent = `${preview.body}\n\n${preview.recipients} consented recipients · estimate ${money(preview.estimated_cost_paise)}\n${preview.within_budget ? 'Within estimated budget' : 'Over estimated budget; approval blocked'}`;
    report('Draft saved. Test it before approving the audience.'); await outreach();
  }); });
  async function outreach() {
    campaigns = await request(base + '/campaigns'); $('campaign-list').replaceChildren(...campaigns.map(item => {
      const card = node('article', null, 'case desk-form'); card.append(node('h3', item.title), node('p', `${item.status} · ${time(item.scheduled_at)}\n${Object.entries(item.counts).map(([key, count]) => `${key}: ${count}`).join(' · ') || 'No audience messages yet'}\nButton replies: ${item.engaged} · Bookings: ${item.bookings} · Button opt-outs: ${item.unsubscribes_from_buttons}`, 'detail'));
      if (item.status === 'draft') {
        card.append(button('Preview draft', async () => { const preview = await request(base + `/campaigns/${item.id}/preview`); $('campaign-preview').textContent = `${preview.body}\n\n${preview.recipients} consented recipients · estimate ${money(preview.estimated_cost_paise)}\n${preview.within_budget ? 'Within estimated budget' : 'Over estimated budget; approval blocked'}`; await previewMedia(preview.header_asset_id || ''); report('Draft preview loaded. No message sent.'); }));
        const recipient = select('Configured test phone', config.test_recipients.map(n => [n, `+${n}`])); const actor = input('Approving staff name'); const received = input('I received and checked the test message', 'checkbox');
        const name = () => { if (actor.el.value.trim().length < 2) throw new Error('Enter the approving staff member’s name.'); return actor.el.value.trim(); };
        card.append(recipient.root, actor.root, button('Send one test', async () => { await call(`/campaigns/${item.id}/test`, { sender_id: recipient.el.value, actor: name() }); report('Test queued. Wait for it on the selected verified phone.'); }), received.root,
          button('Review & approve audience', async () => {
            if (!received.el.checked) throw new Error('Receive and check the test message first.');
            const preview = await request(base + `/campaigns/${item.id}/preview`);
            const review = node('div', `${preview.body}\n\nApprove ${preview.recipients} recipients. Estimate ${money(preview.estimated_cost_paise)}. Budget ${money(item.budget_paise)}.`, 'message-preview');
            const approve = button('Approve these recipients', async () => { await call(`/campaigns/${item.id}/approve`, { actor: name(), test_received: true, expected_count: preview.recipients, audience_hash: preview.audience_hash }); report('Campaign approved. The server rechecks consent and send limits at delivery.'); await outreach(); });
            approve.disabled = !preview.within_budget || !preview.recipients; review.append(approve); card.append(review);
          }));
      }
      if (item.status === 'scheduled') card.append(button('Pause unsent messages', async () => { await call(`/campaigns/${item.id}/pause`, {}); report('Unsent campaign messages paused. Messages already sending may arrive.'); await outreach(); }));
      return card;
    }));
    if (!campaigns.length) $('campaign-list').append(node('p', 'No campaigns yet.', 'detail'));
    const jobs = await request(base + '/outbound'); $('outbound-list').replaceChildren(...jobs.map(j => { const card = node('article', null, 'case'); card.append(node('strong', `${j.purpose} · ${j.status}`), node('p', `+${j.sender_id} · ${time(j.due_at)}\n${j.last_error || ''}\n${j.meta_message_id || 'No Meta receipt yet'}`, 'detail')); return card; }));
  }
  async function rules() {
    const rules = await request(base + '/followup-rules');
    $('followup-rules').replaceChildren(...['feedback', 'no_show', 'followup'].map(kind => {
      const rule = rules.find(r => r.kind === kind), card = node('article', null, 'card desk-form'); card.append(node('h3', ({ feedback: 'Post-visit feedback', no_show: 'Missed visit rebooking', followup: 'Doctor-requested follow-up' })[kind]));
      const choices = templates.filter(t => t.status === 'APPROVED' && t.spec?.parameters === 3 && [null, 'TEXT'].includes(t.spec.header) && t.category !== 'AUTHENTICATION');
      const template = select('Approved care template', choices.map(t => [t.id, templateLabel(t)]), rule?.template_id), delay = input('Delay after staff status change (hours)', 'number', rule?.delay_hours ?? 24), enabled = input('Enable consented messages', 'checkbox'); enabled.el.checked = rule?.enabled ?? false; delay.el.min = 0; delay.el.max = 720;
      card.append(node('p', 'Template fields: booking reference, doctor name, visit time. Marketing-classified templates also require offer consent.', 'detail'), template.root, delay.root, enabled.root, button('Save rule', async () => { await call(`/followup-rules/${kind}`, { template_id: template.el.value, delay_hours: Number(delay.el.value), enabled: enabled.el.checked }, 'PUT'); report('Follow-up rule saved.'); })); return card;
    }));
    const visits = await request('/api/v1/admin/appointments?status=completed&limit=200'); options($('followup-appointment'), visits.filter(v => v.origin_channel === 'whatsapp').map(v => [v.id, `${v.confirmation_code} · ${v.doctor?.name} · ${time(v.starts_at)}`]), 'Choose a completed WhatsApp visit');
  }
  $('manual-followup').addEventListener('submit', e => { e.preventDefault(); const form = e.currentTarget; busy(form.querySelector('button'), async () => { await call(`/appointments/${$('followup-appointment').value}/followup`, { actor: form.elements.actor.value, due_at: new Date(form.elements.due.value).toISOString() }); report('Doctor-requested follow-up scheduled.'); await outreach(); }); });
  function clinics() {
    $('clinic-details').replaceChildren(...inventory.branches.map(branch => {
      const card = node('article', null, 'card desk-form'); card.append(node('h3', branch.name)); const address = input('Clinic address', 'textarea', branch.address), directions = input('HTTPS Google Maps link', 'url', branch.directions_url), arrival = input('Arrival instructions', 'textarea', branch.arrival_instructions); card.append(address.root, directions.root, arrival.root, button('Save clinic details', async () => { await call(`/branches/${branch.id}`, { address: address.el.value, directions_url: directions.el.value, arrival_instructions: arrival.el.value }, 'PATCH'); report('Clinic details saved.'); })); return card;
    }));
  }
  $('refresh-reception').addEventListener('click', e => busy(e.currentTarget, reception)); $('refresh-outreach').addEventListener('click', e => busy(e.currentTarget, outreach));
  document.addEventListener('desk-auth', async e => {
    request = e.detail.request;
    try {
      [inventory, templates, assets, config] = await Promise.all([request('/api/v1/admin/catalogue'), request(base + '/templates'), request(base + '/campaign-assets'), request(base + '/operations-config')]);
      $('outreach-config').textContent = `${config.outreach_enabled ? 'Approved outreach delivery is enabled.' : 'Patient outreach delivery is disabled on the server. Only configured test recipients can receive campaign tests.'} ${config.marketing_contacts} contacts opted in to offers. ${config.test_recipients.length} test recipients configured. Reception: ${config.reception.hours}`;
      options($('campaign-template'), approved('MARKETING').map(t => [t.id, templateLabel(t)]), 'Choose approved marketing template'); options($('campaign-branch'), inventory.branches.filter(b => b.is_active).map(b => [b.id, b.name]), 'All clinics'); options($('campaign-interest'), inventory.departments.filter(d => d.is_active).map(d => [d.slug, d.name]), 'All specialties');
      const date = new Date(Date.now() + 60 * 60 * 1000); date.setMinutes(date.getMinutes() - date.getTimezoneOffset()); $('campaign-form').elements.scheduled.value = date.toISOString().slice(0, 16);
      templateChanged(); clinics(); await Promise.all([reception(), outreach(), rules()]);
    } catch (error) { report(error.message, true); }
  });
})();
