// Client web SmartHome : connexion WebSocket à la passerelle, conversation en streaming,
// micro (voir recorder.js), confirmations des actions dangereuses et lecture de la voix.
import { Recorder, toBase64 } from "./recorder.js";

const $ = (id) => document.getElementById(id);
const ui = {
  log: $("log"), empty: $("empty"), status: $("status"),
  mic: $("mic"), textForm: $("text-form"), text: $("text"), send: document.querySelector(".send"),
  setup: $("setup"), setupForm: $("setup-form"), token: $("token"), setupError: $("setup-error"),
  settings: $("settings"), speak: $("speak"), autostop: $("autostop"), sessionId: $("session-id"),
  confirm: $("confirm"), confirmQuestion: $("confirm-question"), confirmBar: $("confirm-bar"),
};

// ---- Préférences locales (le stockage peut être indisponible : navigation privée...) ----
const store = {
  get(key, fallback = null) {
    try { return localStorage.getItem(`smarthome.${key}`) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try {
      if (value === null || value === undefined) localStorage.removeItem(`smarthome.${key}`);
      else localStorage.setItem(`smarthome.${key}`, value);
    } catch { /* préférence non persistée */ }
  },
};

const state = {
  ws: null,
  ready: false,
  busy: 0,                 // demandes en cours (chaque demande se termine par {"type": "done"})
  botBubble: null,         // bulle de réponse en cours de streaming
  pendingUser: null,       // bulle « audio envoyé » à remplacer par la transcription
  audioConfig: null,
  confirmTimeout: 20,
  reconnectDelay: 1000,
  recorder: null,
  audioCtx: null,
  playing: new Set(),      // sources audio programmées (voix de l'assistant)
  playHead: 0,             // instant de fin de la dernière phrase programmée
  decodeChain: Promise.resolve(),
  audioGeneration: 0,      // incrémenté à chaque arrêt : les phrases encore en décodage sont ignorées
};

// ---- Fil de conversation ----
function addBubble(kind, text) {
  ui.empty.hidden = true;
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.textContent = text;
  ui.log.append(el);
  scrollDown();
  return el;
}

function addToolChip(event) {
  const el = document.createElement("div");
  el.className = `tool ${event.executed ? "ok" : "refused"}`;
  const args = Object.values(event.arguments || {}).join(", ");
  el.textContent = `${event.executed ? "✓" : "✕"} ${event.name}${args ? ` (${args})` : ""}${event.executed ? "" : " — non exécuté"}`;
  el.title = event.output || "";
  ui.log.append(el);
  scrollDown();
}

function scrollDown() {
  ui.log.scrollTop = ui.log.scrollHeight;
}

function setStatus(stateName, label) {
  ui.status.dataset.state = stateName;
  ui.status.textContent = label;
}

function refreshControls() {
  const enabled = state.ready;
  ui.text.disabled = !enabled;
  ui.send.disabled = !enabled;
  ui.mic.disabled = !enabled;
  if (enabled) setStatus(state.busy ? "busy" : "online", state.busy ? "Réflexion…" : "Connecté");
}

// ---- Connexion ----
function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws`);
  state.ws = ws;
  setStatus("offline", "Connexion…");

  ws.addEventListener("open", () => {
    // Authentification par premier message (un navigateur ne peut pas envoyer d'en-tête Authorization)
    ws.send(JSON.stringify({ type: "auth", token: store.get("token", ""), session: store.get("session") }));
  });

  ws.addEventListener("message", (msg) => {
    let event;
    try { event = JSON.parse(msg.data); } catch { return; }
    handleEvent(event);
  });

  ws.addEventListener("close", (e) => {
    state.ready = false;
    state.busy = 0;
    refreshControls();
    if (e.code === 4401) {
      setStatus("offline", "Jeton requis");
      openSetup(store.get("token") ? "Ce jeton a été refusé par la passerelle." : "");
      return;
    }
    if (e.code === 4403) {
      setStatus("offline", "Jeton requis");
      addBubble("error", "Accès distant refusé : la passerelle n'a pas de jeton (GATEWAY_AUTH_TOKEN). Configurez-en un sur l'ordinateur.");
      return;
    }
    setStatus("offline", "Hors ligne");
    setTimeout(connect, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 2, 15000);
  });
}

function send(message) {
  if (state.ws?.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(message));
}

// ---- Événements du cœur ----
function handleEvent(event) {
  switch (event.type) {
    case "ready":
      state.ready = true;
      state.reconnectDelay = 1000;
      state.audioConfig = event.audio;
      state.confirmTimeout = event.confirm_timeout || 20;
      store.set("session", event.session);
      ui.sessionId.textContent = event.session;
      refreshControls();
      break;
    case "transcript":
      if (state.pendingUser) {
        state.pendingUser.textContent = event.text || "(rien compris)";
        state.pendingUser = null;
      } else {
        addBubble("user", event.text);
      }
      break;
    case "token":
      if (!state.botBubble) {
        state.botBubble = addBubble("bot pending", "");
      }
      state.botBubble.textContent += event.text;
      scrollDown();
      break;
    case "tool":
      // L'outil s'exécute pendant la réponse : la suite du texte part dans une nouvelle bulle
      if (state.botBubble && !state.botBubble.textContent.trim()) state.botBubble.remove();
      state.botBubble?.classList.remove("pending");
      state.botBubble = null;
      addToolChip(event);
      break;
    case "confirm_request":
      askConfirmation(event);
      break;
    case "response":
      finishBotBubble(event.text);
      if (event.end_conversation) {
        const el = document.createElement("div");
        el.className = "tool";
        el.textContent = "💤 Conversation terminée";
        ui.log.append(el);
        scrollDown();
      }
      break;
    case "audio":
    case "audio_chunk":
      if (ui.speak.checked) enqueueAudio(event.data);
      break;
    case "interrupted":
      if (state.botBubble) {
        state.botBubble.classList.remove("pending");
        state.botBubble.classList.add("cut");
        if (!state.botBubble.textContent.trim()) state.botBubble.remove();
      }
      state.botBubble = null;
      break;
    case "error":
      // Avant "ready", l'erreur concerne l'authentification : elle est traitée à la fermeture (code 4401)
      if (state.ready) addBubble("error", event.message);
      break;
    case "done":
      state.busy = Math.max(0, state.busy - 1);
      if (state.pendingUser) {
        state.pendingUser.textContent = "🎙️ (rien entendu)";
        state.pendingUser = null;
      }
      refreshControls();
      break;
    case "reset_done":
      ui.log.querySelectorAll(".msg, .tool").forEach((el) => el.remove());
      ui.empty.hidden = false;
      break;
  }
}

function finishBotBubble(text) {
  // Le texte final est épuré (tags d'actions retirés) : il remplace le flux brut
  const bubble = state.botBubble;
  state.botBubble = null;
  if (!text) {
    if (bubble && !bubble.textContent.trim()) bubble.remove();
    bubble?.classList.remove("pending");
    return;
  }
  const target = bubble || addBubble("bot", "");
  target.classList.remove("pending");
  target.textContent = text;
  scrollDown();
}

// ---- Demandes ----
function interruptAssistant() {
  // Barge-in : on coupe la voix ici et la génération côté serveur
  const speaking = stopPlayback();
  if (state.busy || speaking) send({ type: "stop" });
}

function sendText(text) {
  interruptAssistant();
  addBubble("user", text);
  state.busy += 1;
  refreshControls();
  send({ type: "text", text, speak: ui.speak.checked });
}

function sendAudio(wavBytes) {
  state.pendingUser = addBubble("user", "🎙️ …");
  state.busy += 1;
  refreshControls();
  send({ type: "audio", data: toBase64(wavBytes), speak: ui.speak.checked });
}

ui.textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  unlockAudio();
  const text = ui.text.value.trim();
  if (!text || !state.ready) return;
  ui.text.value = "";
  sendText(text);
});

// ---- Micro ----
ui.mic.addEventListener("click", async () => {
  unlockAudio();
  if (state.recorder) {
    stopRecording();
    return;
  }
  interruptAssistant();
  const cfg = state.audioConfig || {};
  const recorder = new Recorder({
    targetRate: cfg.sample_rate || 16000,
    voiceThreshold: cfg.voice_threshold ?? 0.02,
    silenceDuration: cfg.silence_duration ?? 0.8,
    maxDuration: cfg.max_speech_duration ?? 12,
    autoStop: ui.autostop.checked,
    onLevel: (level) => ui.mic.style.setProperty("--level", (1 + Math.min(level * 12, 0.6)).toFixed(3)),
    onAutoStop: () => stopRecording(),
  });
  try {
    await recorder.start(state.audioCtx);
  } catch (err) {
    addBubble("error", micErrorMessage(err));
    return;
  }
  state.recorder = recorder;
  ui.mic.dataset.state = "recording";
  ui.mic.setAttribute("aria-label", "Arrêter l'écoute");
  setStatus("busy", "J'écoute…");
});

function stopRecording() {
  const recorder = state.recorder;
  if (!recorder) return;
  state.recorder = null;
  ui.mic.dataset.state = "idle";
  ui.mic.setAttribute("aria-label", "Parler");
  const { wav, hadSpeech } = recorder.stop();
  refreshControls();
  if (hadSpeech) sendAudio(wav);
}

function micErrorMessage(err) {
  if (!window.isSecureContext) {
    return "Le micro exige une connexion sécurisée (HTTPS). Utilisez l'adresse fournie par « tailscale serve ».";
  }
  if (err?.name === "NotAllowedError") return "Accès au micro refusé : autorisez-le dans les réglages du navigateur.";
  if (err?.name === "NotFoundError") return "Aucun micro détecté sur cet appareil.";
  return `Micro indisponible : ${err?.message || err}`;
}

// ---- Voix ----
function unlockAudio() {
  // iOS / Safari : le contexte audio doit être créé ou relancé pendant un geste de l'utilisateur
  if (!state.audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) state.audioCtx = new Ctx();
  }
  state.audioCtx?.resume?.();
}

function enqueueAudio(base64) {
  // Les phrases arrivent dans l'ordre mais se décodent de façon asynchrone : la chaîne préserve l'ordre
  // et chaque phrase est programmée juste après la précédente (pas de blanc, pas de chevauchement)
  const ctx = state.audioCtx;
  if (!ctx) return;
  const generation = state.audioGeneration;
  state.decodeChain = state.decodeChain.then(async () => {
    try {
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const buffer = await ctx.decodeAudioData(bytes.buffer);
      if (generation !== state.audioGeneration) return;
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      const startAt = Math.max(ctx.currentTime, state.playHead);
      source.start(startAt);
      state.playHead = startAt + buffer.duration;
      state.playing.add(source);
      source.onended = () => state.playing.delete(source);
    } catch (err) {
      console.warn("Lecture audio impossible", err);
    }
  });
}

function stopPlayback() {
  state.audioGeneration += 1;
  const wasPlaying = state.playing.size > 0;
  for (const source of state.playing) {
    try { source.stop(); } catch { /* déjà terminée */ }
  }
  state.playing.clear();
  state.playHead = 0;
  return wasPlaying;
}

// ---- Confirmation ----
let confirmTimer = null;

function askConfirmation(event) {
  ui.confirmQuestion.textContent = event.question;
  ui.confirm.dataset.requestId = event.id;
  const duration = state.confirmTimeout * 1000;
  const started = performance.now();
  clearInterval(confirmTimer);
  confirmTimer = setInterval(() => {
    const left = 1 - (performance.now() - started) / duration;
    ui.confirmBar.style.transform = `scaleX(${Math.max(0, left)})`;
    if (left <= 0) ui.confirm.close("no");
  }, 100);
  if (!ui.confirm.open) ui.confirm.showModal();
  $("confirm-no").focus();
}

ui.confirm.addEventListener("close", () => {
  clearInterval(confirmTimer);
  const id = ui.confirm.dataset.requestId;
  if (!id) return;
  delete ui.confirm.dataset.requestId;
  send({ type: "confirm_response", id, accepted: ui.confirm.returnValue === "yes" });
});

// ---- Connexion & réglages ----
function openSetup(error = "") {
  ui.token.value = store.get("token", "");
  ui.setupError.textContent = error;
  ui.setupError.hidden = !error;
  if (!ui.setup.open) ui.setup.showModal();
}

ui.setupForm.addEventListener("submit", () => {
  unlockAudio();
  store.set("token", ui.token.value.trim() || null);
  state.ws?.close();
  connect();
});

$("settings-btn").addEventListener("click", () => ui.settings.showModal());
$("reset-btn").addEventListener("click", () => { send({ type: "reset" }); ui.settings.close(); });
$("logout-btn").addEventListener("click", () => {
  store.set("token", null);
  store.set("session", null);
  ui.settings.close();
  state.ws?.close(4000);
  openSetup();
});

for (const [el, key, fallback] of [[ui.speak, "speak", "true"], [ui.autostop, "autostop", "true"]]) {
  el.checked = store.get(key, fallback) === "true";
  el.addEventListener("change", () => store.set(key, String(el.checked)));
}

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* PWA non installable, l'appli fonctionne quand même */ });
}

connect();
