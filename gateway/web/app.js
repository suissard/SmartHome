// Client web SmartHome : connexion WebSocket à la passerelle, conversation en streaming,
// micro (voir recorder.js), confirmations des actions dangereuses, lecture de la voix,
// choix du modèle et paramètres du serveur (formulaire généré d'après core/settings_store.py).
import { Recorder, toBase64 } from "./recorder.js";

const $ = (id) => document.getElementById(id);
const ui = {
  log: $("log"), empty: $("empty"), status: $("status"), liveAnnouncer: $("live-announcer"), toast: $("toast"),
  scrollBottomBtn: $("scroll-bottom-btn"), newChatBtn: $("new-chat-btn"), resetConfirm: $("reset-confirm"),
  mic: $("mic"), voiceStop: $("voice-stop"), textForm: $("text-form"), text: $("text"),
  setup: $("setup"), setupForm: $("setup-form"), token: $("token"), setupError: $("setup-error"),
  restartConfirm: $("restart-confirm"),
  msgMenu: $("msg-menu"), msgPreview: $("msg-preview"), msgRelaunch: $("msg-relaunch"), msgEdit: $("msg-edit"), msgMenuNote: $("msg-menu-note"),
  msgEditor: $("msg-editor"), msgEditorTitle: $("msg-editor-title"), msgEditorText: $("msg-editor-text"), msgEditorSave: $("msg-editor-save"),
  settings: $("settings"), speak: $("speak"), autostop: $("autostop"), sessionId: $("session-id"),
  confirm: $("confirm"), confirmQuestion: $("confirm-question"), confirmBar: $("confirm-bar"), confirmTimerText: $("confirm-timer-text"), confirmMicBtn: $("confirm-mic-btn"), confirmVoiceStatus: $("confirm-voice-status"),
  modelBadge: $("model-badge"), modelCurrent: $("model-current"), modelOllama: $("model-ollama"),
  modelSelect: $("model-select"), modelDecision: $("model-decision"), modelMsg: $("model-msg"),
  advanced: $("advanced"), advancedForm: $("advanced-form"), advancedFields: $("advanced-fields"), advancedMsg: $("advanced-msg"), advancedBack: $("advanced-back"),
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
  audioPending: 0,         // morceaux audio en cours de décodage
  speakingBubble: null,    // bulle bot actuellement vocalisée
  audioGeneration: 0,      // incrémenté à chaque arrêt : les phrases encore en décodage sont ignorées
  llm: null,               // modèle actif : {provider, model, decision}
  restarting: false,       // redémarrage demandé : reconnexion en cours
  settings: null,          // groupes de paramètres du serveur (message "settings")
  modelsBy: {},            // modèles par fournisseur (complétion des champs de modèle)
  models: [],              // modèles du fournisseur : [{name, capabilities, size}]
  turnCount: 0,            // numérote les échanges de cette page (identifiant "turn" envoyé au serveur)
  eventTurn: null,         // échange de l'événement en cours de traitement : les bulles créées lui appartiennent
  droppedTurns: new Set(), // échanges effacés : leurs derniers événements sont ignorés
  menuTarget: null,        // bulle visée par le menu d'appui long
};

// ---- Fil de conversation ----
function isNearBottom(threshold = 60) {
  return ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight <= threshold;
}

function scrollDown(force = false) {
  if (force || isNearBottom()) {
    ui.log.scrollTop = ui.log.scrollHeight;
    if (ui.scrollBottomBtn) ui.scrollBottomBtn.hidden = true;
  } else if (ui.scrollBottomBtn) {
    ui.scrollBottomBtn.hidden = false;
  }
}

function addBubble(kind, text) {
  ui.empty.hidden = true;
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.textContent = text;
  el.tabIndex = 0;  // touche « menu » du clavier : voir l'événement contextmenu
  if (state.eventTurn) el.dataset.turn = state.eventTurn;
  ui.log.append(el);
  scrollDown(true);
  return el;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (s) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[s]));
}

function formatActionSignature(name, args = {}) {
  const entries = Object.entries(args || {});
  if (!entries.length) return `${name}()`;
  const formatted = entries
    .map(([k, v]) => `${k}=${typeof v === "string" ? `"${v}"` : JSON.stringify(v)}`)
    .join(", ");
  return `${name}(${formatted})`;
}

function formatActionLabel(name, args = {}, executed = true) {
  let label = "";
  switch (name) {
    case "volume":
      label = args.level !== undefined ? `Volume réglé à ${args.level} %` : "Réglage du volume";
      break;
    case "mute":
      label = args.action === "unmute" ? "Son réactivé" : "Son coupé";
      break;
    case "media":
      label = args.action === "play" ? "Lecture reprise" :
              args.action === "pause" ? "Musique en pause" :
              args.action === "next" ? "Piste suivante" :
              args.action === "previous" ? "Piste précédente" :
              (args.action ? `Média : ${args.action}` : "Contrôle des médias");
      break;
    case "notify":
      label = args.message ? `Notification : ${args.message}` : "Notification envoyée";
      break;
    case "open_app":
      label = `Application ouverte : ${args.app || "inconnue"}`;
      break;
    case "close_app":
      label = `Application fermée : ${args.app || "inconnue"}`;
      break;
    case "shutdown":
      label = "Extinction de l'ordinateur";
      break;
    case "reboot":
      label = "Redémarrage de l'ordinateur";
      break;
    case "lock":
      label = "Session verrouillée";
      break;
    case "screen_off":
      label = "Écran éteint";
      break;
    case "brightness":
      label = args.level !== undefined ? `Luminosité fixée à ${args.level} %` : "Réglage de la luminosité";
      break;
    case "screenshot":
      label = "Capture d'écran enregistrée";
      break;
    case "system_info":
      label = "État du système vérifié";
      break;
    case "sleep":
      label = "Assistant mis en veille";
      break;
    case "timer":
      label = args.seconds ? `Minuteur : ${args.seconds} s` : "Minuteur programmé";
      break;
    case "audio_output":
      label = args.sink ? `Sortie audio : ${args.sink}` : "Sortie audio modifiée";
      break;
    default: {
      const clean = name.replace(/_/g, " ");
      label = `Action : ${clean}`;
      break;
    }
  }
  return executed ? label : `${label} — non exécutée`;
}

function addToolChip(event) {
  const el = document.createElement("div");
  el.className = `tool ${event.executed ? "ok" : "refused"}`;
  if (state.eventTurn) el.dataset.turn = state.eventTurn;
  const label = formatActionLabel(event.name, event.arguments, event.executed);
  const signature = formatActionSignature(event.name, event.arguments);
  const icon = event.executed ? "✓" : "✕";

  // Texte visible : strictement le libellé en français naturel, sans signature technique
  el.innerHTML = `<span class="tool-icon" aria-hidden="true">${icon}</span> <span class="tool-text">${escapeHtml(label)}</span>`;

  // Détail technique : accessible uniquement au survol (title) et aux lecteurs d'écran (aria-label)
  const detail = event.output ? `${signature} → ${event.output}` : signature;
  el.title = detail;
  el.setAttribute("aria-label", `${label} (${signature})${event.output ? `. Résultat : ${event.output}` : ""}`);

  ui.log.append(el);
  scrollDown();
}

function setStatus(stateName, label) {
  ui.status.dataset.state = stateName;
  ui.status.textContent = label;
}

function isSpeaking() {
  return state.playing.size > 0 || state.audioPending > 0;
}

// Bouton principal : arrêter l'écoute, envoyer le texte saisi, sinon parler
function updateMainButton() {
  const recording = Boolean(state.recorder);
  const mode = recording ? "recording" : ui.text.value.trim() ? "send" : "idle";
  ui.mic.dataset.state = mode;
  ui.mic.setAttribute("aria-label", { recording: "Arrêter l'écoute", send: "Envoyer", idle: "Parler" }[mode]);
  ui.mic.setAttribute("aria-pressed", String(recording));
}

function updateSpeakingState() {
  const speaking = isSpeaking();
  ui.voiceStop.hidden = !speaking;
  if (speaking) {
    if (!state.busy) setStatus("speaking", "L'assistant parle…");
    const targetBubble = state.speakingBubble || ui.log.querySelector(".msg.bot:last-of-type");
    if (targetBubble && !targetBubble.querySelector(".sound-wave")) {
      targetBubble.classList.add("speaking");
      const wave = document.createElement("span");
      wave.className = "sound-wave";
      wave.setAttribute("aria-hidden", "true");
      wave.innerHTML = "<span></span><span></span><span></span><span></span>";
      targetBubble.append(wave);
    }
  } else {
    document.querySelectorAll(".msg.bot.speaking").forEach((b) => {
      b.classList.remove("speaking");
      b.querySelector(".sound-wave")?.remove();
    });
    state.speakingBubble = null;
    refreshControls();
  }
}

function refreshControls() {
  const enabled = state.ready;
  ui.text.disabled = !enabled;
  ui.mic.disabled = !enabled;
  if (enabled) {
    if (state.busy) {
      setStatus("busy", "Réflexion…");
    } else if (isSpeaking()) {
      setStatus("speaking", "L'assistant parle…");
    } else {
      setStatus("online", "Connecté");
    }
  }
}

// ---- Connexion ----
// Lien d'appairage (QR code du terminal) : #token=... (ou ?token=...) est mémorisé puis effacé de la barre d'adresse
function consumePairingToken() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const query = new URLSearchParams(location.search);
  const token = hash.get("token") ?? query.get("token");
  if (token === null) return;
  if (token.trim()) {
    store.set("token", token.trim());
    store.set("session", null);
  }
  hash.delete("token");
  query.delete("token");
  const search = query.toString();
  const rest = hash.toString();
  history.replaceState(null, "", location.pathname + (search ? `?${search}` : "") + (rest ? `#${rest}` : ""));
}

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
    // Seule la fin d'un échange effacé compte encore : elle tient le compte des demandes en cours
    if (state.droppedTurns.has(event.turn) && event.type !== "done") return;
    state.eventTurn = event.turn ?? null;
    handleEvent(event);
    state.eventTurn = null;
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
    setStatus("offline", state.restarting ? "Redémarrage…" : "Hors ligne");
    setTimeout(connect, state.reconnectDelay);
    // Pendant un redémarrage, on retente à rythme constant pour revenir dès que le serveur répond
    if (!state.restarting) state.reconnectDelay = Math.min(state.reconnectDelay * 2, 15000);
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
      showModel(event.llm);
      refreshControls();
      if (state.restarting) {
        state.restarting = false;
        showToast("SmartHome a redémarré", "ok");
      }
      break;
    case "restarting":
      state.restarting = true;
      state.reconnectDelay = 1000;
      for (const dialog of [ui.settings, ui.advanced]) if (dialog.open) dialog.close();
      showToast("Redémarrage de SmartHome…", "ok");
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
    case "toast":
      showToast(event.message, event.kind || "warn");
      break;
    case "confirm_dismiss":
      if (ui.confirm.open) {
        clearInterval(confirmTimer);
        clearInterval(confirmSpeechCheckTimer);
        confirmSpeechCheckTimer = null;
        if (state.recorder) {
          state.recorder.stop();
          state.recorder = null;
        }
        delete ui.confirm.dataset.requestId;
        ui.confirm.close(event.accepted ? "yes" : "no");
      }
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
      stopPlayback();
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
    case "settings":
      state.settings = event.groups;
      showModel(event.llm);
      renderModelPicker();
      if (ui.advanced.open && !ui.advancedForm.dataset.dirty) renderAdvanced();
      break;
    case "models":
      state.modelsBy[event.provider] = event.models || [];
      ensureModelsDatalist(event.provider);
      // Le sélecteur de la fenêtre des réglages ne concerne que le fournisseur actif
      if (event.provider === (state.llm?.provider || settingValue("LLM_PROVIDER"))) {
        state.models = event.models || [];
        renderModelPicker(event.error);
      }
      break;
    case "settings_saved":
      onSettingsSaved(event);
      break;
    case "settings_error":
      setMessage(ui.advanced.open ? ui.advancedMsg : ui.modelMsg, event.message, "error");
      break;
    case "settings_changed":
      // Modifié depuis un autre appareil (ou celui-ci) : on recharge les valeurs affichées
      if (ui.settings.open || ui.advanced.open) send({ type: "get_settings" });
      break;
  }
}

function announce(text) {
  if (!ui.liveAnnouncer || !text) return;
  ui.liveAnnouncer.textContent = "";
  setTimeout(() => {
    if (ui.liveAnnouncer) ui.liveAnnouncer.textContent = text;
  }, 50);
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
  state.speakingBubble = target;
  if (isSpeaking()) updateSpeakingState();
  scrollDown();
  announce(text);
}

// ---- Demandes ----
function interruptAssistant() {
  // Barge-in : on coupe la voix ici et la génération côté serveur
  const speaking = stopPlayback();
  if (state.busy || speaking) send({ type: "stop" });
}

function newTurn() {
  state.turnCount += 1;
  return `${Date.now().toString(36)}-${state.turnCount}`;
}

// `forget` : échanges à retirer de l'historique du serveur avant de répondre (relance d'un message)
function sendText(text, forget = []) {
  interruptAssistant();
  const turn = newTurn();
  addBubble("user", text).dataset.turn = turn;
  state.busy += 1;
  refreshControls();
  send({ type: "text", text, speak: ui.speak.checked, turn, forget });
}

function sendAudio(wavBytes) {
  const turn = newTurn();
  state.pendingUser = addBubble("user", "🎙️ …");
  state.pendingUser.dataset.turn = turn;
  state.busy += 1;
  refreshControls();
  send({ type: "audio", data: toBase64(wavBytes), speak: ui.speak.checked, turn });
}

ui.textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  unlockAudio();
  const text = ui.text.value.trim();
  if (!text || !state.ready) return;
  ui.text.value = "";
  updateMainButton();
  sendText(text);
});

ui.text.addEventListener("input", updateMainButton);

ui.log.addEventListener("click", (e) => {
  const chip = e.target.closest(".hint-chip");
  if (!chip || !state.ready) return;
  unlockAudio();
  sendText(chip.textContent.trim());
});

ui.voiceStop.addEventListener("click", interruptAssistant);

// ---- Appui long sur une bulle : supprimer, relancer, modifier ----
const LONG_PRESS_MS = 500;
const LONG_PRESS_TOLERANCE_PX = 10;
let press = null;

function cancelPress() {
  clearTimeout(press?.timer);
  press = null;
}

function menuBubble(target) {
  const el = target.closest?.(".msg");
  return el && (el.dataset.turn || el.classList.contains("error")) ? el : null;
}

ui.log.addEventListener("pointerdown", (e) => {
  cancelPress();
  const el = menuBubble(e.target);
  if (!el || e.button !== 0) return;
  press = { x: e.clientX, y: e.clientY, timer: setTimeout(() => {
    press = null;
    navigator.vibrate?.(15);
    openMessageMenu(el);
  }, LONG_PRESS_MS) };
});
ui.log.addEventListener("pointermove", (e) => {
  if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > LONG_PRESS_TOLERANCE_PX) cancelPress();
});
for (const name of ["pointerup", "pointercancel", "scroll"]) ui.log.addEventListener(name, cancelPress);

// Clic droit, touche « menu », et appui long sur les navigateurs qui le signalent ainsi
ui.log.addEventListener("contextmenu", (e) => {
  const el = menuBubble(e.target);
  if (!el) return;
  e.preventDefault();
  cancelPress();
  openMessageMenu(el);
});

function turnElements(turn, selector = ".msg, .tool") {
  return [...ui.log.querySelectorAll(selector)].filter((el) => el.dataset.turn === turn);
}

// Bulle de l'utilisateur dont on peut renvoyer le texte (un message vocal sans transcription n'en a pas)
function relaunchSource(el) {
  const [source] = turnElements(el.dataset.turn, ".msg.user");
  return source && !source.textContent.startsWith("🎙️") ? source : null;
}

function openMessageMenu(el) {
  if (ui.msgMenu.open || ui.msgEditor.open) return;
  state.menuTarget = el;
  const isBot = el.classList.contains("bot");
  const canRelaunch = Boolean(el.dataset.turn && relaunchSource(el));
  const canEdit = isBot ? !el.matches(".pending, .cut") : el.classList.contains("user") && canRelaunch;
  ui.msgPreview.textContent = el.textContent;
  ui.msgRelaunch.hidden = !canRelaunch;
  ui.msgEdit.hidden = !canEdit;
  ui.msgEdit.textContent = isBot ? "Modifier la réponse" : "Modifier et relancer";
  ui.msgMenuNote.hidden = !canRelaunch && !canEdit;
  ui.msgMenu.showModal();
}

function removeElements(elements) {
  for (const el of elements) {
    if (el === state.botBubble) state.botBubble = null;
    if (el === state.pendingUser) state.pendingUser = null;
    el.remove();
  }
  ui.empty.hidden = ui.log.querySelector(".msg, .tool") !== null;
}

// Efface ces éléments et retourne leurs échanges, à retirer aussi de l'historique du serveur
function dropElements(elements) {
  const turns = [...new Set(elements.map((el) => el.dataset.turn).filter(Boolean))];
  turns.forEach((turn) => state.droppedTurns.add(turn));
  removeElements(elements);
  return turns;
}

function followingElements(el) {
  const elements = [];
  for (let next = el.nextElementSibling; next; next = next.nextElementSibling) {
    if (next.matches(".msg, .tool")) elements.push(next);
  }
  return elements;
}

function relaunchFrom(el, text) {
  const source = relaunchSource(el);
  const content = text ?? source.textContent;
  sendText(content, dropElements([source, ...followingElements(source)]));
}

function deleteMessage(el) {
  const { turn } = el.dataset;
  if (el.classList.contains("error")) {
    removeElements([el]);
  } else if (el.classList.contains("user")) {
    if (state.busy) interruptAssistant();
    removeElements([el]);
    send({ type: "forget", turns: [turn], role: "user" });
  } else {
    // La réponse peut tenir sur plusieurs bulles, séparées par ses outils
    const answer = turnElements(turn, ".msg.bot, .tool");
    if (state.busy || answer.includes(state.speakingBubble)) interruptAssistant();
    dropElements(answer);
    send({ type: "forget", turns: [turn], role: "assistant" });
  }
}

function openMessageEditor(el) {
  const isBot = el.classList.contains("bot");
  ui.msgEditorTitle.textContent = isBot ? "Modifier la réponse" : "Modifier le message";
  ui.msgEditorSave.textContent = isBot ? "Enregistrer" : "Relancer";
  ui.msgEditorText.value = isBot
    ? turnElements(el.dataset.turn, ".msg.bot").map((b) => b.textContent).join("\n\n")
    : el.textContent;
  ui.msgEditor.showModal();
}

function saveEditedAnswer(el, text) {
  const { turn } = el.dataset;
  const [first, ...others] = turnElements(turn, ".msg.bot");
  const answer = turnElements(turn);
  interruptAssistant();
  const forget = dropElements(followingElements(answer[answer.length - 1]));
  removeElements(others);
  first.textContent = text;
  send({ type: "edit_answer", turn, text, forget });
}

ui.msgMenu.addEventListener("close", () => {
  const el = state.menuTarget;
  const action = ui.msgMenu.returnValue;
  ui.msgMenu.returnValue = "";
  if (!el?.isConnected) return;
  if (action === "delete") deleteMessage(el);
  else if (action === "relaunch") {
    unlockAudio();
    relaunchFrom(el);
  } else if (action === "edit") openMessageEditor(el);
});

ui.msgEditor.addEventListener("close", () => {
  const el = state.menuTarget;
  const text = ui.msgEditorText.value.trim();
  const save = ui.msgEditor.returnValue === "save";
  ui.msgEditor.returnValue = "";
  if (!save || !text || !el?.isConnected) return;
  if (el.classList.contains("bot")) saveEditedAnswer(el, text);
  else {
    unlockAudio();
    relaunchFrom(el, text);
  }
});

// ---- Micro ----
ui.mic.addEventListener("click", async () => {
  unlockAudio();
  if (state.recorder) {
    stopRecording();
    return;
  }
  if (ui.text.value.trim()) {
    ui.textForm.requestSubmit();
    return;
  }
  // Parler pendant une réponse l'interrompt : le micro ne doit pas capter la voix de l'assistant
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
  updateMainButton();
  setStatus("busy", "J'écoute…");
});

let toastTimer = null;
function showToast(message, kind = "warn", duration = 4000) {
  if (!ui.toast) return;
  clearTimeout(toastTimer);
  ui.toast.textContent = message;
  ui.toast.className = `toast ${kind}`;
  ui.toast.hidden = false;
  toastTimer = setTimeout(() => {
    if (ui.toast) ui.toast.hidden = true;
  }, duration);
}

function stopRecording() {
  const recorder = state.recorder;
  if (!recorder) return;
  state.recorder = null;
  updateMainButton();
  const { wav, hadSpeech } = recorder.stop();
  refreshControls();
  if (hadSpeech) {
    sendAudio(wav);
  } else {
    showToast("Voix non détectée — parlez plus fort ou approchez-vous du micro.");
  }
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
  state.audioPending += 1;
  updateSpeakingState();
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
      source.onended = () => {
        state.playing.delete(source);
        updateSpeakingState();
      };
      updateSpeakingState();
    } catch (err) {
      console.warn("Lecture audio impossible", err);
    } finally {
      state.audioPending = Math.max(0, state.audioPending - 1);
      updateSpeakingState();
    }
  });
}

function stopPlayback() {
  state.audioGeneration += 1;
  const wasPlaying = state.playing.size > 0 || state.audioPending > 0;
  for (const source of state.playing) {
    try { source.stop(); } catch { /* déjà terminée */ }
  }
  state.playing.clear();
  state.audioPending = 0;
  state.playHead = 0;
  updateSpeakingState();
  return wasPlaying;
}

// ---- Confirmation ----
let confirmTimer = null;
let confirmSpeechCheckTimer = null;
let confirmElapsed = 0;
let confirmPaused = false;
let confirmTotalMs = 20000;
let confirmLastTick = 0;

function updateConfirmDisplay() {
  const remainingMs = Math.max(0, confirmTotalMs - confirmElapsed);
  const leftFrac = remainingMs / confirmTotalMs;
  ui.confirmBar.style.transform = `scaleX(${leftFrac})`;

  if (ui.confirmTimerText) {
    const seconds = Math.ceil(remainingMs / 1000);
    if (confirmPaused) {
      ui.confirmTimerText.textContent = `Décompte en pause (${seconds} s restantes)`;
    } else {
      ui.confirmTimerText.textContent = `Annulation automatique dans ${seconds} s`;
    }
  }

  if (remainingMs <= 0 && ui.confirm.open) {
    ui.confirm.close("no");
  }
}

async function startConfirmListening() {
  if (!ui.confirm.open) return;
  clearInterval(confirmSpeechCheckTimer);

  const statusEl = ui.confirmVoiceStatus;
  const micBtn = ui.confirmMicBtn;

  // Si l'assistant parle encore (lecture de la question TTS), attendre la fin pour ne pas enregistrer sa voix
  if (isSpeaking()) {
    if (statusEl) statusEl.textContent = "🔊 L'assistant parle…";
    confirmSpeechCheckTimer = setInterval(() => {
      if (!isSpeaking() || !ui.confirm.open) {
        clearInterval(confirmSpeechCheckTimer);
        confirmSpeechCheckTimer = null;
        if (ui.confirm.open) {
          startConfirmListening();
        }
      }
    }, 150);
    return;
  }

  if (state.recorder) {
    return;
  }

  unlockAudio();
  if (statusEl) statusEl.textContent = "🎙️ J'écoute… Dites « Oui » ou « Non »";
  if (micBtn) micBtn.classList.add("recording");

  const cfg = state.audioConfig || {};
  const recorder = new Recorder({
    targetRate: cfg.sample_rate || 16000,
    voiceThreshold: cfg.voice_threshold ?? 0.02,
    silenceDuration: cfg.silence_duration ?? 0.8,
    maxDuration: cfg.max_speech_duration ?? 12,
    autoStop: true,
    onLevel: (level) => {
      if (micBtn) micBtn.style.setProperty("--level", (1 + Math.min(level * 12, 0.6)).toFixed(3));
    },
    onAutoStop: () => {
      stopConfirmRecording();
    },
  });

  try {
    await recorder.start(state.audioCtx);
    state.recorder = recorder;
  } catch (err) {
    console.warn("Écoute micro confirmation indisponible:", err);
    if (statusEl) statusEl.textContent = "Dites « Oui » ou « Non », ou cliquez ci-dessous";
    if (micBtn) micBtn.classList.remove("recording");
  }
}

function stopConfirmRecording() {
  const recorder = state.recorder;
  if (!recorder) return;
  state.recorder = null;
  const statusEl = ui.confirmVoiceStatus;
  const micBtn = ui.confirmMicBtn;
  if (micBtn) micBtn.classList.remove("recording");

  const { wav, hadSpeech } = recorder.stop();
  if (hadSpeech) {
    if (statusEl) statusEl.textContent = "⏳ Traitement de votre réponse…";
    sendAudio(wav);
  } else {
    if (statusEl) statusEl.textContent = "🎙️ Dites « Oui » ou « Non »";
    if (ui.confirm.open) {
      setTimeout(startConfirmListening, 250);
    }
  }
}

function askConfirmation(event) {
  ui.confirmQuestion.textContent = event.question;
  ui.confirm.dataset.requestId = event.id;
  confirmTotalMs = (state.confirmTimeout || 20) * 1000;
  confirmElapsed = 0;
  confirmPaused = false;
  confirmLastTick = performance.now();
  clearInterval(confirmTimer);
  updateConfirmDisplay();
  confirmTimer = setInterval(() => {
    if (!confirmPaused) {
      const now = performance.now();
      confirmElapsed += (now - confirmLastTick);
      confirmLastTick = now;
    } else {
      confirmLastTick = performance.now();
    }
    updateConfirmDisplay();
  }, 100);
  if (!ui.confirm.open) ui.confirm.showModal();
  $("confirm-no").focus();

  // Démarrer immédiatement l'écoute vocale
  startConfirmListening();
}

ui.confirmMicBtn?.addEventListener("click", () => {
  if (state.recorder) {
    stopConfirmRecording();
  } else {
    interruptAssistant();
    startConfirmListening();
  }
});

ui.confirm.addEventListener("mouseenter", () => {
  confirmPaused = true;
  updateConfirmDisplay();
});
ui.confirm.addEventListener("mouseleave", () => {
  confirmPaused = false;
  confirmLastTick = performance.now();
  updateConfirmDisplay();
});
ui.confirm.addEventListener("focusin", () => {
  confirmPaused = true;
  updateConfirmDisplay();
});
ui.confirm.addEventListener("focusout", (e) => {
  if (!ui.confirm.contains(e.relatedTarget)) {
    confirmPaused = false;
    confirmLastTick = performance.now();
    updateConfirmDisplay();
  }
});

ui.confirm.addEventListener("close", () => {
  clearInterval(confirmTimer);
  clearInterval(confirmSpeechCheckTimer);
  confirmSpeechCheckTimer = null;
  if (state.recorder) {
    state.recorder.stop();
    state.recorder = null;
  }
  ui.confirmMicBtn?.classList.remove("recording");
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

ui.log.addEventListener("scroll", () => {
  if (isNearBottom() && ui.scrollBottomBtn) {
    ui.scrollBottomBtn.hidden = true;
  }
});

ui.scrollBottomBtn?.addEventListener("click", () => {
  scrollDown(true);
  if (ui.scrollBottomBtn) ui.scrollBottomBtn.hidden = true;
});

function promptResetConversation() {
  const hasMessages = ui.log.querySelectorAll(".msg, .tool").length > 0;
  if (!hasMessages) {
    send({ type: "reset" });
    return;
  }
  if (ui.resetConfirm) {
    ui.resetConfirm.showModal();
  } else if (confirm("Effacer la conversation en cours ?")) {
    send({ type: "reset" });
  }
}

ui.resetConfirm?.addEventListener("close", () => {
  if (ui.resetConfirm.returnValue === "confirm") {
    send({ type: "reset" });
    showToast("Conversation effacée", "ok");
  }
});

ui.newChatBtn?.addEventListener("click", promptResetConversation);

$("settings-btn").addEventListener("click", () => {
  ui.settings.showModal();
  ui.modelMsg.textContent = "";
  send({ type: "get_settings" });
  send({ type: "list_models" });
});
$("reset-btn").addEventListener("click", () => {
  ui.settings.close();
  promptResetConversation();
});
$("restart-btn").addEventListener("click", () => ui.restartConfirm.showModal());
$("advanced-restart").addEventListener("click", () => ui.restartConfirm.showModal());
ui.restartConfirm.addEventListener("close", () => {
  if (ui.restartConfirm.returnValue === "confirm") send({ type: "restart" });
  ui.restartConfirm.returnValue = "";
});
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

// ---- Modèle & paramètres du serveur ----
function setMessage(el, text, kind = "") {
  el.textContent = text;
  el.className = `meta${kind === "error" ? " error" : kind === "ok" ? " ok-text" : ""}`;
}

function settingValue(name) {
  for (const group of state.settings || []) {
    const field = group.fields.find((f) => f.name === name);
    if (field) return field.value;
  }
  return undefined;
}

function showModel(llm) {
  if (!llm) return;
  state.llm = llm;
  ui.modelBadge.hidden = false;
  ui.modelBadge.textContent = llm.decision ? `${llm.model} · décision` : llm.model;
  ui.modelBadge.classList.toggle("decision", Boolean(llm.decision));
  ui.modelBadge.title = `${llm.provider} : ${llm.model}${llm.decision ? " (modèle de décision)" : ""}`;
  ui.modelCurrent.textContent = `Actif : ${llm.model} (${llm.provider})${llm.decision ? " — modèle de décision" : ""}`;
}

const baseName = (model) => model.split(":")[0].toLowerCase();

function isDecisionModel(model, list = settingValue("LLM_DECISION_MODELS") || []) {
  return list.includes(model.toLowerCase()) || list.includes(baseName(model));
}

function renderModelPicker(error = "") {
  const isOllama = (state.llm?.provider || settingValue("LLM_PROVIDER")) === "ollama";
  ui.modelOllama.hidden = !isOllama;
  if (!isOllama) {
    const key = settingValue("OPENROUTER_API_KEY");
    const status = key ? "clé configurée" : "⚠️ clé API manquante";
    setMessage(ui.modelMsg, `Fournisseur OpenRouter (${status}). Modifiez le modèle et la clé dans les paramètres avancés.`);
    return;
  }
  const current = settingValue("OLLAMA_MODEL") || state.llm?.model || "";
  const names = state.models.map((m) => m.name);
  if (current && !names.includes(current)) names.unshift(current);
  const selected = ui.modelSelect.value || current;
  ui.modelSelect.replaceChildren(...names.map((name) => {
    const info = state.models.find((m) => m.name === name);
    const caps = info?.capabilities || [];
    const size = info?.size ? ` · ${(info.size / 1e9).toFixed(1)} Go` : "";
    const kind = caps.includes("decision") ? " · décision" : caps.includes("tools") ? " · outils" : "";
    const audio = caps.includes("audio") ? " · audio" : "";
    return new Option(`${name}${kind}${audio}${size}`, name);
  }));
  ui.modelSelect.value = names.includes(selected) ? selected : current;
  syncDecisionToggle(false);
  if (error) setMessage(ui.modelMsg, error, "error");
}

function syncDecisionToggle(fromUser) {
  const name = ui.modelSelect.value;
  if (!name) return;
  const caps = state.models.find((m) => m.name === name)?.capabilities || [];
  // Un modèle déclaré « decision » par Ollama est proposé coché s'il n'est pas encore connu
  ui.modelDecision.checked = isDecisionModel(name) || (fromUser && caps.includes("decision"));
  // Sans intérêt pour un modèle de langage : la case n'apparaît que pour les modèles de décision
  ui.modelDecision.closest("label").hidden = !isDecisionModel(name) && !caps.includes("decision");
  if (!fromUser) return;
  const hints = [];
  if (caps.includes("decision")) hints.push("Ollama le décrit comme un modèle de décision.");
  else if (caps.length && !caps.includes("tools")) hints.push("Ce modèle ne gère pas les outils : les actions passeront par les tags [ACTION].");
  if (settingValue("STT_PROVIDER") === "direct" && caps.length && !caps.includes("decision")) {
    hints.push(caps.includes("audio")
      ? "Il comprend l'audio : la voix lui sera envoyée directement."
      : `Il ne comprend pas l'audio : la voix sera transcrite (${settingValue("STT_FALLBACK_PROVIDER") || "whisper"}).`);
  }
  setMessage(ui.modelMsg, hints.join(" "));
}

ui.modelSelect.addEventListener("change", () => syncDecisionToggle(true));
$("models-refresh").addEventListener("click", () => {
  setMessage(ui.modelMsg, "Actualisation…");
  send({ type: "list_models" });
});

$("model-apply").addEventListener("click", () => {
  const name = ui.modelSelect.value;
  if (!name) return;
  const list = (settingValue("LLM_DECISION_MODELS") || []).filter((m) => m !== name.toLowerCase() && m !== baseName(name));
  if (ui.modelDecision.checked) list.push(name.endsWith(":latest") ? baseName(name) : name.toLowerCase());
  setMessage(ui.modelMsg, "Enregistrement…");
  send({ type: "update_settings", values: { OLLAMA_MODEL: name, LLM_DECISION_MODELS: list } });
});

function onSettingsSaved(event) {
  showModel(event.llm);
  const target = ui.advanced.open ? ui.advancedMsg : ui.modelMsg;
  if (!event.changed.length) {
    setMessage(target, "Aucun changement.");
    return;
  }
  const label = (name) => fieldByName(name)?.label || name;
  const parts = ["Enregistré."];
  if (event.restart.length) parts.push(`Au prochain démarrage : ${event.restart.map(label).join(", ")}.`);
  $("advanced-restart").hidden = !event.restart.length;
  if (event.overridden.length) parts.push(`Attention, une variable d'environnement reste prioritaire : ${event.overridden.join(", ")}.`);
  setMessage(target, parts.join(" "), "ok");
  delete ui.advancedForm.dataset.dirty;
}

function fieldByName(name) {
  for (const group of state.settings || []) {
    const field = group.fields.find((f) => f.name === name);
    if (field) return field;
  }
  return null;
}

// Formulaire généré : un bloc repliable par groupe, un contrôle par type de champ
function renderAdvanced() {
  const openGroups = new Set([...ui.advancedFields.querySelectorAll("details[open]")].map((d) => d.dataset.title));
  const firstRender = !ui.advancedFields.querySelector("details");
  ui.advancedFields.replaceChildren(...(state.settings || []).map((group, index) => {
    const details = document.createElement("details");
    details.className = "group";
    details.dataset.title = group.title;
    details.open = openGroups.has(group.title) || (firstRender && index === 0);
    const summary = document.createElement("summary");
    summary.textContent = group.title;
    details.append(summary, ...group.fields.map(renderField));
    return details;
  }));
  applyVisibility();
}

// Valeur en cours de saisie dans le formulaire (sinon valeur enregistrée)
function formValue(name) {
  if (name === "LLM_MODE") {
    const list = String(formValue("LLM_DECISION_MODELS")).toLowerCase().split(",").map((m) => m.trim());
    return formValue("LLM_PROVIDER") === "ollama" && isDecisionModel(formValue("OLLAMA_MODEL"), list) ? "decision" : "language";
  }
  const input = ui.advancedFields.querySelector(`[data-name="${name}"]`);
  if (!input) return settingValue(name);
  return input.type === "checkbox" ? input.checked : input.value;
}

// N'affiche que les champs utiles à la configuration saisie (règles : VISIBLE_WHEN de core/settings_store.py)
function applyVisibility() {
  for (const group of ui.advancedFields.querySelectorAll("details.group")) {
    const fields = [...group.querySelectorAll(":scope > .field")];
    for (const wrap of fields) {
      const when = wrap.dataset.when && JSON.parse(wrap.dataset.when);
      wrap.hidden = Boolean(when) && !when.some((rule) =>
        Object.entries(rule).every(([name, allowed]) => allowed.includes(formValue(name))));
    }
    group.hidden = fields.every((wrap) => wrap.hidden);
  }
}

function renderField(field) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  if (field.when) wrap.dataset.when = JSON.stringify(field.when);
  const id = `setting-${field.name}`;
  let input;
  if (field.kind === "bool") {
    const label = document.createElement("label");
    label.className = "toggle";
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(field.value);
    const text = document.createElement("span");
    text.textContent = field.label;
    label.append(input, text);
    appendTag(text, field);
    wrap.append(label);
  } else {
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = field.label;
    appendTag(label, field);
    if (field.kind === "select") {
      input = document.createElement("select");
      const options = [...field.options];
      if (!options.includes(field.value)) options.unshift(field.value);
      input.append(...options.map((o) => new Option(o, o)));
      input.value = field.value;
    } else if (field.kind === "number") {
      input = document.createElement("input");
      input.type = "number";
      input.step = field.step;
      if (field.min !== undefined && field.min !== null) input.min = field.min;
      if (field.max !== undefined && field.max !== null) input.max = field.max;
      input.value = field.value ?? "";
    } else if (field.kind === "json") {
      input = document.createElement("div");
      input.className = "kv-editor";
      const rows = document.createElement("div");
      rows.className = "kv-rows";
      const obj = (typeof field.value === "object" && field.value !== null) ? field.value : {};

      const addRow = (k = "", v = "") => {
        const row = document.createElement("div");
        row.className = "kv-row";
        const kInput = document.createElement("input");
        kInput.type = "text";
        kInput.placeholder = "Commande (ex: volume)";
        kInput.value = k;
        const vInput = document.createElement("input");
        vInput.type = "text";
        vInput.placeholder = "Message de confirmation";
        vInput.value = v;
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "kv-del";
        delBtn.innerHTML = "×";
        delBtn.setAttribute("aria-label", "Supprimer cette commande");
        delBtn.addEventListener("click", () => {
          row.remove();
          input.dispatchEvent(new Event("input", { bubbles: true }));
        });
        const triggerChange = () => input.dispatchEvent(new Event("input", { bubbles: true }));
        kInput.addEventListener("input", triggerChange);
        vInput.addEventListener("input", triggerChange);
        row.append(kInput, vInput, delBtn);
        rows.append(row);
      };

      for (const [k, v] of Object.entries(obj)) {
        addRow(k, v);
      }
      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "kv-add";
      addBtn.textContent = "+ Ajouter une commande";
      addBtn.addEventListener("click", () => {
        addRow("", "");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      input.append(rows, addBtn);
    } else if (field.multiline) {
      input = document.createElement("textarea");
      input.value = field.kind === "list" ? field.value.join(", ") : field.value;
      input.id = id;
      wrap.append(label, input);
    } else if (field.kind === "password") {
      const row = document.createElement("div");
      row.className = "row";
      input = document.createElement("input");
      input.type = "password";
      if (field.placeholder) input.placeholder = field.placeholder;
      input.value = field.value ?? "";
      input.id = id;
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "icon-btn";
      toggleBtn.setAttribute("aria-label", "Afficher ou masquer");
      toggleBtn.title = "Afficher / Masquer";
      toggleBtn.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
      toggleBtn.addEventListener("click", () => {
        input.type = input.type === "password" ? "text" : "password";
      });
      row.append(input, toggleBtn);
      wrap.append(label, row);
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.value = field.kind === "list" ? field.value.join(", ") : (field.value ?? "");
      if (field.kind === "model") {
        // Saisie libre complétée par les modèles connus
        const provider = field.name.split("_")[0].toLowerCase();  // OLLAMA_MODEL, OPENROUTER_MODEL
        input.setAttribute("list", `models-datalist-${provider}`);
        ensureModelsDatalist(provider);
        if (!state.modelsBy[provider]) {
          state.modelsBy[provider] = [];  // demandé une seule fois par ouverture
          send({ type: "list_models", provider });
        }
      }
      input.id = id;
      wrap.append(label, input);
    }
  }
  input.dataset.name = field.name;
  input.addEventListener("input", () => {
    let changed = true;
    try { changed = readField(field, input) !== undefined; } catch { /* JSON en cours de saisie */ }
    wrap.classList.toggle("changed", changed);
    ui.advancedForm.dataset.dirty = "1";
    applyVisibility();
  });
  if (field.help) {
    const help = document.createElement("p");
    help.className = "help";
    help.textContent = field.help;
    wrap.append(help);
  }
  if (field.defaults) {
    // Messages déclarés par les actions : rappel des commandes disponibles et de leur phrase par défaut
    const details = document.createElement("details");
    details.className = "help";
    const summary = document.createElement("summary");
    summary.textContent = "Messages par défaut des commandes";
    const list = document.createElement("pre");
    list.className = "defaults";
    list.textContent = Object.entries(field.defaults)
      .map(([tool, message]) => `${tool} : ${message || "(réponse type)"}`).join("\n");
    details.append(summary, list);
    wrap.append(details);
  }
  return wrap;
}

function appendTag(el, field) {
  if (field.live) return;
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = "au redémarrage";
  el.append(tag);
}

function ensureModelsDatalist(provider) {
  const id = `models-datalist-${provider}`;
  let list = $(id);
  if (!list) {
    list = document.createElement("datalist");
    list.id = id;
    document.body.append(list);
  }
  list.replaceChildren(...(state.modelsBy[provider] || []).map((m) => {
    const caps = (m.capabilities || []).join(", ");
    return new Option(caps ? `${m.name} · ${caps}` : m.name, m.name);
  }));
}

// Valeur saisie si elle diffère de la valeur actuelle (sinon undefined)
function readField(field, input) {
  let value;
  if (field.kind === "bool") value = input.checked;
  else if (field.kind === "number") {
    if (input.value.trim() === "") return undefined;
    value = Number(input.value);
  } else if (field.kind === "list") value = input.value.split(",").map((v) => v.trim()).filter(Boolean);
  else if (field.kind === "json") {
    const result = {};
    for (const row of input.querySelectorAll(".kv-row")) {
      const inputs = row.querySelectorAll("input");
      const k = inputs[0]?.value.trim();
      const v = inputs[1]?.value.trim();
      if (k) result[k] = v;
    }
    value = result;
  }
  else value = input.value;
  return JSON.stringify(value) === JSON.stringify(field.value) ? undefined : value;
}

$("advanced-btn").addEventListener("click", () => {
  ui.settings.close();
  setMessage(ui.advancedMsg, "");
  $("advanced-restart").hidden = true;
  delete ui.advancedForm.dataset.dirty;
  renderAdvanced();
  ui.advanced.showModal();
  $("advanced-back")?.focus();
  send({ type: "get_settings" });
});

$("advanced-back")?.addEventListener("click", () => {
  ui.advanced.close();
  ui.settings.showModal();
  $("advanced-btn")?.focus();
});

$("advanced-close").addEventListener("click", () => {
  ui.advanced.close();
  $("settings-btn")?.focus();
});

ui.advancedForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const values = {};
  try {
    for (const input of ui.advancedFields.querySelectorAll("[data-name]")) {
      const field = fieldByName(input.dataset.name);
      const value = field && readField(field, input);
      if (value !== undefined) values[field.name] = value;
    }
  } catch (err) {
    setMessage(ui.advancedMsg, err.message, "error");
    return;
  }
  if (!Object.keys(values).length) {
    setMessage(ui.advancedMsg, "Aucun changement.");
    return;
  }
  setMessage(ui.advancedMsg, "Enregistrement…");
  send({ type: "update_settings", values });
});

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("sw.js").then((reg) => {
    reg.update();
  }).catch(() => { /* PWA non installable, l'appli fonctionne quand même */ });
}

consumePairingToken();
connect();
