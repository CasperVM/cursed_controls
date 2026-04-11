// ── Device helpers ───────────────────────────────────────────

/** Build {parent_uhid → device} map for composite parent devices. */
function _buildParentMap(devices) {
  const m = {};
  devices.forEach(d => { if (d.is_composite_parent && d.parent_uhid) m[d.parent_uhid] = d; });
  return m;
}

/**
 * Best MAC/identifier for a device.
 * Falls back to phys (which carries the Wiimote MAC), then parent's identifier,
 * then evdev path.
 */
function _deviceMac(d, parentMap) {
  if (d.uniq) return d.uniq;
  if (d.phys) return d.phys;
  // Child device — inherit from composite parent
  if (d.parent_uhid && parentMap[d.parent_uhid]) {
    const p = parentMap[d.parent_uhid];
    return p.uniq || p.phys || '';
  }
  return '';
}

// ── WebSocket ────────────────────────────────────────────────
const WS_URL = `ws://${location.host}/ws`;
let ws = null;
let wsListeners = {};   // type → [handler, ...]

function wsOn(type, handler) {
  if (!wsListeners[type]) wsListeners[type] = [];
  wsListeners[type].push(handler);
}

function wsSend(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function wsConnect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    document.getElementById('ws-status').textContent = 'ws: connected';
  };
  ws.onclose = () => {
    document.getElementById('ws-status').textContent = 'ws: reconnecting…';
    setTimeout(wsConnect, 2000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    const handlers = wsListeners[msg.type] || [];
    handlers.forEach(h => h(msg));
    const allHandlers = wsListeners['*'] || [];
    allHandlers.forEach(h => h(msg));
  };
}

wsConnect();

// ── HTML escaping helper ──────────────────────────────────────
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Toast notifications ───────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type = 'ok') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = type === 'error' ? 'error' : '';
  void el.offsetWidth; // force reflow so transition fires even if already visible
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

// ── Tab switching ─────────────────────────────────────────────
document.querySelectorAll('nav button[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.tab;
    document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${target}`).classList.add('active');
  });
});

// ── Theme toggle ──────────────────────────────────────────────
(function () {
  const btn = document.getElementById('btn-theme');
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
  }
  applyTheme(localStorage.getItem('theme') || 'dark');
  btn.addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
  });
})();

// ── Runtime status indicator ──────────────────────────────────
wsOn('runtime_status', (msg) => {
  const dot = document.getElementById('runtime-dot');
  const lbl = document.getElementById('runtime-label');
  const knownStatuses = ['running', 'stopped'];
  dot.className = 'status-dot ' + (knownStatuses.includes(msg.status) ? msg.status : 'stopped');
  lbl.textContent = msg.status;
});

// ── API helpers ───────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status}: ${text}`);
  }
  return r.json();
}

// ── Devices tab ───────────────────────────────────────────────
const _devicesTbody = document.getElementById('devices-tbody');
_devicesTbody.addEventListener('click', (e) => {
  const btn = e.target.closest('.btn-buzz');
  if (!btn) return;
  btn.disabled = true;
  apiFetch(`/api/devices/${encodeURIComponent(btn.dataset.profile)}/rumble_test`, { method: 'POST' })
    .catch(() => { })
    .finally(() => { setTimeout(() => { btn.disabled = false; }, 1600); });
});

async function loadDevices() {
  try {
    const devices = await apiFetch('/api/devices');
    _devicesTbody.innerHTML = '';
    const parentMap = _buildParentMap(devices);
    devices.forEach(d => {
      const mac = _deviceMac(d, parentMap);
      const status = d.bound_profile
        ? `<span class="badge bound">${escapeHtml(d.bound_profile)}</span>`
        : '<span class="badge unbound">unbound</span>';
      const buzzBtn = d.bound_profile && d.has_ff
        ? `<button class="btn secondary btn-buzz" data-profile="${escapeHtml(d.bound_profile)}">buzz</button>`
        : `<button class="btn secondary" disabled title="no force feedback">buzz</button>`;
      _devicesTbody.insertAdjacentHTML('beforeend', `
        <tr>
          <td>${escapeHtml(d.path)}</td>
          <td>${escapeHtml(d.name)}<span class="dim" style="font-size:.75rem;display:block">${escapeHtml(mac || d.path)}</span></td>
          <td>${d.is_composite_parent ? 'parent' : d.is_composite ? 'child' : '—'}</td>
          <td>${status}</td>
          <td>${buzzBtn}</td>
        </tr>`);
    });
  } catch (e) {
    _devicesTbody.innerHTML = '<tr><td colspan="5">Failed to load devices.</td></tr>';
  }
}

document.getElementById('btn-refresh-devices').addEventListener('click', loadDevices);
wsOn('device_bound', () => { loadDevices(); _refreshFfStatus(); });
wsOn('device_disconnected', () => { loadDevices(); _refreshFfStatus(); });

// BT scan
const btTbody = document.getElementById('bt-tbody');
const btTable = document.getElementById('bt-table');
const btStatus = document.getElementById('bt-scan-status');

document.getElementById('btn-bt-scan').addEventListener('click', async () => {
  btTbody.innerHTML = '';
  btTable.style.display = 'table';
  btStatus.textContent = 'Scanning…';
  await apiFetch('/api/bt/scan', { method: 'POST' });
});

wsOn('bt_scan', (msg) => {
  if (msg.event === 'found') {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${escapeHtml(msg.mac)}</td><td>${escapeHtml(msg.name)}</td><td><button class="btn secondary btn-connect">Connect</button></td>`;
    tr.querySelector('.btn-connect').addEventListener('click', () => btConnect(msg.mac));
    btTbody.appendChild(tr);
  } else if (msg.event === 'done') {
    btStatus.textContent = 'Scan complete.';
  }
});

async function btConnect(mac) {
  btStatus.textContent = `Connecting ${mac}…`;
  try {
    await apiFetch('/api/bt/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac }),
    });
    btStatus.textContent = `Connected ${mac}`;
    loadDevices();
    loadPairedDevices();
  } catch (e) {
    btStatus.textContent = `Failed: ${e.message}`;
  }
}

// ── Paired devices ────────────────────────────────────────────
async function loadPairedDevices() {
  const tbody = document.getElementById('paired-tbody');
  try {
    const devices = await apiFetch('/api/bt/paired');
    tbody.innerHTML = '';
    if (!devices.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="dim">No paired devices.</td></tr>';
      return;
    }
    devices.forEach(d => {
      const tr = document.createElement('tr');
      const statusBadge = d.connected
        ? '<span class="badge bound">connected</span>'
        : '<span class="badge unbound">disconnected</span>';
      const disconnectBtn = d.connected
        ? `<button class="btn secondary btn-bt-disconnect" data-mac="${escapeHtml(d.mac)}">Disconnect</button>`
        : '';
      tr.innerHTML = `
        <td>${escapeHtml(d.name)}</td>
        <td class="dim" style="font-size:.85rem">${escapeHtml(d.mac)}</td>
        <td>${statusBadge}</td>
        <td style="display:flex;gap:.25rem">
          ${disconnectBtn}
          <button class="btn danger btn-bt-unpair" data-mac="${escapeHtml(d.mac)}">Unpair</button>
        </td>`;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll('.btn-bt-disconnect').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.textContent = '…';
        try {
          await apiFetch('/api/bt/disconnect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac: btn.dataset.mac }),
          });
        } catch (e) { /* ignore */ }
        loadPairedDevices();
        loadDevices();
      });
    });

    tbody.querySelectorAll('.btn-bt-unpair').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm(`Unpair ${btn.dataset.mac}?`)) return;
        btn.disabled = true; btn.textContent = '…';
        try {
          await apiFetch('/api/bt/unpair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac: btn.dataset.mac }),
          });
        } catch (e) { /* ignore */ }
        loadPairedDevices();
        loadDevices();
      });
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--disconnected)">Failed: ${escapeHtml(e.message)}</td></tr>`;
  }
}

document.getElementById('btn-refresh-paired').addEventListener('click', loadPairedDevices);
loadPairedDevices();

// ── Mapping tab ───────────────────────────────────────────────
let profiles = [];         // array of profile objects (AppConfig.devices serialised)
let _ffStatus = {};        // {profile_id: bool} — cached from /api/devices
let _boundPaths = {};      // {profile_id: device_path} — cached from /api/devices
let _devicesByName = {};   // {device_name: device_path} — fallback for unbound devices
let _mappingTestPath = null; // device path currently subscribed to for live mapping test

async function _refreshFfStatus() {
  try {
    const devs = await apiFetch('/api/devices');
    _ffStatus = {};
    _boundPaths = {};
    _devicesByName = {};
    devs.forEach(d => {
      if (d.name) _devicesByName[d.name] = d.path;
      if (d.bound_profile) {
        _ffStatus[d.bound_profile] = d.has_ff;
        _boundPaths[d.bound_profile] = d.path;
      }
    });
    renderProfileList();
    _updateMappingTestSubscription();
  } catch (_) { }
}

function _updateMappingTestSubscription() {
  const p = selectedProfile !== null ? profiles[selectedProfile] : null;
  let path = null;
  if (p) {
    path = _boundPaths[p.id] || null;
    // Fallback: device is present but not yet bound (e.g. runtime stopped)
    if (!path) {
      const matchVal = Object.values(p.match || {})[0] || '';
      if (matchVal) path = _devicesByName[matchVal] || null;
    }
  }
  if (path === _mappingTestPath) return;
  if (_mappingTestPath) wsSend({ type: 'unsubscribe_input' });
  _mappingTestPath = path;
  if (_mappingTestPath) wsSend({ type: 'subscribe_input', device_path: _mappingTestPath });
}

function _pauseMappingTest() {
  if (_mappingTestPath) wsSend({ type: 'unsubscribe_input' });
}

function _resumeMappingTest() {
  if (_mappingTestPath) wsSend({ type: 'subscribe_input', device_path: _mappingTestPath });
}
let selectedProfile = null;

async function loadConfig() {
  try {
    const cfg = await apiFetch('/api/config');
    profiles = cfg?.devices ?? [];
    await _refreshFfStatus();  // sets _ffStatus then re-renders list
  } catch (e) {
    console.error('loadConfig failed:', e);
    const ul = document.getElementById('profile-list');
    if (ul) ul.innerHTML = '<li style="color:var(--disconnected)">Failed to load config.</li>';
  }
}

function renderProfileList() {
  const ul = document.getElementById('profile-list');
  ul.innerHTML = '';
  profiles.forEach((p, i) => {
    const li = document.createElement('li');
    li.style.cssText = 'padding:.3rem .5rem;cursor:pointer;border-radius:4px;display:flex;align-items:center;gap:.5rem;';
    if (selectedProfile === i) li.style.background = 'var(--accent-dim)';

    const label = document.createElement('span');
    label.style.flex = '1';
    label.textContent = p.id;
    label.addEventListener('click', () => { selectedProfile = i; renderProfileEditor(); renderProfileList(); });

    const hasFF = !!_ffStatus[p.id];
    const buzz = document.createElement('button');
    buzz.className = 'btn secondary';
    buzz.textContent = 'buzz';
    buzz.style.padding = '0 .4rem';
    buzz.style.fontSize = '.75rem';
    buzz.disabled = !hasFF;
    buzz.title = hasFF ? 'Test rumble' : 'not bound or no force feedback';
    buzz.addEventListener('click', (e) => {
      e.stopPropagation();
      buzz.disabled = true;
      apiFetch(`/api/devices/${encodeURIComponent(p.id)}/rumble_test`, { method: 'POST' })
        .catch(() => { })
        .finally(() => { setTimeout(() => { buzz.disabled = !_ffStatus[p.id]; }, 1600); });
    });

    li.appendChild(label);
    li.appendChild(buzz);
    ul.appendChild(li);
  });
}

function renderProfileEditor() {
  if (selectedProfile === null || !profiles[selectedProfile]) {
    document.getElementById('no-profile-msg').style.display = '';
    document.getElementById('profile-editor').style.display = 'none';
    return;
  }
  document.getElementById('no-profile-msg').style.display = 'none';
  document.getElementById('profile-editor').style.display = '';
  const p = profiles[selectedProfile];

  document.getElementById('profile-editor-title').textContent = `Profile: ${p.id}`;
  document.getElementById('profile-id-input').value = p.id;
  const matchKey = Object.keys(p.match || {})[0] || 'name';
  const matchVal = (p.match || {})[matchKey] || '';
  document.getElementById('profile-match-key').value = matchKey;
  document.getElementById('profile-match-val').value = matchVal;
  const mac = p.connection?.mac || '';
  document.getElementById('picked-device-label').textContent = matchVal ? matchVal + (mac ? ` — ${mac}` : '') : '';

  const connType = p.connection?.type || 'evdev';
  document.getElementById('profile-conn-type').value = connType;
  document.getElementById('profile-mac-field').style.display =
    connType !== 'evdev' ? '' : 'none';
  document.getElementById('profile-mac').value = p.connection?.mac || '';
  document.getElementById('profile-slot').value = String(p.slot ?? 0);
  document.getElementById('profile-rumble').value = (p.rumble ?? true) ? 'true' : 'false';

  renderMappingsTable(p.mappings || []);
  _updateMappingTestSubscription();
}

document.getElementById('profile-conn-type').addEventListener('change', (e) => {
  document.getElementById('profile-mac-field').style.display =
    e.target.value !== 'evdev' ? '' : 'none';
});

function renderMappingsTable(mappings) {
  const tbody = document.getElementById('mappings-tbody');
  tbody.innerHTML = '';
  mappings.forEach((m, i) => {
    const srcCode = `${m.source_type === 1 ? 'EV_KEY' : 'EV_ABS'} ${m.source_code}`;
    const srcCell = m.label
      ? `${escapeHtml(m.label)}<span class="dim" style="font-size:.75rem;display:block">${escapeHtml(srcCode)}</span>`
      : escapeHtml(srcCode);
    // kind lives at top-level (wizard-built) or inside transform (API-loaded)
    const kind = m.transform?.kind ?? m.kind ?? '';
    const srcMin = m.transform?.source_min ?? m.source_min;
    const srcMax = m.transform?.source_max ?? m.source_max;
    const deadzone = m.transform?.deadzone ?? m.deadzone;
    const invert = m.transform?.invert ?? m.invert;
    const extras = [];
    if (srcMin != null) extras.push(`src:${srcMin}..${srcMax}`);
    if (deadzone) extras.push(`dz=${escapeHtml(deadzone)}`);
    if (invert) extras.push('↕inv');
    const isAxis = m.source_type === 3 && kind !== 'hat';
    const liveCell = isAxis
      ? `<td><div class="axis-bar-track live-axis-track" data-mapping-code="${escapeHtml(String(m.source_code))}"><div class="axis-bar-fill" style="width:0%"></div></div></td>`
      : `<td><span class="live-btn" id="live-row-${i}"></span></td>`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${srcCell}</td>
      <td>${escapeHtml(kind)}</td>
      <td>${escapeHtml(m.target)}</td>
      <td class="dim">${extras.join(' ')}</td>
      ${liveCell}
      <td style="display:flex;gap:.25rem">
        <button class="btn secondary btn-edit-mapping">✎</button>
        <button class="btn danger btn-del-mapping">✕</button>
      </td>`;
    tr.querySelector('.btn-del-mapping').addEventListener('click', () => deleteMapping(i));
    tr.querySelector('.btn-edit-mapping').addEventListener('click', () => editMapping(i));
    tbody.appendChild(tr);
  });
}

function deleteMapping(idx) {
  if (selectedProfile === null) return;
  profiles[selectedProfile].mappings.splice(idx, 1);
  renderMappingsTable(profiles[selectedProfile].mappings);
  saveConfig();
}

function editMapping(idx) {
  if (selectedProfile === null) return;
  const m = profiles[selectedProfile].mappings[idx];
  if (!m) return;

  // Normalize — fields may be nested in transform or at top-level
  const kind = m.transform?.kind ?? m.kind ?? 'button';
  const srcMin = m.transform?.source_min ?? m.source_min ?? 0;
  const srcMax = m.transform?.source_max ?? m.source_max ?? 255;
  const deadzone = m.transform?.deadzone ?? m.deadzone ?? 0;
  const invert = m.transform?.invert ?? m.invert ?? false;
  const onValue = m.transform?.on_value ?? m.on_value ?? null;

  wizardData = { editIdx: idx, surface: m.target };
  document.getElementById('wizard-overlay').classList.add('open');
  document.getElementById('wizard-title').textContent = 'Edit Mapping';
  document.getElementById('wizard-confirm').style.display = 'none';

  const srcLabel = m.source_type === 1 ? 'EV_KEY' : 'EV_ABS';
  wizardSetContent(`
    <p class="dim">Source: <strong>${escapeHtml(srcLabel)} ${escapeHtml(String(m.source_code))}</strong></p>
    <div class="field" style="margin-top:.5rem">
      <label>Label <span class="dim">(optional)</span></label>
      <input type="text" id="wz-label" placeholder="e.g. Jump, Left stick X…" value="${escapeHtml(m.label || '')}">
    </div>
    <p class="dim" style="margin-top:.5rem">Xbox surface:</p>
    <div class="surface-grid mt">${SURFACES.map(s =>
    `<button class="surface-btn${s === m.target ? ' selected' : ''}" data-surface="${s}">${s}</button>`
  ).join('')}</div>
    <div id="wz-transform-opts" style="margin-top:1rem"></div>
  `);

  const redrawTransform = () => _showEditTransform(kind, wizardData.surface, { srcMin, srcMax, deadzone, invert, onValue, sourceCode: m.source_code });

  document.querySelectorAll('.surface-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.surface-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      wizardData.surface = btn.dataset.surface;
      redrawTransform();
    });
  });

  redrawTransform();
  document.getElementById('wizard-confirm').style.display = '';
  document.getElementById('wizard-confirm').onclick = () => _confirmEdit(idx, kind);
}

function _wireRedetectBtn(sourceCode) {
  const btn = document.getElementById('wz-redetect-btn');
  if (!btn) return;
  btn.addEventListener('click', function () {
    if (_axisRedetect) {
      // Stop
      _axisRedetect = null;
      this.textContent = '⇔ Re-detect range';
      this.classList.add('secondary');
      document.getElementById('wz-src-min')?.removeAttribute('readonly');
      document.getElementById('wz-src-max')?.removeAttribute('readonly');
      document.getElementById('wz-redetect-hint').textContent = 'Move axis to both extremes after clicking.';
    } else {
      // Start — reset observed range
      _axisRedetect = { code: sourceCode, observed_min: Infinity, observed_max: -Infinity };
      this.textContent = '■ Stop';
      this.classList.remove('secondary');
      document.getElementById('wz-src-min')?.setAttribute('readonly', '');
      document.getElementById('wz-src-max')?.setAttribute('readonly', '');
      document.getElementById('wz-redetect-hint').textContent = 'Detecting… move axis to its extremes.';
    }
  });
}

function _showEditTransform(kind, surface, { srcMin, srcMax, deadzone, invert, onValue = null, sourceCode = null }) {
  const el = document.getElementById('wz-transform-opts');
  if (!el) return;
  if (kind === 'hat') {
    el.innerHTML = `
      <div class="row">
        <div class="field" style="flex:1">
          <label>Trigger value</label>
          <input type="number" id="wz-hat-on-val" value="${escapeHtml(String(onValue ?? ''))}">
        </div>
        <div class="field" style="flex:1">
          <label>Invert</label>
          <select id="wz-invert">
            <option value="false"${!invert ? ' selected' : ''}>no</option>
            <option value="true"${invert ? ' selected' : ''}>yes</option>
          </select>
        </div>
      </div>`;
  } else if (kind === 'axis') {
    el.innerHTML = `
      <div class="row">
        <div class="field" style="flex:1">
          <label>Source min</label>
          <input type="number" id="wz-src-min" value="${escapeHtml(String(srcMin))}">
        </div>
        <div class="field" style="flex:1">
          <label>Source max</label>
          <input type="number" id="wz-src-max" value="${escapeHtml(String(srcMax))}">
        </div>
        <div class="field" style="flex:1">
          <label>Deadzone (0-1)</label>
          <input type="number" id="wz-deadzone" value="${escapeHtml(String(deadzone))}" step="0.01" min="0" max="1">
        </div>
        <div class="field" style="flex:1">
          <label>Invert</label>
          <select id="wz-invert">
            <option value="false"${!invert ? ' selected' : ''}>no</option>
            <option value="true"${invert ? ' selected' : ''}>yes</option>
          </select>
        </div>
      </div>
      <div class="row" style="margin-top:.4rem;align-items:center">
        <button type="button" class="btn secondary" id="wz-redetect-btn" style="font-size:.8rem;padding:.25rem .6rem">⇔ Re-detect range</button>
        <span class="dim" id="wz-redetect-hint" style="font-size:.75rem">Move axis to both extremes after clicking.</span>
      </div>`;
    if (sourceCode != null) _wireRedetectBtn(sourceCode);
  } else {
    el.innerHTML = '';
  }
}

function _confirmEdit(idx, kind) {
  if (!wizardData.surface || selectedProfile === null) return;
  const m = profiles[selectedProfile].mappings[idx];
  if (!m) return;

  m.target = wizardData.surface;
  const label = document.getElementById('wz-label')?.value.trim();
  if (label) m.label = label; else delete m.label;
  // Flatten any nested transform into top-level fields
  delete m.transform;

  if (kind === 'hat') {
    m.kind = 'hat';
    const onVal = document.getElementById('wz-hat-on-val')?.value.trim();
    if (onVal !== '' && onVal != null) m.on_value = parseInt(onVal); else delete m.on_value;
    const inv = document.getElementById('wz-invert')?.value === 'true';
    if (inv) m.invert = true; else delete m.invert;
    delete m.source_min; delete m.source_max;
    delete m.target_min; delete m.target_max;
    delete m.deadzone; delete m.off_value;
  } else if (kind === 'axis') {
    const isTrigger = ['LEFT_TRIGGER', 'RIGHT_TRIGGER'].includes(wizardData.surface);
    m.kind = 'axis';
    m.source_min = parseInt(document.getElementById('wz-src-min')?.value ?? '0');
    m.source_max = parseInt(document.getElementById('wz-src-max')?.value ?? '255');
    m.target_min = isTrigger ? 0 : -32767;
    m.target_max = isTrigger ? 255 : 32767;
    const dz = parseFloat(document.getElementById('wz-deadzone')?.value ?? '0');
    if (dz > 0) m.deadzone = dz; else delete m.deadzone;
    const inv = document.getElementById('wz-invert')?.value === 'true';
    if (inv) m.invert = true; else delete m.invert;
  } else {
    m.kind = 'button';
    const isAxisSurface = ['LEFT_JOYSTICK_X', 'LEFT_JOYSTICK_Y', 'RIGHT_JOYSTICK_X', 'RIGHT_JOYSTICK_Y',
      'LEFT_TRIGGER', 'RIGHT_TRIGGER'].includes(wizardData.surface);
    if (isAxisSurface) {
      m.on_value = wizardData.surface.includes('TRIGGER') ? 255 : 32767;
      m.off_value = 0;
    }
  }

  renderMappingsTable(profiles[selectedProfile].mappings);
  saveConfig();
  closeWizard();
}

document.getElementById('btn-save-profile').addEventListener('click', () => {
  if (selectedProfile === null) return;
  const p = profiles[selectedProfile];
  p.id = document.getElementById('profile-id-input').value;
  const key = document.getElementById('profile-match-key').value;
  p.match = { [key]: document.getElementById('profile-match-val').value };
  const connType = document.getElementById('profile-conn-type').value;
  p.connection = { type: connType };
  if (connType !== 'evdev') {
    p.connection.mac = document.getElementById('profile-mac').value;
  }
  p.slot = parseInt(document.getElementById('profile-slot').value, 10);
  p.rumble = document.getElementById('profile-rumble').value === 'true';
  renderProfileList();
  renderProfileEditor();
  saveConfig();
});

document.getElementById('btn-delete-profile').addEventListener('click', () => {
  if (selectedProfile === null) return;
  profiles.splice(selectedProfile, 1);
  selectedProfile = null;
  renderProfileList();
  renderProfileEditor();
  saveConfig();
});

document.getElementById('btn-add-profile').addEventListener('click', () => {
  const id = `device-${profiles.length + 1}`;
  profiles.push({ id, match: { name: '' }, mappings: [], connection: { type: 'evdev' } });
  selectedProfile = profiles.length - 1;
  renderProfileList();
  renderProfileEditor();
});

// ── Device picker ─────────────────────────────────────────────

document.getElementById('btn-pick-device').addEventListener('click', openDevicePicker);
document.getElementById('btn-picker-close').addEventListener('click', closeDevicePicker);
document.getElementById('device-picker').addEventListener('click', (e) => {
  if (e.target === document.getElementById('device-picker')) closeDevicePicker();
});

function closeDevicePicker() {
  document.getElementById('device-picker').style.display = 'none';
}

async function openDevicePicker() {
  const modal = document.getElementById('device-picker');
  const list = document.getElementById('picker-list');
  list.innerHTML = '<span class="dim">Loading…</span>';
  modal.style.display = 'flex';

  const [evdevDevices, btDevices] = await Promise.all([
    apiFetch('/api/devices').catch(() => []),
    apiFetch('/api/bt/paired').catch(() => []),
  ]);

  list.innerHTML = '';
  const parentMap = _buildParentMap(evdevDevices || []);

  // Evdev section
  const evdevFiltered = (evdevDevices || []).filter(d => !d.name.startsWith('vc4-') && !d.name.includes('HDMI'));
  if (evdevFiltered.length) {
    const hdr = document.createElement('div');
    hdr.className = 'dim';
    hdr.style.cssText = 'font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:.25rem 0';
    hdr.textContent = 'Connected (evdev)';
    list.appendChild(hdr);
    evdevFiltered.forEach(d => {
      const mac = _deviceMac(d, parentMap);
      const btn = document.createElement('button');
      btn.className = 'btn secondary';
      btn.style.cssText = 'text-align:left;justify-content:flex-start;width:100%';
      btn.textContent = d.name + (mac ? `  [${mac}]` : `  [${d.path}]`);
      btn.addEventListener('click', () => {
        applyPickedDevice({ name: d.name, uniq: d.uniq, connType: 'evdev', mac: '' });
        closeDevicePicker();
      });
      list.appendChild(btn);
    });
  }

  // BT section — skip devices already shown via evdev (match by uniq/MAC)
  const evdevMacs = new Set((evdevDevices || []).map(d => (_deviceMac(d, parentMap) || '').toLowerCase()));
  const btFiltered = (btDevices || []).filter(d => !evdevMacs.has(d.mac.toLowerCase()));
  if (btFiltered.length) {
    const hdr = document.createElement('div');
    hdr.className = 'dim';
    hdr.style.cssText = 'font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:.25rem 0;margin-top:.5rem';
    hdr.textContent = 'Paired (Bluetooth)';
    list.appendChild(hdr);
    btFiltered.forEach(d => {
      const isWiimote = /wii|nintendo rvl/i.test(d.name);
      const btn = document.createElement('button');
      btn.className = 'btn secondary';
      btn.style.cssText = 'text-align:left;justify-content:flex-start;width:100%';
      btn.textContent = `${d.name}  [${d.mac}]`;
      btn.addEventListener('click', () => {
        applyPickedDevice({ name: d.name, uniq: d.mac, connType: isWiimote ? 'wiimote' : 'bluetooth', mac: d.mac });
        closeDevicePicker();
      });
      list.appendChild(btn);
    });
  }

  if (!evdevFiltered.length && !btFiltered.length) {
    list.innerHTML = '<span class="dim">No devices found. Connect a device or run a BT scan first.</span>';
  }
}

function applyPickedDevice({ name, uniq, connType, mac }) {
  document.getElementById('profile-match-key').value = 'name';
  document.getElementById('profile-match-val').value = name;
  document.getElementById('profile-conn-type').value = connType;
  const macField = document.getElementById('profile-mac-field');
  macField.style.display = connType !== 'evdev' ? '' : 'none';
  document.getElementById('profile-mac').value = mac || '';
  document.getElementById('picked-device-label').textContent = name + (mac ? ` — ${mac}` : '');
}

// ── Mapping wizard ────────────────────────────────────────────
const SURFACES = [
  'A', 'B', 'X', 'Y',
  'BUMPER_L', 'BUMPER_R', 'STICK_L', 'STICK_R',
  'START', 'OPTIONS', 'XBOX',
  'DPAD_UP', 'DPAD_DOWN', 'DPAD_LEFT', 'DPAD_RIGHT',
  'LEFT_JOYSTICK_X', 'LEFT_JOYSTICK_Y',
  'RIGHT_JOYSTICK_X', 'RIGHT_JOYSTICK_Y',
  'LEFT_TRIGGER', 'RIGHT_TRIGGER',
];

let wizardData = {};   // accumulated state across wizard steps
let _axisRedetect = null; // { code, observed_min, observed_max } — set while re-detecting axis range

function openWizard() {
  _pauseMappingTest();
  wizardData = {};
  document.getElementById('wizard-overlay').classList.add('open');
  wizardStep_chooseType();
}

function closeWizard() {
  document.getElementById('wizard-overlay').classList.remove('open');
  wsSend({ type: 'unsubscribe_input' });
  wizardData = {};
  _axisRedetect = null;
  _resumeMappingTest();
}

document.getElementById('wizard-cancel').addEventListener('click', closeWizard);
document.getElementById('btn-add-mapping').addEventListener('click', openWizard);

function wizardSetContent(html) {
  document.getElementById('wizard-content').innerHTML = html;
}

function wizardStep_chooseType() {
  document.getElementById('wizard-title').textContent = 'Add Mapping — Choose type';
  document.getElementById('wizard-confirm').style.display = 'none';
  wizardSetContent(`
    <p class="dim">What kind of input are you mapping?</p>
    <div class="row mt">
      <button class="btn" id="wz-btn-button">Button / Key</button>
      <button class="btn secondary" id="wz-btn-axis">Axis (joystick / trigger)</button>
    </div>
  `);
  document.getElementById('wz-btn-button').addEventListener('click', wizardStep_detectButton);
  document.getElementById('wz-btn-axis').addEventListener('click', wizardStep_axisMonitor);
}

// ── Wizard: button path ───────────────────────────────────────
function wizardStep_detectButton() {
  if (selectedProfile === null) return;
  const p = profiles[selectedProfile];
  const matchKey = Object.keys(p.match || {})[0];
  const matchVal = (p.match || {})[matchKey] || '';

  document.getElementById('wizard-title').textContent = 'Add Mapping — Press a button';
  document.getElementById('wizard-confirm').style.display = 'none';
  wizardSetContent(`
    <p class="dim">First, select the device for this profile, then press a button on it.</p>
    <div class="field mt">
      <label>Device</label>
      <select id="wz-device-select"></select>
    </div>
    <div id="wz-detect-status" class="dim mt">Waiting for button press…</div>
    <div id="wz-detected-info" style="display:none"></div>
  `);

  apiFetch('/api/devices').then(devices => {
    const sel = document.getElementById('wz-device-select');
    if (!sel) return;
    const boundPath = _boundPaths[p.id] || null;
    devices.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.path;
      opt.textContent = `${d.name} [${d.path}]`;
      if (boundPath ? d.path === boundPath : (d.name === matchVal || d.path === matchVal))
        opt.selected = true;
      sel.appendChild(opt);
    });
    startButtonDetect(sel.value);
    sel.addEventListener('change', () => startButtonDetect(sel.value));
  });
}

function startButtonDetect(devicePath) {
  wsSend({ type: 'unsubscribe_input' });
  wsSend({ type: 'subscribe_input', device_path: devicePath });
  wizardData.devicePath = devicePath;
  wizardData.pendingButton = null;
}

wsOn('button_detected', (msg) => {
  // Wizard path
  const statusEl = document.getElementById('wz-detect-status');
  if (statusEl) {
    const infoEl = document.getElementById('wz-detected-info');
    wizardData.pendingButton = msg;
    wizardData.hintLabel = null;
    statusEl.textContent = `Detected: ${msg.name} (code ${msg.ev_code})`;
    if (infoEl) {
      infoEl.style.display = '';
      infoEl.innerHTML = `<div class="dim">ev_type=${escapeHtml(msg.ev_type)} ev_code=${escapeHtml(msg.ev_code)} name=${escapeHtml(msg.name)}</div>`;
    }
    // Fetch label hint in background; fills the label input when available
    if (wizardData.devicePath) {
      apiFetch(`/api/presets/hint?device_path=${encodeURIComponent(wizardData.devicePath)}&source_type=${msg.ev_type}&source_code=${msg.ev_code}`)
        .then(d => {
          if (!d?.label) return;
          wizardData.hintLabel = d.label;
          const el = document.getElementById('wz-label');
          if (el && !el.value) el.value = d.label;
        }).catch(() => { });
    }
    wizardStep_pickSurface('button');
    return;
  }
  // Mapping test path — flash matching button row
  if (!_mappingTestPath || selectedProfile === null) return;
  const p = profiles[selectedProfile];
  if (!p) return;
  p.mappings.forEach((m, i) => {
    if (m.source_type === 1 && String(m.source_code) === String(msg.ev_code)) {
      const span = document.getElementById(`live-row-${i}`);
      if (!span) return;
      span.classList.add('live-flash');
      clearTimeout(span._t);
      span._t = setTimeout(() => span.classList.remove('live-flash'), 400);
    }
  });
});

// ── Wizard: axis monitor ──────────────────────────────────────
let axisRows = {};   // code → {row el, info}

function wizardStep_axisMonitor() {
  if (selectedProfile === null) return;
  const p = profiles[selectedProfile];
  const matchKey = Object.keys(p.match || {})[0];
  const matchVal = (p.match || {})[matchKey] || '';

  document.getElementById('wizard-title').textContent = 'Add Mapping — Axis Monitor';
  document.getElementById('wizard-confirm').style.display = 'none';
  axisRows = {};

  wizardSetContent(`
    <p class="dim">Select device, then move the axis you want to map. Click its row to select it.</p>
    <div class="row mt" style="margin-bottom:.75rem">
      <div class="field" style="flex:1;margin:0">
        <label>Device</label>
        <select id="wz-axis-device"></select>
      </div>
      <button class="btn secondary" id="wz-reset-axes">Reset min/max</button>
    </div>
    <table>
      <thead><tr>
        <th>Axis</th><th>Code</th><th>Current</th><th>Observed range</th><th>Bar</th>
      </tr></thead>
      <tbody id="wz-axis-tbody"></tbody>
    </table>
  `);

  apiFetch('/api/devices').then(devices => {
    const sel = document.getElementById('wz-axis-device');
    if (!sel) return;
    const boundPath = _boundPaths[p.id] || null;
    devices.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.path;
      opt.textContent = `${d.name} [${d.path}]`;
      if (boundPath ? d.path === boundPath : (d.name === matchVal || d.path === matchVal))
        opt.selected = true;
      sel.appendChild(opt);
    });
    startAxisMonitor(sel.value);
    sel.addEventListener('change', () => {
      axisRows = {};
      document.getElementById('wz-axis-tbody').innerHTML = '';
      startAxisMonitor(sel.value);
    });
  });

  document.getElementById('wz-reset-axes').addEventListener('click', () => {
    wsSend({ type: 'reset_axis_range' });
    axisRows = {};
    document.getElementById('wz-axis-tbody').innerHTML = '';
  });
}

function startAxisMonitor(devicePath) {
  wsSend({ type: 'unsubscribe_input' });
  wsSend({ type: 'subscribe_input', device_path: devicePath });
  wizardData.devicePath = devicePath;
}

wsOn('axis_update', (msg) => {
  const tbody = document.getElementById('wz-axis-tbody');
  if (!tbody) {
    // Button detect wizard — redirect to hat flow if a HAT axis fires
    if (document.getElementById('wz-detect-status')) {
      const hatAxis = msg.axes.find(a => a.name.includes('HAT') && a.value !== 0);
      if (hatAxis) {
        wizardData.pendingAxis = hatAxis;
        wizardStep_hatOrAxis();
        return;
      }
    }
    // Re-detect axis range — update min/max inputs live while user moves the axis
    if (_axisRedetect) {
      msg.axes.forEach(a => {
        if (a.code !== _axisRedetect.code) return;
        _axisRedetect.observed_min = Math.min(_axisRedetect.observed_min, a.value);
        _axisRedetect.observed_max = Math.max(_axisRedetect.observed_max, a.value);
        const minEl = document.getElementById('wz-src-min');
        const maxEl = document.getElementById('wz-src-max');
        if (minEl && isFinite(_axisRedetect.observed_min)) minEl.value = _axisRedetect.observed_min;
        if (maxEl && isFinite(_axisRedetect.observed_max)) maxEl.value = _axisRedetect.observed_max;
      });
    }
    // Mapping test path — update live axis bars and hat buttons in the mappings table
    if (!_mappingTestPath || selectedProfile === null) return;
    const p = profiles[selectedProfile];
    if (!p) return;
    msg.axes.forEach(a => {
      // Axis mappings — update bar
      const track = document.querySelector(`.live-axis-track[data-mapping-code="${CSS.escape(String(a.code))}"]`);
      if (track) {
        const m = p.mappings.find(m => m.source_type === 3 && (m.transform?.kind ?? m.kind) !== 'hat' && String(m.source_code) === String(a.code));
        if (m) {
          const srcMin = m.transform?.source_min ?? m.source_min ?? a.min;
          const srcMax = m.transform?.source_max ?? m.source_max ?? a.max;
          const pct = Math.round((a.value - srcMin) / ((srcMax - srcMin) || 1) * 100);
          track.querySelector('.axis-bar-fill').style.width = `${Math.max(0, Math.min(100, pct))}%`;
          const tr = track.closest('tr');
          if (tr) {
            tr.classList.add('active');
            clearTimeout(tr._axTimer);
            tr._axTimer = setTimeout(() => tr.classList.remove('active'), 400);
          }
        }
      }
      // Hat mappings — flash like buttons
      p.mappings.forEach((m, i) => {
        if ((m.transform?.kind ?? m.kind) !== 'hat') return;
        if (String(m.source_code) !== String(a.code)) return;
        const onValue = m.transform?.on_value ?? m.on_value;
        if (onValue == null || a.value !== onValue) return;
        const span = document.getElementById(`live-row-${i}`);
        if (!span) return;
        span.classList.add('live-flash');
        clearTimeout(span._t);
        span._t = setTimeout(() => span.classList.remove('live-flash'), 200);
      });
    });
    return;
  }
  msg.axes.forEach(a => {
    if (!axisRows[a.code]) {
      const tr = document.createElement('tr');
      tr.className = 'axis-row';
      tr.dataset.code = a.code;
      tr.innerHTML = `
        <td>${escapeHtml(a.name)}</td>
        <td>${escapeHtml(a.code)}</td>
        <td class="ax-cur">0</td>
        <td class="ax-range">—</td>
        <td><div class="axis-bar-wrap">
          <div class="axis-bar-track">
            <div class="axis-bar-fill" style="width:0%"></div>
          </div>
        </div></td>`;
      tr.addEventListener('click', () => selectAxis(axisRows[a.code].info, tr));
      tbody.appendChild(tr);
      axisRows[a.code] = { tr, info: a };
    }
    const row = axisRows[a.code];
    row.info = a;
    row.tr.querySelector('.ax-cur').textContent = a.value;
    row.tr.querySelector('.ax-range').textContent =
      `${a.observed_min} .. ${a.observed_max}`;
    const span = a.max - a.min || 1;
    const pct = Math.round((a.value - a.min) / span * 100);
    row.tr.querySelector('.axis-bar-fill').style.width = `${Math.max(0, Math.min(100, pct))}%`;
    row.tr.classList.add('active');
    clearTimeout(row._timer);
    row._timer = setTimeout(() => row.tr.classList.remove('active'), 500);
  });
});

function selectAxis(axisInfo, tr) {
  document.querySelectorAll('.axis-row').forEach(r => r.classList.remove('active'));
  tr.classList.add('active');
  wizardData.pendingAxis = axisInfo;
  wizardData.hintLabel = null;
  // Fetch label hint in background
  if (wizardData.devicePath) {
    apiFetch(`/api/presets/hint?device_path=${encodeURIComponent(wizardData.devicePath)}&source_type=3&source_code=${axisInfo.code}`)
      .then(d => {
        if (!d?.label) return;
        wizardData.hintLabel = d.label;
        const el = document.getElementById('wz-label');
        if (el && !el.value) el.value = d.label;
      }).catch(() => { });
  }
  if (axisInfo.name.includes('HAT')) {
    wizardStep_hatOrAxis();
  } else {
    wizardStep_pickSurface('axis');
  }
}

// ── Wizard: hat-or-axis choice ────────────────────────────────
function wizardStep_hatOrAxis() {
  document.getElementById('wizard-title').textContent = 'Add Mapping — Axis button (D-pad/Hat)';
  document.getElementById('wizard-confirm').style.display = 'none';
  wizardSetContent(`
    <p class="dim">Treat as direction buttons, or map as a continuous axis?</p>
    <div class="row mt">
      <button class="btn" id="wz-btn-hat">Hat (two buttons)</button>
      <button class="btn secondary" id="wz-btn-axis-cont">Axis (continuous)</button>
    </div>
  `);
  document.getElementById('wz-btn-hat').addEventListener('click', wizardStep_hatConfig);
  document.getElementById('wz-btn-axis-cont').addEventListener('click', () => wizardStep_pickSurface('axis'));
}

function wizardStep_hatConfig() {
  const a = wizardData.pendingAxis;
  document.getElementById('wizard-title').textContent = 'Add Mapping — Hat Config';
  const opts = SURFACES.map(s => `<option value="${s}">${s}</option>`).join('');
  wizardSetContent(`
    <p class="dim">Choose a surface and trigger value for each direction. Uncheck to skip a direction.</p>
    <div class="row mt" style="align-items:flex-end">
      <input type="checkbox" id="wz-hat-neg-en" checked style="margin-bottom:.35rem;flex-shrink:0">
      <div class="field" style="flex:1;margin:0 0 0 .4rem">
        <label>Negative (−) surface</label>
        <select id="wz-hat-neg-surface">${opts}</select>
      </div>
      <div class="field" style="flex:0 0 90px;margin:0 0 0 .4rem">
        <label>at value</label>
        <input type="number" id="wz-hat-neg-val" value="-1">
      </div>
    </div>
    <div class="row" style="align-items:flex-end;margin-top:.4rem">
      <input type="checkbox" id="wz-hat-pos-en" checked style="margin-bottom:.35rem;flex-shrink:0">
      <div class="field" style="flex:1;margin:0 0 0 .4rem">
        <label>Positive (+) surface</label>
        <select id="wz-hat-pos-surface">${opts}</select>
      </div>
      <div class="field" style="flex:0 0 90px;margin:0 0 0 .4rem">
        <label>at value</label>
        <input type="number" id="wz-hat-pos-val" value="1">
      </div>
    </div>
    <div class="row" style="margin-top:.75rem">
      <div class="field" style="flex:1">
        <label>Invert</label>
        <select id="wz-hat-invert">
          <option value="false">no</option>
          <option value="true">yes</option>
        </select>
      </div>
      <div class="field" style="flex:2">
        <label>Label <span class="dim">(optional, applied to each)</span></label>
        <input type="text" id="wz-label" placeholder="e.g. D-pad horizontal">
      </div>
    </div>
  `);
  // Pre-select sensible DPAD defaults based on axis name (X → left/right, Y → up/down)
  const neg = document.getElementById('wz-hat-neg-surface');
  const pos = document.getElementById('wz-hat-pos-surface');
  if (a.name.endsWith('X')) { neg.value = 'DPAD_LEFT'; pos.value = 'DPAD_RIGHT'; }
  else if (a.name.endsWith('Y')) { neg.value = 'DPAD_UP'; pos.value = 'DPAD_DOWN'; }

  // Toggle enabled state of each direction row when checkbox changes
  const _toggleDir = (checkId, surfId, valId) => {
    const cb = document.getElementById(checkId);
    const surf = document.getElementById(surfId);
    const val = document.getElementById(valId);
    const update = () => { surf.disabled = !cb.checked; val.disabled = !cb.checked; };
    cb.addEventListener('change', update);
  };
  _toggleDir('wz-hat-neg-en', 'wz-hat-neg-surface', 'wz-hat-neg-val');
  _toggleDir('wz-hat-pos-en', 'wz-hat-pos-surface', 'wz-hat-pos-val');

  document.getElementById('wizard-confirm').style.display = '';
  document.getElementById('wizard-confirm').onclick = confirmHatMapping;
}

function confirmHatMapping() {
  if (selectedProfile === null) return;
  const a = wizardData.pendingAxis;
  if (!a) return;
  const invert = document.getElementById('wz-hat-invert').value === 'true';
  const label = document.getElementById('wz-label')?.value.trim();
  const base = { source_type: 3, source_code: a.code, kind: 'hat' };
  if (invert) base.invert = true;
  const toAdd = [];
  if (document.getElementById('wz-hat-neg-en').checked) {
    const m = { ...base, target: document.getElementById('wz-hat-neg-surface').value, on_value: parseInt(document.getElementById('wz-hat-neg-val').value) };
    if (label) m.label = label;
    toAdd.push(m);
  }
  if (document.getElementById('wz-hat-pos-en').checked) {
    const m = { ...base, target: document.getElementById('wz-hat-pos-surface').value, on_value: parseInt(document.getElementById('wz-hat-pos-val').value) };
    if (label) m.label = label;
    toAdd.push(m);
  }
  if (!toAdd.length) return;
  profiles[selectedProfile].mappings.push(...toAdd);
  renderMappingsTable(profiles[selectedProfile].mappings);
  saveConfig();
  closeWizard();
}

// ── Wizard: surface picker ────────────────────────────────────
function wizardStep_pickSurface(inputKind) {
  const already = new Set((profiles[selectedProfile]?.mappings || []).map(m => m.target));
  document.getElementById('wizard-title').textContent = 'Add Mapping — Choose Xbox surface';
  document.getElementById('wizard-confirm').style.display = 'none';

  const grid = SURFACES.map(s =>
    `<button class="surface-btn${already.has(s) ? ' mapped' : ''}" data-surface="${s}">${s}</button>`
  ).join('');

  wizardSetContent(`
    <p class="dim">Click the Xbox surface this input should control.</p>
    <div class="surface-grid mt">${grid}</div>
    <div id="wz-transform-opts" style="display:none;margin-top:1rem"></div>
  `);

  document.querySelectorAll('.surface-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.surface-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      wizardData.surface = btn.dataset.surface;
      showTransformOptions(inputKind, btn.dataset.surface);
    });
  });
}

function showTransformOptions(inputKind, surface) {
  const el = document.getElementById('wz-transform-opts');
  if (!el) return;
  el.style.display = '';

  let html = '';
  if (inputKind === 'axis') {
    const a = wizardData.pendingAxis;
    html += `
      <div class="row">
        <div class="field" style="flex:1">
          <label>Source min</label>
          <input type="number" id="wz-src-min" value="${escapeHtml(a?.observed_min ?? a?.min ?? 0)}">
        </div>
        <div class="field" style="flex:1">
          <label>Source max</label>
          <input type="number" id="wz-src-max" value="${escapeHtml(a?.observed_max ?? a?.max ?? 255)}">
        </div>
        <div class="field" style="flex:1">
          <label>Deadzone (0-1)</label>
          <input type="number" id="wz-deadzone" value="0.0" step="0.01" min="0" max="1">
        </div>
        <div class="field" style="flex:1">
          <label>Invert</label>
          <select id="wz-invert">
            <option value="false">no</option>
            <option value="true">yes</option>
          </select>
        </div>
      </div>`;
  }
  if (inputKind === 'axis') {
    html += `
    <div class="row" style="margin-top:.4rem;align-items:center">
      <button type="button" class="btn secondary" id="wz-redetect-btn" style="font-size:.8rem;padding:.25rem .6rem">⇔ Re-detect range</button>
      <span class="dim" id="wz-redetect-hint" style="font-size:.75rem">Move axis to both extremes after clicking.</span>
    </div>`;
  }
  html += `
    <div class="field" style="margin-top:.5rem">
      <label>Label <span class="dim">(optional)</span></label>
      <input type="text" id="wz-label" placeholder="e.g. Jump, Left stick X…">
    </div>`;
  el.innerHTML = html;

  if (inputKind === 'axis' && wizardData.pendingAxis?.code != null) {
    _wireRedetectBtn(wizardData.pendingAxis.code);
  }

  // Pre-fill label from hint if already resolved
  const labelEl = document.getElementById('wz-label');
  if (labelEl && wizardData.hintLabel) labelEl.value = wizardData.hintLabel;

  document.getElementById('wizard-confirm').style.display = '';
  document.getElementById('wizard-confirm').onclick = () => confirmMapping(inputKind);
}

function confirmMapping(inputKind) {
  if (!wizardData.surface || selectedProfile === null) return;
  const surface = wizardData.surface;
  let mapping;

  const label = document.getElementById('wz-label')?.value.trim();

  if (inputKind === 'button') {
    const btn = wizardData.pendingButton;
    if (!btn) return;
    const isAxis = ['LEFT_JOYSTICK_X', 'LEFT_JOYSTICK_Y', 'RIGHT_JOYSTICK_X', 'RIGHT_JOYSTICK_Y',
      'LEFT_TRIGGER', 'RIGHT_TRIGGER'].includes(surface);
    mapping = {
      source_type: btn.ev_type,
      source_code: btn.ev_code,
      target: surface,
      kind: 'button',
    };
    if (isAxis) {
      const onVal = surface.includes('TRIGGER') ? 255 : 32767;
      mapping.on_value = onVal;
      mapping.off_value = 0;
    }
  } else {
    const a = wizardData.pendingAxis;
    if (!a) return;
    const srcMin = parseInt(document.getElementById('wz-src-min')?.value ?? a.min);
    const srcMax = parseInt(document.getElementById('wz-src-max')?.value ?? a.max);
    const deadzone = parseFloat(document.getElementById('wz-deadzone')?.value ?? '0');
    const invert = document.getElementById('wz-invert')?.value === 'true';
    const isTrigger = ['LEFT_TRIGGER', 'RIGHT_TRIGGER'].includes(surface);
    mapping = {
      source_type: 3,  // EV_ABS
      source_code: a.code,
      target: surface,
      kind: 'axis',
      source_min: srcMin,
      source_max: srcMax,
      target_min: isTrigger ? 0 : -32767,
      target_max: isTrigger ? 255 : 32767,
    };
    if (deadzone > 0) mapping.deadzone = deadzone;
    if (invert) mapping.invert = true;
  }

  if (label) mapping.label = label;

  profiles[selectedProfile].mappings.push(mapping);
  renderMappingsTable(profiles[selectedProfile].mappings);
  saveConfig();
  closeWizard();
}

// ── Config tab ────────────────────────────────────────────────
document.getElementById('btn-save-runtime').addEventListener('click', saveRuntimeSettings);

async function saveRuntimeSettings() {
  try {
    const cfg = await apiFetch('/api/config') ?? { runtime: {}, devices: [] };
    cfg.runtime = cfg.runtime ?? {};
    cfg.runtime.output_mode = document.getElementById('cfg-output-mode').value;
    cfg.runtime.interfaces = parseInt(document.getElementById('cfg-interfaces').value);
    cfg.runtime.poll_interval_ms = parseInt(document.getElementById('cfg-poll-interval').value);
    cfg.runtime.rescan_interval_ms = parseInt(document.getElementById('cfg-rescan').value);
    const gadgetLib = document.getElementById('cfg-gadget-library').value.trim();
    if (gadgetLib) cfg.runtime.gadget_library = gadgetLib;
    const gadgetDriver = document.getElementById('cfg-gadget-driver').value.trim();
    cfg.runtime.gadget_driver = gadgetDriver || null;
    const gadgetDevice = document.getElementById('cfg-gadget-device').value.trim();
    cfg.runtime.gadget_device = gadgetDevice || null;
    cfg.runtime.rumble = document.getElementById('cfg-rumble').value === 'true';
    cfg.runtime.rumble_timeout_s = parseFloat(document.getElementById('cfg-rumble-timeout').value);
    cfg.runtime.rumble_heartbeat_s = parseFloat(document.getElementById('cfg-rumble-heartbeat').value);
    cfg.runtime.rumble_stop_debounce_s = parseFloat(document.getElementById('cfg-rumble-debounce').value);
    cfg.runtime.rumble_activate_count = parseInt(document.getElementById('cfg-rumble-activate-count').value);
    cfg.runtime.rumble_activate_window_s = parseFloat(document.getElementById('cfg-rumble-activate-window').value);
    await putConfig(cfg);
    showToast('Runtime settings saved');
  } catch (e) {
    console.error('saveRuntimeSettings failed:', e);
    showToast(`Save failed: ${e.message}`, 'error');
  }
}

async function putConfig(cfg) {
  const r = await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error(`PUT /api/config failed: ${r.status}`);
}

async function saveConfig() {
  try {
    const cfg = await apiFetch('/api/config') ?? { runtime: { output_mode: 'stdout' }, devices: [] };
    cfg.devices = profiles;
    await putConfig(cfg);
    showToast('Config saved');
  } catch (e) {
    console.error('saveConfig failed:', e);
    showToast(`Save failed: ${e.message}`, 'error');
  }
}

document.getElementById('btn-export').addEventListener('click', () => {
  window.location.href = '/api/config/export';
});

document.getElementById('import-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/api/config/import', { method: 'POST', body: fd });
    if (!r.ok) throw new Error(`Import failed: ${r.status}`);
    showToast('Config imported');
    loadConfig();
  } catch (err) {
    showToast(`Import failed: ${err.message}`, 'error');
  }
  e.target.value = '';
});

document.getElementById('btn-restart-service').addEventListener('click', async () => {
  if (!confirm('Restart the service? This will briefly disconnect all controllers.')) return;
  await apiFetch('/api/service/restart', { method: 'POST' });
});

document.getElementById('btn-clear-config').addEventListener('click', async () => {
  if (!confirm('Clear all config?')) return;
  await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ runtime: { output_mode: 'stdout' }, devices: [] }),
  });
  profiles = [];
  selectedProfile = null;
  renderProfileList();
  renderProfileEditor();
});

async function populateConfigTab() {
  try {
    const cfg = await apiFetch('/api/config');
    if (!cfg?.runtime) return;
    const rt = cfg.runtime;
    document.getElementById('cfg-output-mode').value = rt.output_mode ?? 'stdout';
    document.getElementById('cfg-interfaces').value = rt.interfaces ?? 1;
    document.getElementById('cfg-poll-interval').value = rt.poll_interval_ms ?? 1;
    document.getElementById('cfg-rescan').value = rt.rescan_interval_ms ?? 2000;
    document.getElementById('cfg-gadget-library').value = rt.gadget_library ?? '';
    document.getElementById('cfg-gadget-driver').value = rt.gadget_driver ?? '';
    document.getElementById('cfg-gadget-device').value = rt.gadget_device ?? '';
    document.getElementById('cfg-rumble').value = rt.rumble ? 'true' : 'false';
    document.getElementById('cfg-rumble-timeout').value = rt.rumble_timeout_s ?? 0.5;
    document.getElementById('cfg-rumble-heartbeat').value = rt.rumble_heartbeat_s ?? 0.05;
    document.getElementById('cfg-rumble-debounce').value = rt.rumble_stop_debounce_s ?? 0.4;
    document.getElementById('cfg-rumble-activate-count').value = rt.rumble_activate_count ?? 2;
    document.getElementById('cfg-rumble-activate-window').value = rt.rumble_activate_window_s ?? 4.0;
  } catch (e) {
    console.error('populateConfigTab failed:', e);
  }
}

// ── Presets ───────────────────────────────────────────────────
let _allPresets = [];

document.getElementById('btn-open-presets').addEventListener('click', () => {
  if (selectedProfile === null) return;
  document.getElementById('preset-overlay').classList.add('open');
  document.getElementById('preset-search').value = '';
  document.getElementById('preset-show-all').checked = false;
  _loadPresetList();
});

document.getElementById('preset-close').addEventListener('click', () => {
  document.getElementById('preset-overlay').classList.remove('open');
});

document.getElementById('preset-search').addEventListener('input', () => _renderPresetList());
document.getElementById('preset-show-all').addEventListener('change', () => _renderPresetList());

function _presetRelevantToDevice(preset, deviceName) {
  if (!deviceName || !preset.match?.name) return true;
  const d = deviceName.toLowerCase();
  const words = preset.match.name.toLowerCase().split(/\s+/).filter(w => w.length > 2);
  return words.some(w => d.includes(w));
}

async function _loadPresetList() {
  const list = document.getElementById('preset-list');
  list.innerHTML = '<p class="dim" style="padding:.25rem 0">Loading…</p>';
  try {
    _allPresets = await apiFetch('/api/presets') ?? [];
    if (!_allPresets.length) {
      list.innerHTML = '<p class="dim" style="padding:.25rem 0">No presets found. Add .yaml files to a <code>presets/</code> folder next to your config file.</p>';
      document.getElementById('preset-filter-label').style.display = 'none';
      return;
    }
    // Show filter toggle only when there are irrelevant presets to hide
    const deviceName = selectedProfile !== null
      ? (Object.values(profiles[selectedProfile]?.match || {}))[0] || ''
      : '';
    const hasIrrelevant = deviceName && _allPresets.some(p => !_presetRelevantToDevice(p, deviceName));
    document.getElementById('preset-filter-label').style.display = hasIrrelevant ? '' : 'none';
    _renderPresetList();
  } catch (e) {
    list.innerHTML = `<p class="dim">Error: ${escapeHtml(e.message)}</p>`;
  }
}

function _renderPresetList() {
  const list = document.getElementById('preset-list');
  const query = document.getElementById('preset-search').value.trim().toLowerCase();
  const showAll = document.getElementById('preset-show-all').checked;
  const deviceName = selectedProfile !== null
    ? (Object.values(profiles[selectedProfile]?.match || {}))[0] || ''
    : '';

  const filtered = _allPresets.filter(p => {
    if (!showAll && !_presetRelevantToDevice(p, deviceName)) return false;
    if (query) {
      const haystack = (p.display_name + ' ' + (p.match?.name || '')).toLowerCase();
      return haystack.includes(query);
    }
    return true;
  });

  if (!filtered.length) {
    list.innerHTML = '<p class="dim" style="padding:.25rem 0">No matching presets.</p>';
    return;
  }

  list.innerHTML = '';
  filtered.forEach(p => {
    const item = document.createElement('div');
    item.className = 'preset-item';
    const matchNote = p.match?.name
      ? `<div class="preset-item-match">${escapeHtml(p.match.name)}</div>` : '';
    item.innerHTML = `
      <div>
        <div class="preset-item-name">${escapeHtml(p.display_name)}</div>
        ${matchNote}
      </div>
      <button class="btn secondary" style="padding:0 .6rem;font-size:.8rem;flex-shrink:0">Apply</button>`;
    item.querySelector('button').addEventListener('click', () => _applyPreset(p.name, p.display_name));
    list.appendChild(item);
  });
}

async function _applyPreset(name, displayName) {
  if (selectedProfile === null) return;
  if (!confirm(`Replace mappings in current profile with "${displayName}"?`)) return;
  try {
    const preset = await apiFetch(`/api/presets/${encodeURIComponent(name)}`);
    if (!preset) return;
    profiles[selectedProfile].mappings = preset.mappings || [];
    renderMappingsTable(profiles[selectedProfile].mappings);
    document.getElementById('preset-overlay').classList.remove('open');
    saveConfig();
  } catch (e) {
    showToast(`Failed to apply preset: ${e.message}`, 'error');
  }
}

// Normalise a mapping from either wizard (flat) or server (nested transform) to flat preset format
function _flattenMapping(m) {
  if (!m.transform) return m;
  const { transform, ...rest } = m;
  const flat = { ...rest, kind: transform.kind };
  if (transform.deadzone) flat.deadzone = transform.deadzone;
  if (transform.invert) flat.invert = transform.invert;
  if (transform.on_value != null) flat.on_value = transform.on_value;
  if (transform.off_value != null) flat.off_value = transform.off_value;
  if (transform.source_min != null) flat.source_min = transform.source_min;
  if (transform.source_max != null) flat.source_max = transform.source_max;
  if (transform.target_min != null) flat.target_min = transform.target_min;
  if (transform.target_max != null) flat.target_max = transform.target_max;
  return flat;
}

document.getElementById('preset-save-btn').addEventListener('click', async () => {
  if (selectedProfile === null) return;
  const p = profiles[selectedProfile];
  const nameInput = document.getElementById('preset-name-input');
  const displayName = nameInput.value.trim();
  if (!displayName) { nameInput.focus(); return; }
  const slug = displayName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const preset = {
    display_name: displayName,
    match: p.match || {},
    mappings: (p.mappings || []).map(_flattenMapping),
  };
  try {
    const r = await fetch(`/api/presets/${encodeURIComponent(slug)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preset),
    });
    if (!r.ok) throw new Error(`${r.status}`);
    showToast(`Preset "${displayName}" saved`);
    nameInput.value = '';
    _loadPresetList();
  } catch (e) {
    showToast(`Failed to save preset: ${e.message}`, 'error');
  }
});

// ── Splash ───────────────────────────────────────────────────
document.getElementById('splash')?.addEventListener('animationend', function (e) {
  if (e.animationName === 'splash-out') this.remove();
});

// ── Field tooltips ───────────────────────────────────────────
const _tip = document.createElement('div');
_tip.id = 'field-tooltip';
document.body.appendChild(_tip);

document.addEventListener('mouseover', (e) => {
  const field = e.target.closest('.field[data-tip]');
  if (!field) { _tip.style.display = 'none'; return; }
  _tip.textContent = field.dataset.tip;
  _tip.style.display = 'block';
  const r = field.getBoundingClientRect();
  let left = r.left;
  const top = r.bottom + 6;
  if (left + _tip.offsetWidth > window.innerWidth - 8)
    left = window.innerWidth - _tip.offsetWidth - 8;
  if (left < 8) left = 8;
  _tip.style.left = left + 'px';
  _tip.style.top = top + 'px';
});

document.addEventListener('mouseover', (e) => {
  if (!e.target.closest('.field[data-tip]')) _tip.style.display = 'none';
});

// ── Initialise ────────────────────────────────────────────────
loadDevices();
loadConfig();
populateConfigTab();
