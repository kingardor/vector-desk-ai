/**
 * Vector Companion — Frontend v3
 * Drives avatar state machine, conversation timeline, WebSocket connection.
 * Camera always visible in avatar panel — no toggle logic needed.
 */

"use strict";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const timeline    = document.getElementById("timeline");
const tlEmpty     = document.getElementById("tl-empty");
const tlHint      = document.getElementById("tl-hint");
const textInput   = document.getElementById("text-input");
const sendBtn     = document.getElementById("send-btn");
const statusDot   = document.getElementById("status-dot");
const statusChip  = document.getElementById("status-chip");
const connDot     = document.getElementById("conn-dot");
const connLabel   = document.getElementById("conn-label");
const avatar      = document.getElementById("avatar");
const avatarPanel = document.getElementById("avatar-panel");
const avatarGlow  = document.getElementById("avatar-glow");
const btnWake     = document.getElementById("btn-wake");
const btnSleep    = document.getElementById("btn-sleep");
const btnMute     = document.getElementById("btn-mute");
const btnReset    = document.getElementById("btn-reset");

// Sensor strip
const batFill      = document.getElementById("bat-fill");
const batLabel     = document.getElementById("bat-label");
const batIcon      = document.getElementById("bat-icon");
const sensorTouch  = document.getElementById("sensor-touch");
const pillCharging = document.getElementById("pill-charging");
const pillCharger  = document.getElementById("pill-charger");
const pillPickedup = document.getElementById("pill-pickedup");
const pillCliff    = document.getElementById("pill-cliff");

// ── State ─────────────────────────────────────────────────────────────────────
let ws               = null;
let isConnected      = false;
let avatarState      = "idle";
let micMuted         = false;
let currentVectorRow = null;
let blinkTimer       = null;

// ── Ambient glow per emotional state ──────────────────────────────────────────
// bg = panel background tint, glo = close glow behind eyes
const AMBIENT = {
  angry:        { bg: "rgba(255,77,106,0.07)",   glo: "rgba(255,77,106,0.40)" },
  happy:        { bg: "rgba(0,255,132,0.05)",    glo: "rgba(0,255,132,0.38)" },
  celebrate:    { bg: "rgba(0,255,132,0.07)",    glo: "rgba(0,255,132,0.44)" },
  excited:      { bg: "rgba(167,139,250,0.06)",  glo: "rgba(167,139,250,0.38)" },
  sad:          { bg: "rgba(96,165,250,0.05)",   glo: "rgba(96,165,250,0.30)" },
  surprised:    { bg: "rgba(251,191,36,0.06)",   glo: "rgba(251,191,36,0.36)" },
  curious:      { bg: "rgba(34,211,238,0.05)",   glo: "rgba(34,211,238,0.34)" },
  confused:     { bg: "rgba(251,146,60,0.05)",   glo: "rgba(251,146,60,0.32)" },
  sleepy:       { bg: "rgba(42,74,107,0.04)",    glo: "rgba(42,74,107,0.20)" },
  bored:        { bg: "rgba(96,105,122,0.03)",   glo: "rgba(96,105,122,0.18)" },
  love:         { bg: "rgba(244,114,182,0.05)",  glo: "rgba(244,114,182,0.34)" },
  scared:       { bg: "rgba(129,140,248,0.05)",  glo: "rgba(129,140,248,0.32)" },
  laugh:        { bg: "rgba(74,222,128,0.05)",   glo: "rgba(74,222,128,0.34)" },
  refuse:       { bg: "rgba(251,146,60,0.05)",   glo: "rgba(251,146,60,0.32)" },
  disappointed: { bg: "rgba(148,163,184,0.04)",  glo: "rgba(148,163,184,0.22)" },
  listening:    { bg: "rgba(240,96,255,0.05)",   glo: "rgba(240,96,255,0.36)" },
  thinking:     { bg: "rgba(155,32,184,0.05)",   glo: "rgba(155,32,184,0.30)" },
  speaking:     { bg: "rgba(224,64,251,0.05)",   glo: "rgba(224,64,251,0.32)" },
  _default:     { bg: "rgba(224,64,251,0.04)",   glo: "rgba(224,64,251,0.28)" },
};

// ── WebSocket ──────────────────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen  = () => { isConnected = true;  setConn(true); };
  ws.onclose = () => { isConnected = false; setConn(false); setTimeout(connect, 2000); };
  ws.onmessage = ({ data }) => {
    try { handleEvent(JSON.parse(data)); }
    catch (e) { console.warn("WS parse error", e); }
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// ── Event handler ──────────────────────────────────────────────────────────────
function handleEvent(ev) {
  switch (ev.type) {

    case "state":
      setVectorState(ev.state);
      break;

    case "user_message":
      closeVectorRow();
      addUserBubble(ev.text, ev.source === "web" ? "You" : "You (voice)");
      hideTlEmpty();
      break;

    case "vector_reply_start":
      currentVectorRow = null;
      break;

    case "segment_start":
      onSegmentStart(ev);
      break;

    case "segment_done":
      onSegmentDone(ev);
      break;

    case "vector_reply_done":
      closeVectorRow();
      break;

    case "sensors":
      updateSensors(ev);
      break;

    case "reset":
      clearTimeline();
      setVectorState("idle");
      break;

    case "mute":
      micMuted = ev.muted;
      btnMute.classList.toggle("active-state", micMuted);
      swapIcon(btnMute, micMuted ? "mic-off" : "mic", micMuted ? "Muted" : "Mic");
      addSystemMsg(micMuted ? "Mic muted" : "Mic active");
      break;

    case "sleep":
      addSystemMsg("Vector sleeping");
      break;

    case "wake":
      addSystemMsg("Vector awake");
      break;
  }
}

// ── Segment lifecycle ─────────────────────────────────────────────────────────
function onSegmentStart(ev) {
  const { kind, value, label, params } = ev;

  if (kind === "speech") {
    ensureVectorRow();
    appendSpeechToRow(value);
    setAvatarState("speaking");

  } else if (kind === "emote") {
    closeVectorRow();
    addActionChip("emote", label, params.chip_color || "#34D399");
    setAvatarState(params.css_state || "neutral");

  } else if (kind === "motion") {
    closeVectorRow();
    addActionChip("motion", label, "#FCA21A");

  } else if (kind === "look") {
    closeVectorRow();
    addActionChip("look", "Looking", "#22D3EE");
    setAvatarState("curious");
  }
}

function onSegmentDone(ev) {
  if (ev.kind === "emote") setAvatarState("speaking");
}

// ── Avatar state machine ──────────────────────────────────────────────────────
const SERVER_STATES = {
  waiting: "waiting", listening: "listening",
  thinking: "thinking", speaking: "speaking",
};

function setVectorState(serverState) {
  setAvatarState(SERVER_STATES[serverState] || serverState);
  updateStatusChip(serverState);
}

function setAvatarState(state) {
  if (avatarState === state) return;
  avatarState = state;
  avatar.dataset.state = state;

  const glo = AMBIENT[state] || AMBIENT._default;
  avatarGlow.style.background = glo.glo;
  avatarPanel.style.setProperty("--ambient-color", glo.bg);

  updateStatusChip(state);
}

function updateStatusChip(state) {
  const labels = {
    waiting: "waiting", listening: "listening", thinking: "thinking…",
    speaking: "speaking", idle: "ready", neutral: "ready",
    happy: "happy", angry: "angry", sad: "sad", excited: "excited",
    curious: "curious", confused: "confused", surprised: "surprised",
    sleepy: "sleepy", bored: "bored", celebrate: "celebrate",
    love: "love", scared: "scared", laugh: "laugh",
    refuse: "refusing", disappointed: "disappointed",
  };
  statusChip.textContent = labels[state] || state;

  const active = ["listening", "thinking", "speaking"].includes(state);
  statusDot.classList.toggle("active", active);

  const hints = {
    waiting:   'Say "Vector" to start',
    listening: "Listening…",
    thinking:  "Thinking…",
    speaking:  "Speaking…",
  };
  tlHint.textContent = hints[state] || "";
}

// ── Blink engine ──────────────────────────────────────────────────────────────
const BLINKABLE = new Set(["idle", "listening", "neutral", "waiting", "speaking"]);

function scheduleBlink() {
  if (!BLINKABLE.has(avatarState)) {
    blinkTimer = setTimeout(scheduleBlink, 800);
    return;
  }
  const delay = 2500 + Math.random() * 2500;
  blinkTimer = setTimeout(() => {
    avatar.classList.add("blinking");
    setTimeout(() => {
      avatar.classList.remove("blinking");
      avatar.classList.add("blink-return");
      setTimeout(() => {
        avatar.classList.remove("blink-return");
        scheduleBlink();
      }, 110);
    }, 75);
  }, delay);
}

// ── Timeline builders ─────────────────────────────────────────────────────────
function hideTlEmpty() {
  if (tlEmpty) tlEmpty.style.display = "none";
}

function addUserBubble(text, senderName) {
  const item = document.createElement("div");
  item.className = "tl-item user";
  item.innerHTML =
    `<span class="sender-label">${esc(senderName)}</span>` +
    `<div class="bubble">${esc(text)}</div>`;
  timeline.appendChild(item);
  scrollBottom();
}

function ensureVectorRow() {
  if (!currentVectorRow) {
    const item = document.createElement("div");
    item.className = "tl-item vector speaking";
    item.innerHTML =
      `<span class="sender-label">Vector</span>` +
      `<div class="bubble" data-speech=""></div>`;
    timeline.appendChild(item);
    currentVectorRow = item;
    scrollBottom();
  }
}

function appendSpeechToRow(text) {
  if (!currentVectorRow) return;
  const bubble = currentVectorRow.querySelector("[data-speech]");
  if (!bubble) return;
  bubble.textContent = bubble.textContent ? bubble.textContent + " " + text : text;
  scrollBottom();
}

function closeVectorRow() {
  if (currentVectorRow) {
    currentVectorRow.classList.remove("speaking");
    currentVectorRow = null;
  }
}

function addActionChip(kind, label, color) {
  const item = document.createElement("div");
  item.className = "tl-item action";
  const chip = document.createElement("div");
  chip.className = `action-chip ${kind}`;
  chip.style.borderColor = color + "28";
  chip.style.color = color;
  chip.style.background = color + "0A";
  chip.innerHTML =
    `<span class="chip-dot" style="background:${color}"></span>${esc(label)}`;
  item.appendChild(chip);
  timeline.appendChild(item);
  scrollBottom();
}

function addSystemMsg(text) {
  const item = document.createElement("div");
  item.className = "tl-item system";
  item.innerHTML = `<span class="system-msg">— ${esc(text)} —</span>`;
  timeline.appendChild(item);
  scrollBottom();
}

function clearTimeline() {
  timeline.innerHTML = "";
  const empty = document.createElement("div");
  empty.id = "tl-empty";
  empty.className = "tl-empty";
  empty.innerHTML =
    `<div class="empty-icon"><i data-lucide="radio"></i></div>` +
    `<p class="empty-title">Conversation reset</p>` +
    `<p class="empty-sub">Say "Vector" or type below to begin</p>`;
  timeline.appendChild(empty);
  lucide.createIcons();
}

function scrollBottom() {
  requestAnimationFrame(() => { timeline.scrollTop = timeline.scrollHeight; });
}

// ── Connection state ───────────────────────────────────────────────────────────
function setConn(online) {
  connDot.className = "conn-dot " + (online ? "online" : "offline");
  connLabel.textContent = online ? "connected" : "reconnecting…";
}

// ── Icon swap (preserves sibling label text) ──────────────────────────────────
function swapIcon(btn, iconName, labelText) {
  const icon  = btn.querySelector("i[data-lucide]");
  const label = btn.querySelector(".ctrl-label");
  if (icon) {
    icon.setAttribute("data-lucide", iconName);
    lucide.createIcons();
  }
  if (label && labelText !== undefined) label.textContent = labelText;
}

// ── Input handling ────────────────────────────────────────────────────────────
function sendText() {
  const text = textInput.value.trim();
  if (!text) return;
  send({ type: "text_input", text });
  textInput.value = "";
}

sendBtn.addEventListener("click", sendText);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendText(); }
});

// ── Control buttons ───────────────────────────────────────────────────────────
btnWake.addEventListener("click",  () => send({ type: "wake" }));
btnSleep.addEventListener("click", () => send({ type: "sleep" }));
btnMute.addEventListener("click",  () => send({ type: "mute" }));
btnReset.addEventListener("click", () => {
  if (confirm("Reset conversation history?")) send({ type: "reset" });
});

// ── XSS helper ────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Sensor strip ──────────────────────────────────────────────────────────────
const BAT_LEVELS = ["", "low", "nominal", "full"];
const BAT_ICONS  = ["battery", "battery-low", "battery-medium", "battery-full"];
const BAT_LABELS = ["--", "LOW", "OK", "FULL"];
const BAT_PCT    = [0, 20, 65, 100];

function updateSensors(data) {
  // ── Battery ────────────────────────────────────────────────────────────────
  if (data.battery) {
    const { level, charging, on_charger } = data.battery;
    const lvl = Math.max(1, Math.min(3, level));
    const pct = charging ? 100 : BAT_PCT[lvl];

    batFill.style.width = pct + "%";
    batFill.className   = "bat-fill " + BAT_LEVELS[lvl];
    batLabel.textContent = charging ? "CHG" : BAT_LABELS[lvl];
    batIcon.setAttribute("data-lucide", charging ? "battery-charging" : BAT_ICONS[lvl]);
    lucide.createIcons({ nodes: [batIcon] });
  }

  // ── Touch ──────────────────────────────────────────────────────────────────
  if (data.touch) {
    const touched = data.touch.touched;
    sensorTouch.classList.toggle("active", touched);
    avatarPanel.classList.toggle("touched", touched);
  }

  // ── Status pills ───────────────────────────────────────────────────────────
  if (data.status) {
    const s = data.status;
    pillCharging.classList.toggle("active", s.charging);
    pillCharger.classList.toggle("active",  s.on_charger && !s.charging);
    pillPickedup.classList.toggle("active", s.picked_up || s.held);
    pillCliff.classList.toggle("active",    s.cliff);
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
connect();
scheduleBlink();
