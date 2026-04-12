const demoData = {
  runtimeStatus: "running",
  devices: [
    {
      path: "/dev/input/event1",
      name: "Xbox Wireless Controller",
      composite: "—",
      status: "bound",
      boundProfile: "Xbox Controller",
      hasFf: true,
    },
    {
      path: "/dev/input/event2",
      name: "Nintendo Wii Remote",
      composite: "parent",
      status: "bound",
      boundProfile: "wiimote-rocket-league",
      hasFf: true,
    },
    {
      path: "/dev/input/event3",
      name: "Nintendo Wii Remote Nunchuk",
      composite: "child",
      status: "bound",
      boundProfile: "nunchuk-rocket-league",
      hasFf: false,
    },
    {
      path: "/dev/input/event6",
      name: "8BitDo SN30 Pro",
      composite: "—",
      status: "unbound",
      boundProfile: "",
      hasFf: true,
    },
  ],
  pairedDevices: [
    { name: "Xbox Wireless Controller", mac: "7C:BB:8A:21:50:11", connected: true },
    { name: "Nintendo Wii Remote", mac: "00:25:A0:D1:CA:93", connected: true },
    { name: "8BitDo SN30 Pro", mac: "E4:17:D8:55:12:AF", connected: false },
  ],
  profiles: [
    {
      id: "Xbox Controller",
      matchKey: "name",
      matchValue: "Xbox Wireless Controller",
      connType: "evdev",
      mac: "",
      slot: "0",
      rumble: "true",
      mappings: [
        {
          source_type: 1,
          source_code: 304,
          kind: "button",
          label: "A",
          target: "A",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 305,
          kind: "button",
          label: "B",
          target: "B",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 307,
          kind: "button",
          label: "X",
          target: "X",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 308,
          kind: "button",
          label: "Y",
          target: "Y",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 310,
          kind: "button",
          label: "LB",
          target: "BUMPER_L",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 311,
          kind: "button",
          label: "RB",
          target: "BUMPER_R",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 315,
          kind: "button",
          label: "Menu",
          target: "START",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 314,
          kind: "button",
          label: "View",
          target: "OPTIONS",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 316,
          kind: "button",
          label: "Xbox",
          target: "XBOX",
          live: "button",
        },
        {
          source_type: 3,
          source_code: 16,
          kind: "hat",
          label: "D-Pad X",
          target: "DPAD_LEFT",
          on_value: -1,
          live: "button",
        },
        {
          source_type: 3,
          source_code: 16,
          kind: "hat",
          label: "D-Pad X",
          target: "DPAD_RIGHT",
          on_value: 1,
          live: "button",
        },
        {
          source_type: 3,
          source_code: 17,
          kind: "hat",
          label: "D-Pad Y",
          target: "DPAD_UP",
          on_value: -1,
          live: "button",
        },
        {
          source_type: 3,
          source_code: 17,
          kind: "hat",
          label: "D-Pad Y",
          target: "DPAD_DOWN",
          on_value: 1,
          live: "button",
        },
        {
          source_type: 3,
          source_code: 0,
          label: "Left Stick X",
          kind: "button",
          target: "LEFT_JOYSTICK_X",
          on_value: 32767,
          off_value: 0,
          live: "axis",
        },
        {
          source_type: 3,
          source_code: 1,
          kind: "button",
          label: "Left Stick Y",
          target: "LEFT_JOYSTICK_Y",
          on_value: 32767,
          off_value: 0,
          live: "axis",
        },
        {
          source_type: 3,
          source_code: 2,
          kind: "button",
          label: "Right Stick X",
          target: "RIGHT_JOYSTICK_X",
          live: "axis",
        },
        {
          source_type: 3,
          source_code: 5,
          kind: "button",
          label: "Right Stick Y",
          target: "RIGHT_JOYSTICK_Y",
          on_value: 32767,
          off_value: 0,
          live: "axis",
        },
        {
          source_type: 3,
          source_code: 10,
          kind: "button",
          label: "LT",
          target: "LEFT_TRIGGER",
          live: "button",
        },
        {
          source_type: 3,
          source_code: 9,
          kind: "button",
          label: "RT",
          target: "RIGHT_TRIGGER",
          live: "button",
        },
      ],
    },
    {
      id: "wiimote-rocket-league",
      matchKey: "name",
      matchValue: "Nintendo Wii Remote",
      connType: "wiimote",
      mac: "00:25:A0:D1:CA:93",
      slot: "0",
      rumble: "true",
      mappings: [
        {
          source_type: 1,
          source_code: 304,
          kind: "button",
          label: "Jump",
          target: "A",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 305,
          kind: "button",
          label: "Throttle",
          target: "RIGHT_TRIGGER",
          on_value: 255,
          off_value: 0,
          live: "button",
        },
        {
          source_type: 1,
          source_code: 407,
          kind: "button",
          label: "Menu",
          target: "START",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 412,
          kind: "button",
          label: "Back",
          target: "OPTIONS",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 316,
          kind: "button",
          label: "Guide",
          target: "XBOX",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 108,
          kind: "button",
          label: "Boost",
          target: "B",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 257,
          kind: "button",
          label: "Ball Cam",
          target: "X",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 103,
          kind: "button",
          label: "D-Pad Up",
          target: "DPAD_UP",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 105,
          kind: "button",
          label: "D-Pad Left",
          target: "DPAD_LEFT",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 106,
          kind: "button",
          label: "D-Pad Right",
          target: "DPAD_RIGHT",
          live: "button",
        },
        {
          source_type: 1,
          source_code: 258,
          kind: "button",
          label: "D-Pad Down",
          target: "DPAD_DOWN",
          live: "button",
        },
      ],
    },
    {
      id: "nunchuk-rocket-league",
      matchKey: "name",
      matchValue: "Nintendo Wii Remote Nunchuk",
      connType: "evdev",
      mac: "",
      slot: "0",
      rumble: "true",
      mappings: [
        {
          source_type: 1,
          source_code: 309,
          kind: "button",
          label: "Brake",
          target: "LEFT_TRIGGER",
          on_value: 255,
          off_value: 0,
          live: "button",
        },
        {
          source_type: 1,
          source_code: 306,
          kind: "button",
          label: "Handbrake",
          target: "Y",
          live: "button",
        },
        {
          source_type: 3,
          source_code: 16,
          kind: "axis",
          label: "Stick X",
          target: "LEFT_JOYSTICK_X",
          source_min: -90,
          source_max: 111,
          deadzone: 0.10,
          live: "axis",
        },
        {
          source_type: 3,
          source_code: 17,
          kind: "axis",
          label: "Stick Y",
          target: "LEFT_JOYSTICK_Y",
          source_min: -104,
          source_max: 95,
          deadzone: 0.10,
          live: "axis",
        },
      ],
    },
    {
      id: "tv-remote",
      matchKey: "name",
      matchValue: "Nintendo Wii Remote",
      connType: "wiimote",
      mac: "00:25:A0:D1:CA:93",
      slot: "0",
      rumble: "false",
      mappings: [
        {
          source_type: 3,
          source_code: 16,
          kind: "hat",
          label: "D-Pad X",
          target: "DPAD_LEFT",
          on_value: -1,
          live: "button",
        },
        {
          source_type: 3,
          source_code: 16,
          kind: "hat",
          label: "D-Pad X",
          target: "DPAD_RIGHT",
          on_value: 1,
          live: "button",
        },
        {
          source_type: 1,
          source_code: 2,
          kind: "button",
          label: "Button 1",
          target: "A",
          live: "button",
        },
      ],
    },
  ],
  runtimeConfig: {
    output_mode: "gadget",
    interfaces: 1,
    poll_interval_ms: 1,
    rescan_interval_ms: 2000,
    rumble: "true",
    rumble_timeout_s: 0.5,
    rumble_heartbeat_s: 0.05,
    rumble_stop_debounce_s: 0.4,
    rumble_activate_count: 2,
    rumble_activate_window_s: 4.0,
    gadget_library: "360-w-raw-gadget/target/release/libx360_w_raw_gadget.so",
    gadget_driver: "",
    gadget_device: "",
  },
};

let selectedProfileId = demoData.profiles[0].id;
let toastTimer = null;

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(msg, type = "ok") {
  const el = byId("toast");
  el.textContent = msg;
  el.className = type === "error" ? "error" : "";
  void el.offsetWidth;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("demo-theme", theme);
}

function setupTheme() {
  applyTheme(localStorage.getItem("demo-theme") || "dark");
  byId("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    applyTheme(next);
  });
}

function setupTabs() {
  document.querySelectorAll("nav button[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      document.querySelectorAll("nav button[data-tab]").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((t) => t.classList.remove("active"));
      btn.classList.add("active");
      byId(`tab-${target}`).classList.add("active");
    });
  });
}

function setRuntimeStatus(status) {
  const dot = byId("runtime-dot");
  const label = byId("runtime-label");
  dot.className = `status-dot ${status === "running" ? "running" : "stopped"}`;
  label.textContent = status;
}

function renderDevices() {
  const tbody = byId("devices-tbody");
  tbody.innerHTML = demoData.devices
    .map((d) => {
      const badgeClass = d.status === "bound" ? "bound" : d.status === "pending" ? "pending" : "unbound";
      const buzz = d.boundProfile && d.hasFf
        ? `<button class="btn secondary demo-buzz" data-profile="${escapeHtml(d.boundProfile)}">buzz</button>`
        : `<button class="btn secondary" disabled>buzz</button>`;
      return `
        <tr>
          <td>${escapeHtml(d.path)}</td>
          <td>${escapeHtml(d.name)}</td>
          <td>${escapeHtml(d.composite)}</td>
          <td><span class="badge ${badgeClass}">${escapeHtml(d.boundProfile || d.status)}</span></td>
          <td>${buzz}</td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll(".demo-buzz").forEach((btn) => {
    btn.addEventListener("click", () => showToast(`Demo only: would buzz ${btn.dataset.profile}`));
  });
}

function renderPairedDevices() {
  const tbody = byId("paired-tbody");
  tbody.innerHTML = demoData.pairedDevices
    .map((d) => {
      const status = d.connected
        ? '<span class="badge bound">connected</span>'
        : '<span class="badge unbound">remembered</span>';
      return `
        <tr>
          <td>${escapeHtml(d.name)}</td>
          <td class="dim" style="font-size:.85rem">${escapeHtml(d.mac)}</td>
          <td>${status}</td>
          <td style="display:flex;gap:.25rem">
            <button class="btn secondary demo-action">Disconnect</button>
            <button class="btn danger demo-action">Unpair</button>
          </td>
        </tr>
      `;
    })
    .join("");

  bindGenericDemoActions(tbody);
}

function profileSlotLabel(slot) {
  return `Slot ${Number(slot) + 1}`;
}

function renderProfileList() {
  const list = byId("profile-list");
  list.innerHTML = demoData.profiles
    .map((p) => `
      <li class="${p.id === selectedProfileId ? "active" : ""}" style="margin-bottom:.5rem">
        <button class="btn secondary profile-select" data-profile="${escapeHtml(p.id)}" style="width:100%;text-align:left">
          ${escapeHtml(p.id)}
        </button>
      </li>
    `)
    .join("");

  list.querySelectorAll(".profile-select").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedProfileId = btn.dataset.profile;
      renderProfileList();
      renderSelectedProfile();
    });
  });
}

function renderSelectedProfile() {
  const profile = demoData.profiles.find((p) => p.id === selectedProfileId);
  if (!profile) return;

  byId("no-profile-msg").style.display = "none";
  byId("profile-editor").style.display = "";
  byId("profile-editor-title").textContent = profile.id;
  byId("profile-id-input").value = profile.id;
  byId("picked-device-label").textContent = `${profile.matchKey}: ${profile.matchValue}`;
  byId("profile-match-key").value = profile.matchKey;
  byId("profile-match-val").value = profile.matchValue;
  byId("profile-conn-type").value = profile.connType;
  byId("profile-mac").value = profile.mac;
  byId("profile-slot").value = profile.slot;
  byId("profile-rumble").value = profile.rumble;
  byId("profile-mac-field").style.display = profile.connType === "evdev" ? "none" : "";

  const tbody = byId("mappings-tbody");
  tbody.innerHTML = profile.mappings
    .map((m) => {
      const srcCode = `${m.source_type === 1 ? "EV_KEY" : "EV_ABS"} ${m.source_code}`;
      const srcCell = m.label
        ? `${escapeHtml(m.label)}<span class="dim" style="font-size:.75rem;display:block">${escapeHtml(srcCode)}</span>`
        : escapeHtml(srcCode);
      const extras = [];
      if (m.source_min != null) extras.push(`src:${m.source_min}..${m.source_max}`);
      if (m.deadzone) extras.push(`dz=${escapeHtml(m.deadzone)}`);
      if (m.invert) extras.push("↕inv");
      const liveCell = m.live === "axis"
        ? '<div class="live-axis-track"><div style="width:48%;height:100%;background:var(--accent)"></div></div>'
        : '<span class="live-btn live-flash"></span>';
      return `
        <tr>
          <td>${srcCell}</td>
          <td>${escapeHtml(m.kind)}</td>
          <td>${escapeHtml(m.target)}</td>
          <td class="dim">${extras.join(" ")}</td>
          <td>${liveCell}</td>
          <td><button class="btn secondary demo-action">edit</button></td>
        </tr>
      `;
    })
    .join("");

  bindGenericDemoActions(tbody);
}

function renderRuntimeConfig() {
  const cfg = demoData.runtimeConfig;
  byId("cfg-output-mode").value = cfg.output_mode;
  byId("cfg-interfaces").value = cfg.interfaces;
  byId("cfg-poll-interval").value = cfg.poll_interval_ms;
  byId("cfg-rescan").value = cfg.rescan_interval_ms;
  byId("cfg-rumble").value = cfg.rumble;
  byId("cfg-rumble-timeout").value = cfg.rumble_timeout_s;
  byId("cfg-rumble-heartbeat").value = cfg.rumble_heartbeat_s;
  byId("cfg-rumble-debounce").value = cfg.rumble_stop_debounce_s;
  byId("cfg-rumble-activate-count").value = cfg.rumble_activate_count;
  byId("cfg-rumble-activate-window").value = cfg.rumble_activate_window_s;
  byId("cfg-gadget-library").value = cfg.gadget_library;
  byId("cfg-gadget-driver").value = cfg.gadget_driver;
  byId("cfg-gadget-device").value = cfg.gadget_device;
}

function shuffleDeviceStatuses() {
  const next = { bound: "unbound", unbound: "pending", pending: "bound" };
  demoData.devices = demoData.devices.map((device) => ({
    ...device,
    status: next[device.status] || "bound",
    boundProfile: next[device.status] === "bound"
      ? (
        device.name === "Xbox Wireless Controller"
          ? "Xbox Controller"
          : device.name === "Nintendo Wii Remote Nunchuk"
            ? "nunchuk-rocket-league"
            : "wiimote-rocket-league"
      )
      : device.status === "bound"
        ? ""
        : device.boundProfile,
  }));
  renderDevices();
  showToast("Demo only: shuffled sample device states");
}

function setupDemoActions() {
  byId("btn-refresh-devices").addEventListener("click", shuffleDeviceStatuses);
  byId("btn-bt-scan").addEventListener("click", () => showToast("Demo only: would scan for Bluetooth devices"));
  byId("btn-refresh-paired").addEventListener("click", () => showToast("Demo only: paired list is static"));
  byId("btn-pick-device").addEventListener("click", () => showToast("Demo only: device picker disabled"));
  byId("btn-add-profile").addEventListener("click", () => showToast("Demo only: profile creation disabled"));
  byId("btn-save-profile").addEventListener("click", () => showToast("Demo only: profile edits are not persisted"));
  byId("btn-delete-profile").addEventListener("click", () => showToast("Demo only: delete disabled"));
  byId("btn-add-mapping").addEventListener("click", () => showToast("Demo only: mapping wizard disabled"));
  byId("btn-open-presets").addEventListener("click", () => showToast("Demo only: presets are shown in the static sample"));
  byId("btn-save-runtime").addEventListener("click", () => showToast("Demo only: runtime settings are not persisted"));
  byId("btn-export").addEventListener("click", () => showToast("Demo only: export disabled"));
  byId("import-file").addEventListener("click", (e) => {
    e.preventDefault();
    showToast("Demo only: import disabled");
  });
  byId("btn-restart-service").addEventListener("click", () => {
    demoData.runtimeStatus = demoData.runtimeStatus === "running" ? "stopped" : "running";
    setRuntimeStatus(demoData.runtimeStatus);
    showToast(`Demo only: sample runtime is now ${demoData.runtimeStatus}`);
  });
  byId("btn-clear-config").addEventListener("click", () => showToast("Demo only: clear config disabled", "error"));
  byId("wizard-cancel").addEventListener("click", () => showToast("Demo only: wizard hidden"));
  byId("wizard-confirm").addEventListener("click", () => showToast("Demo only: wizard confirm disabled"));
  byId("preset-close").addEventListener("click", () => showToast("Demo only: preset overlay hidden"));
  byId("preset-save-btn").addEventListener("click", () => showToast("Demo only: preset save disabled"));

  document.querySelectorAll('input, select').forEach((el) => {
    if (el.id === "import-file") return;
    el.addEventListener("change", () => showToast("Demo only: local edits are not persisted"));
  });
}

function bindGenericDemoActions(root = document) {
  root.querySelectorAll(".demo-action").forEach((btn) => {
    btn.addEventListener("click", () => showToast("Demo only: action disabled"));
  });
}

function init() {
  setupTabs();
  setupTheme();
  setRuntimeStatus(demoData.runtimeStatus);
  renderDevices();
  renderPairedDevices();
  renderProfileList();
  renderSelectedProfile();
  renderRuntimeConfig();
  setupDemoActions();
  bindGenericDemoActions();
}

init();
