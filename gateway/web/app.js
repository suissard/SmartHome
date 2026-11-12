// Client web SmartHome : connexion WebSocket à la passerelle, conversation en streaming,
// micro (voir recorder.js), confirmations des actions dangereuses, lecture de la voix,
// choix du modèle et paramètres du serveur (formulaire généré d'après core/settings_store.py).
import { Recorder, toBase64 } from "./recorder.js";

const $ = (id) => document.getElementById(id);
const ui = {
  log: $("log"), empty: $("empty"), emptyContent: $("empty-content"),
  authBanner: $("auth-banner"), authBannerBtn: $("auth-banner-btn"),
  authBannerHost: $("auth-banner-host"), authBannerMode: $("auth-banner-mode"),
  status: $("status"), loginBtn: $("login-btn"),
  updatePill: $("update-pill"), updatePillText: $("update-pill-text"),
  adminBtn: $("admin-btn"), connPill: $("conn-pill"),
  connPillAvatar: $("conn-pill-avatar"), connPillName: $("conn-pill-name"), connPillRole: $("conn-pill-role"),
  liveAnnouncer: $("live-announcer"), toast: $("toast"),
  scrollBottomBtn: $("scroll-bottom-btn"), newChatBtn: $("new-chat-btn"), resetConfirm: $("reset-confirm"),
  convToggleBtn: $("conv-toggle-btn"), convDrawer: $("conv-drawer"), convBackdrop: $("conv-backdrop"),
  convCloseBtn: $("conv-close-btn"), convNewBtn: $("conv-new-btn"), convSearch: $("conv-search"),
  convList: $("conv-list"), convEmpty: $("conv-empty"), convCount: $("conv-count"),
  convSyncBadge: $("conv-sync-badge"), convActiveTitle: $("conv-active-title"),
  convDeleteConfirm: $("conv-delete-confirm"), convDeleteDesc: $("conv-delete-desc"),
  mic: $("mic"), voiceStop: $("voice-stop"), textForm: $("text-form"), text: $("text"),
  setup: $("setup"), setupForm: $("setup-form"), token: $("token"), setupError: $("setup-error"),
  setupCloseBtn: $("setup-close-btn"), setupCancelBtn: $("setup-cancel-btn"),
  setupServerDot: $("setup-server-dot"), setupServerInfo: $("setup-server-info"),
  setupTabAccount: $("setup-tab-account"), setupTabToken: $("setup-tab-token"),
  accountFields: $("account-fields"), tokenFields: $("token-fields"),
  identity: $("identity"), password: $("password"), tokenHelp: $("token-help"),
  userName: $("user-name"),
  connAvatar: $("conn-avatar"), connDot: $("conn-dot"), connRoleBadge: $("conn-role-badge"),
  connUserEmail: $("conn-user-email"), connStateLabel: $("conn-state-label"),
  connAuthType: $("conn-auth-type"), connToolsInfo: $("conn-tools-info"),
  connRepoInfo: $("conn-repo-info"), connVersionInfo: $("conn-version-info"),
  connUpdateBtn: $("conn-update-btn"), connAdminBtn: $("conn-admin-btn"),
  versionTagLabel: $("version-tag-label"),
  updateDialog: $("update-dialog"), updateDialogBadge: $("update-dialog-badge"),
  updateCloseBtn: $("update-close-btn"), updateFooterClose: $("update-footer-close"),
  updateRepoName: $("update-repo-name"), updateBranchName: $("update-branch-name"),
  updateRepoLink: $("update-repo-link"),
  updateLocalSha: $("update-local-sha"), updateLocalMsg: $("update-local-msg"),
  updateRemoteSha: $("update-remote-sha"), updateRemoteMsg: $("update-remote-msg"),
  updateStatusMsg: $("update-status-msg"), updateApplyBtn: $("update-apply-btn"),
  updateCheckBtn: $("update-check-btn"),
  profile: $("profile"), profileName: $("profile-name"), profileAssistantName: $("profile-assistant-name"),
  wakewordCard: $("wakeword-card"), wakewordToggle: $("wakeword-toggle"), wakewordState: $("wakeword-state"),
  wakewordHint: $("wakeword-hint"), wakewordPill: $("wakeword-pill"),
  agentCard: $("agent-card"), agentCardState: $("agent-card-state"), agentChoices: $("agent-choices"),
  profileInstructions: $("profile-instructions"), profileSave: $("profile-save"), profileMsg: $("profile-msg"),
  profileVoiceField: $("profile-voice-field"), profileVoice: $("profile-voice"), profileVoicePlay: $("profile-voice-play"),
  adminDialog: $("admin-dialog"), adminCloseBtn: $("admin-close-btn"), adminFooterClose: $("admin-footer-close"),
  pbUrlDisplay: $("pb-url-display"), pbSuperEmail: $("pb-super-email"), pbDashboardLink: $("pb-dashboard-link"),
  pbUsersCount: $("pb-users-count"), pbUsersRefresh: $("pb-users-refresh"), pbUsersList: $("pb-users-list"),
  pbCreateGroup: $("pb-create-group"), pbCreateForm: $("pb-create-form"),
  pbNewName: $("pb-new-name"), pbNewRole: $("pb-new-role"), pbNewEmail: $("pb-new-email"), pbNewPassword: $("pb-new-password"),
  pbAdminMsg: $("pb-admin-msg"), adminOpenAdvanced: $("admin-open-advanced"), adminOpenRestart: $("admin-open-restart"),
  restartConfirm: $("restart-confirm"),
  msgMenu: $("msg-menu"), msgPreview: $("msg-preview"), msgRelaunch: $("msg-relaunch"), msgEdit: $("msg-edit"), msgMenuNote: $("msg-menu-note"),
  msgEditor: $("msg-editor"), msgEditorTitle: $("msg-editor-title"), msgEditorText: $("msg-editor-text"), msgEditorSave: $("msg-editor-save"),
  settings: $("settings"), settingsLoginBtn: $("settings-login-btn"), logoutBtn: $("logout-btn"),
  speak: $("speak"), autostop: $("autostop"), sessionId: $("session-id"),
  confirm: $("confirm"), confirmQuestion: $("confirm-question"), confirmBar: $("confirm-bar"), confirmTimerText: $("confirm-timer-text"), confirmMicBtn: $("confirm-mic-btn"), confirmVoiceStatus: $("confirm-voice-status"),
  modelBadge: $("model-badge"), modelBadgeLabel: $("model-badge-label"), agentMenu: $("agent-menu"), modelCurrent: $("model-current"), modelOllama: $("model-ollama"),
  modelSelect: $("model-select"), modelDecision: $("model-decision"), modelMsg: $("model-msg"),
  attachBtn: $("attach-btn"), attachInput: $("attach-input"), attachments: $("attachments"),
  attachList: $("attachments-list"), attachNote: $("attachments-note"),
  imageViewer: $("image-viewer"), imageViewerImg: $("image-viewer-img"), imageViewerCaption: $("image-viewer-caption"),
  advanced: $("advanced"), advancedForm: $("advanced-form"), advancedFields: $("advanced-fields"), advancedMsg: $("advanced-msg"), advancedBack: $("advanced-back"),
};

// ---- Préférences locales (le stockage peut être indisponible : navigation privée...) ----
const store = {
  get(key, fallback = null) {
    try { return localStorage.getItem(`smarthome.${key}`) ?? fallback; } catch { return fallback; }
  },
  getJSON(key, fallback = null) {
    try {
      const raw = localStorage.getItem(`smarthome.${key}`);
      if (!raw) return fallback;
      return JSON.parse(raw);
    } catch { return fallback; }
  },
  set(key, value) {
    try {
      if (value === null || value === undefined) localStorage.removeItem(`smarthome.${key}`);
      else localStorage.setItem(`smarthome.${key}`, String(value));
    } catch { /* préférence non persistée */ }
  },
  setJSON(key, value) {
    try {
      if (value === null || value === undefined) localStorage.removeItem(`smarthome.${key}`);
      else localStorage.setItem(`smarthome.${key}`, JSON.stringify(value));
    } catch { /* préférence non persistée */ }
  },
};

const state = {
  ws: null,
  agent: null,             // agent externe relié à la conversation ({name, label, color}) ; null : l'assistant
  agents: [],              // agents externes que ce compte peut rejoindre
  attachments: [],         // images jointes au prochain message : [{id, name, mime, data (base64), url}]
  imageConfig: { enabled: true, max_bytes: 8000000, max_per_message: 4, max_side: 1600 },
  ready: false,
  accounts: false,         // la passerelle a des comptes utilisateurs (AUTH_PROVIDER)
  admin: true,             // l'utilisateur connecté peut modifier les paramètres et redémarrer
  pendingLogin: null,      // identifiant + mot de passe saisis, envoyés une seule fois puis oubliés
  authTried: false,
  authError: "",
  busy: 0,                 // demandes en cours (chaque demande se termine par {"type": "done"})
  botBubble: null,         // bulle de réponse en cours de streaming
  lastBotBubble: null,     // dernière réponse terminée (latence affichée dessous)
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
  assistantName: "Assistant", // nom de l'assistant affiché sur ses bulles (ready.assistant)
  wakeword: { enabled: true, available: false },  // écoute du mot-clé par le micro de l'ordinateur
  settings: null,          // groupes de paramètres du serveur (message "settings")
  modelsBy: {},            // modèles par fournisseur (complétion des champs de modèle)
  models: [],              // modèles du fournisseur : [{name, capabilities, size}]
  turnCount: 0,            // numérote les échanges de cette page (identifiant "turn" envoyé au serveur)
  eventTurn: null,         // échange de l'événement en cours de traitement : les bulles créées lui appartiennent
  droppedTurns: new Set(), // échanges effacés : leurs derniers événements sont ignorés
  menuTarget: null,        // bulle visée par le menu d'appui long
  conversations: [],       // liste des conversations : [{id, title, updated, created, messages, tools, message_count}]
  currentConversationId: null, // identifiant de la conversation active
  pendingDeleteConvId: null,   // conversation en attente de suppression
  currentTurnTools: [],    // outils exécutés lors du tour courant
  superadmin: false,       // superadmin référencé sur PocketBase (_superusers)
  user: null,              // profil de l'utilisateur connecté
  tools: [],               // outils autorisés pour l'utilisateur courant
  pocketbaseUrl: "http://127.0.0.1:8090", // URL de PocketBase
  pbUsers: [],             // liste des comptes PocketBase (superadmin)
  versionInfo: null,       // informations de version locale vs dépôt GitHub
  feedback: { enabled: false, comment_max: 2000 }, // pouce sous les réponses (ready.feedback)
  memory: { enabled: false, max_chars: 300 },       // souvenirs du compte (ready.memory)
  household: false,        // ce compte voit les conversations tenues au micro de l'ordinateur
  readonlyConversation: null, // conversation du micro affichée (lecture seule) ; null : conversation de la session
};

// Éléments du fil de conversation (effacés ensemble au changement de conversation)
const LOG_ITEMS = ".msg, .tool, .tool-pastille, .feedback, .timings, .readonly-banner";
const HOUSEHOLD_AUTHOR = "Foyer (micro)";

// ---- Synchronisation de la hauteur visible (évite que la barre de saisie en bas sorte de l'écran) ----
function syncViewportHeight() {
  const candidates = [window.innerHeight];
  if (document.documentElement?.clientHeight > 0) {
    candidates.push(document.documentElement.clientHeight);
  }
  if (window.visualViewport?.height > 0) {
    candidates.push(Math.round(window.visualViewport.height));
  }
  const visibleHeight = Math.max(280, Math.min(...candidates.filter((v) => Number.isFinite(v) && v > 0)));
  document.documentElement.style.setProperty("--app-height", `${visibleHeight}px`);
}
syncViewportHeight();
window.addEventListener("resize", syncViewportHeight, { passive: true });
window.addEventListener("orientationchange", syncViewportHeight, { passive: true });
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", syncViewportHeight, { passive: true });
  window.visualViewport.addEventListener("scroll", syncViewportHeight, { passive: true });
}

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

// Bulle « en train d'écrire » (trois points animés) : visible tant qu'une demande est en cours
// et qu'aucun texte de réponse n'arrive, toujours en bas du fil
let typingIndicator = null;
function updateTypingIndicator() {
  const streaming = state.botBubble && state.botBubble.textContent.trim();
  const show = state.ready && state.busy > 0 && !streaming;
  if (!show) {
    typingIndicator?.remove();
    return;
  }
  if (!typingIndicator) {
    typingIndicator = document.createElement("div");
    typingIndicator.className = "typing-indicator";
    typingIndicator.setAttribute("role", "status");
    typingIndicator.setAttribute("aria-label", "L'assistant réfléchit");
    typingIndicator.innerHTML = "<span></span><span></span><span></span>";
  }
  if (state.agent) typingIndicator.style.setProperty("--bubble-agent-color", state.agent.color);
  else typingIndicator.style.removeProperty("--bubble-agent-color");
  if (ui.log.lastElementChild !== typingIndicator) {
    ui.log.append(typingIndicator);
    scrollDown();
  }
}

function addBubble(kind, text) {
  ui.empty.hidden = true;
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.textContent = text;
  // Nom de l'auteur affiché au-dessus de la bulle (pseudo-élément : survit aux mises à jour du texte)
  if (kind.startsWith("user")) el.dataset.author = userDisplayName();
  else if (kind.startsWith("bot")) el.dataset.author = state.assistantName;
  if (kind.startsWith("bot") && state.agent) markAgentBubble(el, state.agent);
  el.tabIndex = 0;  // touche « menu » du clavier : voir l'événement contextmenu
  if (state.eventTurn) el.dataset.turn = state.eventTurn;
  ui.log.append(el);
  scrollDown(true);
  return el;
}

function userDisplayName() {
  const user = state.user;
  return user ? (user.name || user.email || "Vous") : "Vous";
}

// Noms de l'assistant et de l'utilisateur : bulles déjà affichées mises à jour (profil ou réglage modifié)
function refreshAuthors() {
  for (const el of ui.log.querySelectorAll(".msg.user:not([data-household])")) el.dataset.author = userDisplayName();
  for (const el of ui.log.querySelectorAll(".msg.bot")) el.dataset.author = state.assistantName;
}

// État public envoyé par le serveur (ready, profile_saved, settings_changed) : nom de l'assistant, écoute du mot-clé
function applyPublicState(event) {
  if (event.assistant?.name) state.assistantName = event.assistant.name;
  if (ui.profileAssistantName && event.assistant) ui.profileAssistantName.placeholder = event.assistant.default_name || "";
  if (event.wakeword) state.wakeword = event.wakeword;
  refreshAuthors();
  renderWakeword();
}

function renderWakeword() {
  const { enabled, available } = state.wakeword;
  if (ui.wakewordToggle) {
    ui.wakewordToggle.checked = Boolean(enabled);
    ui.wakewordToggle.disabled = !state.admin;
  }
  if (ui.wakewordCard) ui.wakewordCard.dataset.state = enabled ? "on" : "off";
  if (ui.wakewordState) ui.wakewordState.textContent = enabled
    ? `Le micro de l'ordinateur attend « ${state.assistantName} »`
    : "Coupé : le mot-clé n'est plus détecté sur l'ordinateur";
  if (ui.wakewordHint) {
    const hints = [];
    if (!available) hints.push("SmartHome tourne sans micro local (passerelle seule) : ce réglage s'appliquera au prochain lancement avec micro.");
    if (!state.admin) hints.push("Réservé aux administrateurs.");
    ui.wakewordHint.textContent = hints.join(" ");
    ui.wakewordHint.hidden = !hints.length;
  }
  // Pastille dans la barre du haut : visible seulement quand l'écoute est coupée
  if (ui.wakewordPill) ui.wakewordPill.hidden = Boolean(enabled) || !state.ready;
}

function setWakeword(enabled) {
  if (!state.admin) return;
  state.wakeword = { ...state.wakeword, enabled };
  renderWakeword();
  send({ type: "update_settings", values: { WAKEWORD_ENABLED: enabled } });
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

const TOOL_ICONS = {
  volume: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>`,
  mute: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3 3 4.27l4.73 4.73H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4 9.91 6.09 12 8.18V4z"/></svg>`,
  unmute: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>`,
  media: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>`,
  media_play_pause: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>`,
  media_next: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 18 8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>`,
  media_prev: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg>`,
  open: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>`,
  open_app: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>`,
  close: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`,
  close_app: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`,
  lock: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>`,
  screen_off: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 3H3c-1.11 0-2 .89-2 2v12a2 2 0 0 0 2 2h5v2h8v-2h5c1.1 0 1.99-.9 1.99-2L23 5a2 2 0 0 0-2-2zm0 14H3V5h18v12z"/></svg>`,
  brightness: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 8.69V4h-4.69L12 .69 8.69 4H4v4.69L.69 12 4 15.31V20h4.69L12 23.31 15.31 20H20v-4.69L23.31 12 20 8.69zM12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6zm0-10c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z"/></svg>`,
  screenshot: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4z"/><path d="M9 2 7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z"/></svg>`,
  shutdown: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3h-2v10h2V3zm4.83 2.17-1.42 1.42A6.92 6.92 0 0 1 19 12c0 3.87-3.13 7-7 7A6.995 6.995 0 0 1 7.58 6.58L6.17 5.17A8.932 8.932 0 0 0 3 12a9 9 0 0 0 18 0c0-2.74-1.23-5.18-3.17-6.83z"/></svg>`,
  reboot: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>`,
  timer: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61 1.42-1.42c-.43-.51-.9-.99-1.41-1.41l-1.42 1.42C16.07 4.74 14.12 4 12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9 9-4.03 9-9c0-2.12-.74-4.07-1.97-5.61zM12 20c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>`,
  system_info: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14h-2v-4h2v4zm0-6h-2V7h2v4z"/></svg>`,
  audio_output: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 0 0-9 9v7c0 1.66 1.34 3 3 3h3v-8H5v-2c0-3.87 3.13-7 7-7s7 3.13 7 7v2h-4v8h3c1.66 0 3-1.34 3-3v-7a9 9 0 0 0-9-9z"/></svg>`,
  remember: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>`,
  remind: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m22 5.72-4.6-3.86-1.29 1.53 4.6 3.86L22 5.72zM7.88 3.39 6.6 1.86 2 5.71l1.29 1.53 4.59-3.85zM12.5 8H11v6l4.75 2.85.75-1.23-4-2.37V8zM12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9a9 9 0 0 0 0-18zm0 16c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>`,
  routine: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m22 5.72-4.6-3.86-1.29 1.53 4.6 3.86L22 5.72zM7.88 3.39 6.6 1.86 2 5.71l1.29 1.53 4.59-3.85zM12.5 8H11v6l4.75 2.85.75-1.23-4-2.37V8zM12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9a9 9 0 0 0 0-18zm0 16c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>`,
  list_reminders: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m22 5.72-4.6-3.86-1.29 1.53 4.6 3.86L22 5.72zM7.88 3.39 6.6 1.86 2 5.71l1.29 1.53 4.59-3.85zM12.5 8H11v6l4.75 2.85.75-1.23-4-2.37V8zM12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9a9 9 0 0 0 0-18zm0 16c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>`,
  cancel_reminder: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m22 5.72-4.6-3.86-1.29 1.53 4.6 3.86L22 5.72zM7.88 3.39 6.6 1.86 2 5.71l1.29 1.53 4.59-3.85zM12.5 8H11v6l4.75 2.85.75-1.23-4-2.37V8zM12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9a9 9 0 0 0 0-18zm0 16c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>`,
  sleep: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.3 2a10 10 0 0 0-1.9 20 10.04 10.04 0 0 0 9.6-7.2A8 8 0 0 1 12.3 2z"/></svg>`,
  search_files: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>`,
  show_image: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>`,
  notify: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>`,
  default: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>`
};

TOOL_ICONS.list_memories = TOOL_ICONS.forget_memory = TOOL_ICONS.remember;

function getToolIcon(name) {
  const key = (name || "").toLowerCase().trim();
  return TOOL_ICONS[key] || TOOL_ICONS[key.replace(/_action$/, "")] || TOOL_ICONS.default;
}

function formatActionLabel(name, args = {}, executed = true) {
  let label = "";
  const key = (name || "").toLowerCase();
  const rawArg = typeof args === "string" ? args : (args?.raw ?? "");
  switch (key) {
    case "volume": {
      const lvl = args?.level ?? (rawArg && !isNaN(rawArg) ? rawArg : null);
      if (lvl !== null && lvl !== undefined) label = `Volume réglé à ${lvl} %`;
      else if (rawArg === "up" || rawArg === "+") label = "Volume augmenté";
      else if (rawArg === "down" || rawArg === "-") label = "Volume diminué";
      else label = "Réglage du volume";
      break;
    }
    case "mute":
      label = (args?.action === "unmute" || rawArg === "unmute") ? "Son réactivé" : "Son coupé";
      break;
    case "unmute":
      label = "Son réactivé";
      break;
    case "media":
    case "media_play_pause": {
      const act = args?.action || rawArg;
      label = act === "play" ? "Lecture reprise" :
              act === "pause" ? "Musique en pause" :
              act === "next" ? "Piste suivante" :
              act === "prev" || act === "previous" ? "Piste précédente" :
              "Contrôle des médias";
      break;
    }
    case "media_next":
      label = "Piste suivante";
      break;
    case "media_prev":
      label = "Piste précédente";
      break;
    case "notify":
      label = (args?.message || rawArg) ? `Notification : ${args?.message || rawArg}` : "Notification envoyée";
      break;
    case "open":
    case "open_app": {
      const app = args?.app || rawArg || "inconnue";
      label = `Application ouverte : ${app}`;
      break;
    }
    case "close":
    case "close_app": {
      const app = args?.app || rawArg || "inconnue";
      label = `Application fermée : ${app}`;
      break;
    }
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
    case "brightness": {
      const lvl = args?.level ?? (rawArg && !isNaN(rawArg) ? rawArg : null);
      if (lvl !== null && lvl !== undefined) label = `Luminosité fixée à ${lvl} %`;
      else if (rawArg === "up") label = "Luminosité augmentée";
      else if (rawArg === "down") label = "Luminosité diminuée";
      else label = "Réglage de la luminosité";
      break;
    }
    case "screenshot":
      label = "Capture d'écran enregistrée";
      break;
    case "system_info":
      label = "État du système vérifié";
      break;
    case "sleep":
      label = "Assistant mis en veille";
      break;
    case "timer": {
      const s = args?.seconds || rawArg;
      label = s ? `Minuteur : ${s} s` : "Minuteur programmé";
      break;
    }
    case "remind":
    case "routine": {
      const what = (args?.args || rawArg || "").split("|").map((x) => x.trim());
      const kind = key === "routine" ? "Routine" : "Rappel";
      label = what[1] ? `${kind} ${what[0]} : ${what[1]}` : `${kind} programmé${key === "routine" ? "e" : ""}`;
      break;
    }
    case "list_reminders":
      label = "Rappels consultés";
      break;
    case "remember": {
      const fact = args?.args || rawArg;
      label = fact ? `Retenu : ${fact}` : "Souvenir enregistré";
      break;
    }
    case "list_memories":
      label = "Souvenirs consultés";
      break;
    case "forget_memory":
      label = "Souvenir oublié";
      break;
    case "cancel_reminder":
      label = "Rappel annulé";
      break;
    case "search_files": {
      const q = args?.args || rawArg;
      label = q ? `Recherche de fichiers : « ${q} »` : "Recherche de fichiers";
      break;
    }
    case "show_image": {
      const path = args?.args || rawArg;
      label = path ? `Image montrée : ${path.split("/").pop()}` : "Image montrée";
      break;
    }
    case "audio_output": {
      const sink = args?.sink || rawArg;
      label = sink ? `Sortie audio : ${sink}` : "Sortie audio modifiée";
      break;
    }
    default: {
      const clean = name.replace(/_/g, " ");
      label = `Action : ${clean}`;
      break;
    }
  }
  return executed ? label : `${label} — non exécutée`;
}

function createToolPastille(tool, turn = null) {
  const el = document.createElement("div");
  const isOk = tool.executed !== false;
  el.className = `tool-pastille ${isOk ? "ok" : "refused"}`;
  if (turn) el.dataset.turn = turn;

  const label = formatActionLabel(tool.name, tool.arguments, isOk);
  const signature = formatActionSignature(tool.name, tool.arguments);
  const iconSvg = getToolIcon(tool.name);
  const statusIcon = isOk
    ? `<svg class="pastille-status-icon ok" viewBox="0 0 24 24"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`
    : `<svg class="pastille-status-icon refused" viewBox="0 0 24 24"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`;

  el.innerHTML = `
    <span class="pastille-tool-icon" aria-hidden="true">${iconSvg}</span>
    <span class="pastille-label">${escapeHtml(label)}</span>
    <span class="pastille-status" aria-hidden="true">${statusIcon}</span>
  `;

  const detail = tool.output ? `${signature} → ${tool.output}` : signature;
  el.title = detail;
  el.setAttribute("aria-label", `${label} (${signature})${tool.output ? `. Résultat : ${tool.output}` : ""}`);

  el.addEventListener("click", () => {
    showToast(`${signature}${tool.output ? ` : ${tool.output}` : ""}`, isOk ? "ok" : "error");
  });

  return el;
}

function addToolChip(event) {
  const el = createToolPastille(event, state.eventTurn);
  ui.log.append(el);
  scrollDown();

  state.currentTurnTools.push(event);
  recordToolInCurrentConversation(event);
}

function setStatus(stateName, label) {
  ui.status.dataset.state = stateName;
  ui.status.textContent = label;
  if (ui.connDot) ui.connDot.dataset.state = stateName;
  if (ui.connStateLabel) ui.connStateLabel.textContent = label;
}

function isSpeaking() {
  return state.playing.size > 0 || state.audioPending > 0;
}

// Bouton principal : arrêter l'écoute, envoyer le texte saisi, sinon parler
function updateMainButton() {
  const recording = Boolean(state.recorder);
  const mode = recording ? "recording" : ui.text.value.trim() || state.attachments.length ? "send" : "idle";
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
  if (ui.attachBtn) {
    ui.attachBtn.disabled = !enabled;
    ui.attachBtn.hidden = state.imageConfig.enabled === false;
  }
  if (ui.loginBtn) ui.loginBtn.hidden = enabled;
  if (ui.connPill) ui.connPill.hidden = !enabled;
  if (ui.adminBtn) ui.adminBtn.hidden = !(enabled && state.superadmin);
  if (ui.connAdminBtn) ui.connAdminBtn.hidden = !(enabled && state.superadmin);
  if (ui.status) {
    ui.status.classList.add("interactive");
    ui.status.title = enabled
      ? "Connecté — cliquer pour voir les informations de connexion"
      : "État de la connexion (cliquer pour se connecter)";
  }
  if (ui.authBanner) ui.authBanner.hidden = enabled;
  if (ui.emptyContent) ui.emptyContent.hidden = !enabled;
  if (ui.settingsLoginBtn) {
    ui.settingsLoginBtn.textContent = enabled ? "Changer de compte / jeton" : "Se connecter";
  }
  if (ui.logoutBtn) {
    ui.logoutBtn.hidden = !enabled;
  }
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
    // Avec des comptes : identifiant + mot de passe juste saisis (jamais enregistrés), sinon le jeton du compte
    const login = state.pendingLogin;
    state.pendingLogin = null;
    ws.send(JSON.stringify({
      type: "auth", token: store.get("token", ""), session: store.get("session"),
      ...(login ? { identity: login.identity, password: login.password } : { user_token: store.get("userToken") }),
    }));
  });

  ws.addEventListener("message", (msg) => {
    let event;
    try { event = JSON.parse(msg.data); } catch { return; }
    // Seule la fin d'un échange effacé compte encore : elle tient le compte des demandes en cours
    if (state.droppedTurns.has(event.turn) && event.type !== "done") return;
    state.eventTurn = event.turn ?? null;
    handleEvent(event);
    state.eventTurn = null;
    updateTypingIndicator();
  });

  ws.addEventListener("close", (e) => {
    state.ready = false;
    state.busy = 0;
    refreshControls();
    renderAgentChoices();
    if (e.code === 4401) {
      setStatus("offline", "Connexion requise");
      // Le jeton du compte a expiré ou a été révoqué : il ne sert plus à rien
      const hadCredentials = Boolean(store.get("token") || store.get("userToken") || state.authTried);
      store.set("userToken", null);
      state.authTried = false;
      openSetup(hadCredentials ? (state.authError || "Identifiants refusés par la passerelle.") : "Veuillez vous authentifier.");
      state.authError = "";
      return;
    }
    if (e.code === 4403) {
      setStatus("offline", "Jeton requis");
      addBubble("error", "Accès distant refusé : la passerelle n'a pas de jeton (GATEWAY_AUTH_TOKEN). Configurez-en un sur l'ordinateur.");
      openSetup("Jeton requis pour l'accès distant (GATEWAY_AUTH_TOKEN).");
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

// Micro ouvert / fermé : l'ordinateur, qui entend la même voix, ignore alors son mot-clé et reste en veille
function announceMic(active) {
  send({ type: "listening", active });
}

// ---- Événements du cœur ----
function handleEvent(event) {
  switch (event.type) {
    case "ready":
      state.ready = true;
      state.reconnectDelay = 1000;
      state.audioConfig = event.audio;
      state.confirmTimeout = event.confirm_timeout || 20;
      state.tools = event.tools || [];
      if (event.images) state.imageConfig = event.images;
      if (event.pocketbase_url) state.pocketbaseUrl = event.pocketbase_url;
      state.feedback = { enabled: false, comment_max: 2000, ...(event.feedback || {}) };
      state.memory = { enabled: false, max_chars: 300, ...(event.memory || {}) };
      $("memory-card").hidden = !state.memory.enabled;
      $("memory-input").maxLength = state.memory.max_chars;
      state.household = Boolean(event.household);
      state.readonlyConversation = null;
      if (!state.household) state.conversations = state.conversations.filter((c) => c.source !== "local");
      store.set("session", event.session);
      ui.sessionId.textContent = event.session;
      if (event.conversation_id) state.currentConversationId = event.conversation_id;
      applyUser(event.user, event.accounts, state.tools, state.pocketbaseUrl);
      if (event.version) applyVersionInfo(event.version);
      if (event.profile_max) ui.profileInstructions.maxLength = event.profile_max;
      fillVoices(event.voices || [], event.user?.voice || "");
      applyPublicState(event);
      renderHistory(event.history || []);
      state.agents = event.agents || [];
      setAgent(event.agent || null, { quiet: true });
      showModel(event.llm);
      renderAgentChoices();
      refreshControls();
      send({ type: "list_conversations" });
      send({ type: "check_update" });
      updateActiveConversationUI();
      if (state.restarting) {
        state.restarting = false;
        showToast("SmartHome a redémarré", "ok");
      }
      break;
    case "conversations_list":
      if (event.conversations && Array.isArray(event.conversations)) {
        for (const sConv of event.conversations) {
          const local = state.conversations.find((c) => c.id === sConv.id);
          if (local) {
            local.title = sConv.title || local.title;
            local.updated = sConv.updated || local.updated;
            local.last_message = sConv.last_message || local.last_message;
            if (sConv.tools) local.tools = [...new Set([...(local.tools || []), ...sConv.tools])];
            if (sConv.source) local.source = sConv.source;
          } else {
            state.conversations.push(sConv);
          }
        }
        state.conversations.sort((a, b) => new Date(b.updated || b.created || 0) - new Date(a.updated || a.created || 0));
        saveConversations();
        renderConvList(ui.convSearch ? ui.convSearch.value : "");
      }
      break;
    case "conversation_loaded":
      if (event.conversation_id) {
        // Réponse tardive à un ancien choix : la conversation affichée a changé entre-temps
        if (event.conversation_id !== state.currentConversationId && event.readonly) break;
        state.currentConversationId = event.conversation_id;
        state.readonlyConversation = event.readonly ? event.conversation_id : null;
        renderHistory(event.history || []);
        const conv = getCurrentConversation();
        conv.messages = event.history || [];
        saveConversations();
        updateActiveConversationUI();
      }
      break;
    case "conversation_created":
      if (event.conversation_id) {
        state.currentConversationId = event.conversation_id;
        state.currentTurnTools = [];
        ui.log.querySelectorAll(LOG_ITEMS).forEach((el) => el.remove());
        ui.empty.hidden = false;
        updateActiveConversationUI();
      }
      break;
    case "history_updated":
      // Échange au micro de l'ordinateur : liste rafraîchie, et conversation rechargée si elle est affichée
      clearTimeout(historyRefreshTimer);
      historyRefreshTimer = setTimeout(() => {
        send({ type: "list_conversations" });
        if (state.readonlyConversation && state.readonlyConversation === event.conversation_id) {
          send({ type: "load_conversation", conversation_id: event.conversation_id, source: "local" });
        }
      }, 400);
      break;
    case "feedback_saved":
      onFeedbackSaved(event);
      break;
    case "feedback_error":
      showToast(event.message || "Note non enregistrée", "error");
      if (event.turn) for (const el of feedbackControls(event.turn)) renderFeedback(el);
      break;
    case "conversation_deleted":
      if (event.conversation_id) {
        state.conversations = state.conversations.filter((c) => c.id !== event.conversation_id);
        saveConversations();
        renderConvList(ui.convSearch ? ui.convSearch.value : "");
      }
      break;
    case "restarting":
      state.restarting = true;
      state.reconnectDelay = 1000;
      for (const dialog of [ui.settings, ui.advanced, ui.adminDialog, ui.updateDialog]) if (dialog?.open) dialog.close();
      showToast("Redémarrage de SmartHome…", "ok");
      break;
    case "version_info":
      applyVersionInfo(event);
      break;
    case "update_applied":
      onUpdateApplied(event);
      break;
    case "transcript":
      if (state.pendingUser) {
        state.pendingUser.textContent = event.text || "(rien compris)";
        state.pendingUser = null;
      } else {
        addBubble("user", event.text);
      }
      recordMessageInCurrentConversation("user", event.text, state.eventTurn);
      break;
    case "agent_changed":
      setAgent(event.agent || null);
      break;
    case "token":
      if (!state.botBubble) {
        state.botBubble = addBubble("bot pending", "");
      }
      state.botBubble.textContent += event.text;
      scrollDown();
      break;
    case "tool":
      if (["remind", "routine"].includes(event.name)) askNotificationPermission();
      // L'outil s'exécute pendant la réponse : la suite du texte part dans une nouvelle bulle
      if (state.botBubble && !state.botBubble.textContent.trim()) state.botBubble.remove();
      state.botBubble?.classList.remove("pending");
      state.botBubble = null;
      addToolChip(event);
      break;
    case "toast":
      showToast(event.message, event.kind || "warn");
      break;
    case "warning":
      // Ex : modèle sans vision, l'image n'a pas été transmise
      addNotice(event.message);
      announce(event.message);
      break;
    case "image":
      // Image montrée par l'assistant (outil show_image) : la suite du texte part dans une nouvelle bulle
      if (state.botBubble && !state.botBubble.textContent.trim()) state.botBubble.remove();
      state.botBubble?.classList.remove("pending");
      state.botBubble = null;
      addImageBubble(event);
      break;
    case "confirm_dismiss":
      if (ui.confirm.open) {
        clearInterval(confirmTimer);
        clearInterval(confirmSpeechCheckTimer);
        confirmSpeechCheckTimer = null;
        if (state.recorder) {
          state.recorder.stop();
          state.recorder = null;
          announceMic(false);
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
      if (event.tools && Array.isArray(event.tools)) {
        for (const t of event.tools) {
          if (!state.currentTurnTools.some((x) => x.name === t.name)) {
            addToolChip(t);
          }
        }
      }
      recordMessageInCurrentConversation("assistant", event.text, state.eventTurn, state.currentTurnTools);
      state.currentTurnTools = [];
      // Les échanges avec un agent externe ne sont pas archivés : rien à noter
      if (event.text && state.eventTurn && !event.agent) addFeedbackControl(state.eventTurn);
      if (event.end_conversation) {
        const el = document.createElement("div");
        el.className = "tool-pastille";
        el.innerHTML = `<span class="pastille-tool-icon" aria-hidden="true">${TOOL_ICONS.sleep}</span><span class="pastille-label">Conversation terminée</span>`;
        ui.log.append(el);
        scrollDown();
      }
      break;
    case "timings":
      showTimings(event.timings);
      break;
    case "reminder":
      showReminder(event);
      break;
    case "memories":
      renderMemories(event.memories || []);
      break;
    case "memory_error":
      $("memory-msg").textContent = event.message;
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
      else {
        state.authError = event.message;
        state.accounts = Boolean(event.accounts);
      }
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
      ui.log.querySelectorAll(LOG_ITEMS).forEach((el) => el.remove());
      ui.empty.hidden = false;
      if (event.conversation_id) state.currentConversationId = event.conversation_id;
      state.currentTurnTools = [];
      updateActiveConversationUI();
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
    case "profile_saved":
      applyUser(event.user, state.accounts, state.tools, state.pocketbaseUrl);
      applyPublicState(event);
      setMessage(ui.profileMsg, "Profil enregistré : pris en compte dès votre prochaine demande.", "ok");
      break;
    case "pb_users":
      state.pbUsers = event.users || [];
      if (event.pocketbase_url) state.pocketbaseUrl = event.pocketbase_url;
      renderPbUsers();
      break;
    case "pb_user_saved":
      state.pbUsers = event.users || [];
      renderPbUsers();
      if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "Compte PocketBase enregistré.", "ok");
      if (ui.pbCreateForm) ui.pbCreateForm.reset();
      if (ui.pbCreateGroup) ui.pbCreateGroup.open = false;
      break;
    case "pb_user_deleted":
      state.pbUsers = event.users || [];
      renderPbUsers();
      if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "Compte supprimé de PocketBase.", "ok");
      break;
    case "pb_admin_error":
      if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, event.message, "error");
      break;
    case "voice_preview":
      // Jouée même si la réponse vocale est coupée sur cet appareil : c'est une demande explicite
      enqueueAudio(event.data);
      break;
    case "profile_error":
      setMessage(ui.profileMsg, event.message, "error");
      break;
    case "settings_error":
      setMessage(ui.advanced.open ? ui.advancedMsg : ui.modelMsg, event.message, "error");
      break;
    case "settings_changed":
      applyPublicState(event);
      // Modifié depuis un autre appareil (ou celui-ci) : on recharge les valeurs affichées
      if (state.admin && (ui.settings.open || ui.advanced.open)) send({ type: "get_settings" });
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
  state.lastBotBubble = target;
  state.speakingBubble = target;
  if (isSpeaking()) updateSpeakingState();
  scrollDown();
  announce(text);
}

// Latence du tour (core/metrics.py), sous la réponse : réservée aux administrateurs
const TIMING_LABELS = { stt: "transcription", first_sentence: "1re phrase", llm: "génération", tts: "synthèse", total: "total" };
function formatMs(ms) {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}
function showTimings(timings) {
  const bubble = state.lastBotBubble;
  if (!state.admin || !timings || !bubble?.isConnected) return;
  const parts = Object.entries(TIMING_LABELS)
    .filter(([key]) => Number.isFinite(timings[key]))
    .map(([key, label]) => `${label} ${formatMs(timings[key])}`);
  if (!parts.length) return;
  const el = document.createElement("div");
  el.className = "timings";
  el.textContent = `⏱ ${parts.join(" · ")}`;
  el.title = "Temps écoulé depuis la réception de la demande";
  bubble.after(el);
  state.lastBotBubble = null;
}

// Rappel ou routine arrivé à échéance (core/scheduler.py) : pastille dans la conversation et notification système
function askNotificationPermission() {
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
}
function showReminder(event) {
  const text = event.text || event.message || "Rappel";
  const el = document.createElement("div");
  el.className = "tool-pastille reminder";
  el.innerHTML = `<span class="pastille-tool-icon" aria-hidden="true">${TOOL_ICONS.remind}</span><span class="pastille-label"></span>`;
  el.querySelector(".pastille-label").textContent = text;
  ui.log.append(el);
  ui.empty.hidden = true;
  scrollDown();
  announce(text);
  // Vibration refusée par le navigateur tant que l'utilisateur n'a pas touché la page
  if (navigator.userActivation?.hasBeenActive) navigator.vibrate?.([200, 100, 200]);
  if ("Notification" in window && Notification.permission === "granted" && document.visibilityState !== "visible") {
    const title = event.kind === "routine" ? "⏰ Routine" : "⏰ Rappel";
    // Service worker d'abord (notifications d'une PWA installée sur mobile), sinon notification de la page
    navigator.serviceWorker?.ready
      .then((reg) => reg.showNotification(title, { body: text, tag: `reminder-${event.id}`, icon: "icon-192.png" }))
      .catch(() => new Notification(title, { body: text, icon: "icon-192.png" }));
  }
}

// Souvenirs du compte (core/memory.py), dans les réglages : liste, ajout, effacement
function renderMemories(memories) {
  const list = $("memory-list");
  list.replaceChildren();
  $("memory-msg").textContent = "";
  $("memory-card-state").textContent = memories.length
    ? `${memories.length} souvenir${memories.length > 1 ? "s" : ""}, donné${memories.length > 1 ? "s" : ""} à l'assistant quand c'est utile`
    : "Rien pour l'instant. Dites « retiens que… » ou ajoutez-en un ici.";
  for (const memory of memories) {
    const item = document.createElement("li");
    const text = document.createElement("span");
    text.textContent = memory.text;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn memory-delete";
    remove.title = "Oublier";
    remove.setAttribute("aria-label", `Oublier : ${memory.text}`);
    remove.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`;
    remove.addEventListener("click", () => send({ type: "delete_memory", id: memory.id }));
    item.append(text, remove);
    list.append(item);
  }
}
function addMemory() {
  const input = $("memory-input");
  const text = input.value.trim();
  if (!text) return;
  send({ type: "add_memory", text });
  input.value = "";
}
$("memory-add-btn").addEventListener("click", addMemory);
$("memory-input").addEventListener("keydown", (e) => {
  // Le champ est dans le formulaire du dialogue : Entrée ajoute le souvenir au lieu de fermer les réglages
  if (e.key === "Enter") {
    e.preventDefault();
    addMemory();
  }
});

// ---- Demandes ----
function interruptAssistant() {
  // Barge-in : on coupe la voix ici et la génération côté serveur
  const speaking = stopPlayback();
  if (state.busy || speaking) send({ type: "stop" });
}

// ---- Gestion des Conversations & Historique ----

function generateConvId() {
  return "conv_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
}

function formatConvDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "";
  const now = new Date();
  const diffMs = now - d;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "À l'instant";
  if (diffMins < 60) return `Il y a ${diffMins} min`;

  const isToday = d.toDateString() === now.toDateString();
  if (isToday) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) {
    return "Hier";
  }
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function toggleConvDrawer(open) {
  if (!ui.convDrawer) return;
  const shouldOpen = open !== undefined ? Boolean(open) : !ui.convDrawer.classList.contains("open");
  ui.convDrawer.classList.toggle("open", shouldOpen);
  ui.convDrawer.setAttribute("aria-hidden", String(!shouldOpen));
  if (ui.convBackdrop) {
    ui.convBackdrop.hidden = !shouldOpen;
    ui.convBackdrop.classList.toggle("open", shouldOpen);
  }
  if (shouldOpen && ui.convSearch) {
    ui.convSearch.value = "";
    renderConvList();
    ui.convSearch.focus();
  }
}

function saveConversations() {
  store.setJSON("conversations", state.conversations);
}

function getCurrentConversation() {
  if (!state.currentConversationId) {
    state.currentConversationId = generateConvId();
  }
  let conv = state.conversations.find((c) => c.id === state.currentConversationId);
  if (!conv) {
    conv = {
      id: state.currentConversationId,
      title: "Nouvelle conversation",
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      messages: [],
      tools: [],
      messageCount: 0,
    };
    state.conversations.unshift(conv);
    saveConversations();
  }
  return conv;
}

function updateActiveConversationUI() {
  const conv = state.conversations.find((c) => c.id === state.currentConversationId);
  const title = conv?.title || (ui.log.querySelector(".msg") ? "Conversation" : "");
  if (ui.convActiveTitle) {
    ui.convActiveTitle.textContent = title && title !== "Nouvelle conversation" ? title : "";
  }
  renderConvList(ui.convSearch ? ui.convSearch.value : "");
}

function renderConvList(filterText = "") {
  if (!ui.convList) return;
  const filter = filterText.toLowerCase().trim();
  const filtered = state.conversations.filter((c) => {
    if (!filter) return true;
    return (
      (c.title || "").toLowerCase().includes(filter) ||
      (c.last_message || "").toLowerCase().includes(filter) ||
      (c.tools || []).some((t) => t.toLowerCase().includes(filter))
    );
  });

  ui.convList.replaceChildren(
    ...filtered.map((conv) => {
      const li = document.createElement("li");
      li.className = `conv-item ${conv.id === state.currentConversationId ? "active" : ""}`;
      li.tabIndex = 0;
      li.dataset.id = conv.id;

      const top = document.createElement("div");
      top.className = "conv-item-top";

      const title = document.createElement("span");
      title.className = "conv-item-title";
      title.textContent = conv.title || "Nouvelle conversation";

      const date = document.createElement("span");
      date.className = "conv-item-date";
      date.textContent = formatConvDate(conv.updated || conv.created);

      const delBtn = document.createElement("button");
      delBtn.className = "conv-item-delete";
      delBtn.type = "button";
      delBtn.setAttribute("aria-label", "Supprimer cette conversation");
      delBtn.title = "Supprimer";
      delBtn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`;
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        confirmDeleteConversation(conv.id, conv.title);
      });

      if (conv.source === "local") {
        // Conversation au micro de l'ordinateur : appartient au foyer, jamais supprimée depuis la PWA
        li.classList.add("household");
        const badge = document.createElement("span");
        badge.className = "conv-item-badge";
        badge.title = "Conversation au micro de l'ordinateur";
        badge.innerHTML = `${HOUSE_ICON}<span>Micro</span>`;
        top.append(badge, title, date);
      } else {
        top.append(title, date, delBtn);
      }

      const snippet = document.createElement("div");
      snippet.className = "conv-item-snippet";
      snippet.textContent = conv.last_message || "Aucun échange";

      li.append(top, snippet);

      if (conv.tools && conv.tools.length) {
        const toolsDiv = document.createElement("div");
        toolsDiv.className = "conv-item-tools";
        const uniqueTools = [...new Set(conv.tools)].slice(0, 4);
        for (const t of uniqueTools) {
          const badge = document.createElement("span");
          badge.className = "mini-tool-pastille";
          badge.innerHTML = `${getToolIcon(t)} ${escapeHtml(t)}`;
          badge.title = t;
          toolsDiv.append(badge);
        }
        li.append(toolsDiv);
      }

      li.addEventListener("click", () => {
        selectConversation(conv.id);
      });

      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectConversation(conv.id);
        }
      });

      return li;
    })
  );

  if (ui.convEmpty) {
    ui.convEmpty.hidden = filtered.length > 0;
  }
  if (ui.convCount) {
    const total = state.conversations.length;
    ui.convCount.textContent = `${total} conversation${total > 1 ? "s" : ""}`;
  }
}

function selectConversation(convId) {
  if (state.busy) interruptAssistant();
  state.currentConversationId = convId;
  const conv = state.conversations.find((c) => c.id === convId);
  if (conv) {
    const household = conv.source === "local";
    state.readonlyConversation = household ? convId : null;
    renderHistory(conv.messages || []);
    send(household
      ? { type: "load_conversation", conversation_id: convId, source: "local" }
      : { type: "load_conversation", conversation_id: convId, messages: conv.messages || [] });
  }
  updateActiveConversationUI();
  if (window.innerWidth <= 600) {
    toggleConvDrawer(false);
  }
}

function startNewConversation() {
  if (state.busy) interruptAssistant();
  state.readonlyConversation = null;
  const newId = generateConvId();
  state.currentConversationId = newId;
  state.currentTurnTools = [];
  ui.log.querySelectorAll(LOG_ITEMS).forEach((el) => el.remove());
  ui.empty.hidden = false;
  send({ type: "new_conversation" });
  updateActiveConversationUI();
  if (window.innerWidth <= 600) {
    toggleConvDrawer(false);
  }
}

function confirmDeleteConversation(convId, title) {
  state.pendingDeleteConvId = convId;
  if (ui.convDeleteDesc) {
    ui.convDeleteDesc.textContent = `Retirer « ${title || "cette conversation"} » de votre historique ? Elle reste dans l'archive locale de SmartHome (données d'entraînement).`;
  }
  if (ui.convDeleteConfirm) {
    ui.convDeleteConfirm.showModal();
  } else if (confirm("Supprimer cette conversation ?")) {
    deleteConversation(convId);
  }
}

function deleteConversation(convId) {
  state.conversations = state.conversations.filter((c) => c.id !== convId);
  saveConversations();
  send({ type: "delete_conversation", conversation_id: convId });

  if (state.currentConversationId === convId) {
    startNewConversation();
  } else {
    renderConvList(ui.convSearch ? ui.convSearch.value : "");
  }
  showToast("Conversation supprimée", "ok");
}

function recordMessageInCurrentConversation(role, content, turn, tools = []) {
  if (!content && !tools.length) return;
  const conv = getCurrentConversation();
  conv.updated = new Date().toISOString();
  if (!conv.messages) conv.messages = [];

  const existingIdx = turn ? conv.messages.findIndex((m) => m.turn === turn && m.role === role) : -1;
  const msgObj = {
    role,
    content: content || "",
    turn: turn || newTurn(),
    tools: tools && tools.length ? tools : undefined,
  };

  if (existingIdx >= 0) {
    conv.messages[existingIdx] = msgObj;
  } else {
    conv.messages.push(msgObj);
  }

  if (role === "user" && (!conv.title || conv.title === "Nouvelle conversation")) {
    const rawTitle = content.trim();
    conv.title = rawTitle.length > 55 ? rawTitle.slice(0, 52) + "…" : rawTitle;
  }
  conv.last_message = content || (tools.length ? `[${tools[0].name}]` : "");
  conv.messageCount = conv.messages.length;

  if (tools && tools.length) {
    if (!conv.tools) conv.tools = [];
    for (const t of tools) {
      const name = t.name || t.tag || "";
      if (name && !conv.tools.includes(name)) conv.tools.push(name);
    }
  }

  state.conversations = [conv, ...state.conversations.filter((c) => c.id !== conv.id)];
  saveConversations();
  updateActiveConversationUI();
}

function recordToolInCurrentConversation(tool) {
  const conv = getCurrentConversation();
  if (!conv.tools) conv.tools = [];
  const name = tool.name || tool.tag || "";
  if (name && !conv.tools.includes(name)) {
    conv.tools.push(name);
    saveConversations();
    renderConvList(ui.convSearch ? ui.convSearch.value : "");
  }
}

function initConversations() {
  state.conversations = store.getJSON("conversations", []);
  updateActiveConversationUI();
}

// Conversation en cours renvoyée par le serveur ou chargée depuis le tiroir :
function renderHistory(messages) {
  if (!messages || !messages.length) {
    ui.empty.hidden = ui.log.querySelector(LOG_ITEMS) !== null;
    return;
  }
  ui.log.querySelectorAll(LOG_ITEMS).forEach((el) => el.remove());
  for (const message of messages) {
    if (message.role === "user") {
      const el = addBubble("user", message.content);
      if (message.turn) el.dataset.turn = message.turn;
      // Conversation au micro : la voix n'est pas identifiée, c'est le foyer qui parle
      if (state.readonlyConversation) {
        el.dataset.author = HOUSEHOLD_AUTHOR;
        el.dataset.household = "1";
      }
    } else if (message.role === "assistant") {
      if (message.tools && Array.isArray(message.tools)) {
        for (const t of message.tools) {
          const pastille = createToolPastille(t, message.turn);
          ui.log.append(pastille);
        }
      }
      if (message.content) {
        const el = addBubble("bot", message.content);
        if (message.turn) {
          el.dataset.turn = message.turn;
          addFeedbackControl(message.turn, message.feedback || null);
        }
      }
    }
  }
  if (state.readonlyConversation) {
    const banner = document.createElement("div");
    banner.className = "readonly-banner";
    banner.setAttribute("role", "note");
    banner.innerHTML = `<span aria-hidden="true">${HOUSE_ICON}</span><span>Conversation tenue au micro de l'ordinateur — lecture seule. Écrire ou parler en commence une nouvelle.</span>`;
    ui.log.prepend(banner);
  }
  ui.empty.hidden = ui.log.querySelector(LOG_ITEMS) !== null;
  scrollDown(true);
}

// ---- Note des réponses : pouce, échelle de -2 à +2, puis commentaire facultatif ----
const HOUSE_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>`;
const THUMB_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 21h4V9H2v12zm20-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L13.17 1 6.59 7.59C6.22 7.95 6 8.45 6 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg>`;
const FEEDBACK_SCALE = [
  { value: -2, label: "Très mauvaise" },
  { value: -1, label: "Mauvaise" },
  { value: 0, label: "Moyenne" },
  { value: 1, label: "Bonne" },
  { value: 2, label: "Excellente" },
];
let historyRefreshTimer = null;

function formatRating(value) {
  return value > 0 ? `+${value}` : String(value);
}

function feedbackControls(turn) {
  return [...ui.log.querySelectorAll(".feedback")].filter((el) => el.dataset.turn === turn);
}

function leaveReadonlyConversation() {
  if (state.readonlyConversation) startNewConversation();
}

// Contrôle placé sous la dernière bulle de l'échange (une réponse coupée par des outils en a plusieurs)
function addFeedbackControl(turn, feedback = null) {
  if (!state.feedback.enabled || !turn || !state.currentConversationId) return;
  for (const old of feedbackControls(turn)) old.remove();
  const el = document.createElement("div");
  el.className = "feedback";
  el.dataset.turn = turn;
  el.dataset.conversation = state.currentConversationId;
  el.innerHTML = `
    <button type="button" class="feedback-thumb" aria-expanded="false">
      ${THUMB_ICON}<span class="feedback-value"></span>
    </button>
    <div class="feedback-panel" hidden>
      <div class="feedback-scale" role="radiogroup" aria-label="Satisfaction, de -2 (très mauvaise) à +2 (excellente)">
        ${FEEDBACK_SCALE.map((s) => `
          <button type="button" role="radio" aria-checked="false" class="feedback-step" data-value="${s.value}" title="${s.label}">
            <span class="feedback-step-value">${formatRating(s.value)}</span>
            <span class="feedback-step-label">${s.label}</span>
          </button>`).join("")}
      </div>
      <form class="feedback-comment" hidden>
        <textarea rows="2" placeholder="Un commentaire ? (facultatif) — ce qui manquait, ce qui était faux…"
          aria-label="Commentaire sur la réponse"></textarea>
        <div class="feedback-actions">
          <button type="button" class="feedback-close">Fermer</button>
          <button type="submit" class="feedback-send">Envoyer</button>
        </div>
      </form>
    </div>`;
  el.querySelector("textarea").maxLength = state.feedback.comment_max || 2000;
  if (feedback && Number.isInteger(feedback.rating)) {
    el.dataset.rating = String(feedback.rating);
    el.dataset.comment = feedback.comment || "";
  }
  renderFeedback(el);

  const thumb = el.querySelector(".feedback-thumb");
  thumb.addEventListener("click", () => toggleFeedback(el));
  for (const step of el.querySelectorAll(".feedback-step")) {
    step.addEventListener("click", () => {
      el.dataset.pending = step.dataset.value;
      sendFeedback(el, Number(step.dataset.value), el.querySelector("textarea").value);
      const form = el.querySelector(".feedback-comment");
      form.hidden = false;
      renderFeedback(el);
      el.querySelector("textarea").focus({ preventScroll: true });
      scrollDown();
    });
  }
  el.querySelector(".feedback-comment").addEventListener("submit", (e) => {
    e.preventDefault();
    const rating = Number(el.dataset.pending ?? el.dataset.rating);
    if (!Number.isInteger(rating)) return;
    el.dataset.closeOnSave = "1";
    sendFeedback(el, rating, el.querySelector("textarea").value);
  });
  el.querySelector(".feedback-close").addEventListener("click", () => toggleFeedback(el, false));
  el.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !el.querySelector(".feedback-panel").hidden) {
      e.stopPropagation();
      toggleFeedback(el, false);
      thumb.focus();
    }
  });

  // Après la dernière bulle (ou pastille) de l'échange
  const items = turnElements(turn, ".msg, .tool, .tool-pastille");
  const last = items[items.length - 1];
  if (last) last.after(el);
  else ui.log.append(el);
  scrollDown();
}

function toggleFeedback(el, open) {
  const panel = el.querySelector(".feedback-panel");
  const show = open ?? panel.hidden;
  for (const other of ui.log.querySelectorAll(".feedback.open")) if (other !== el) toggleFeedback(other, false);
  panel.hidden = !show;
  el.classList.toggle("open", show);
  el.querySelector(".feedback-thumb").setAttribute("aria-expanded", String(show));
  // Une note déjà donnée : son commentaire reste modifiable
  const form = el.querySelector(".feedback-comment");
  form.hidden = !(show && el.dataset.rating !== undefined);
  if (show) {
    el.querySelector("textarea").value = el.dataset.comment || "";
    const current = el.querySelector(`.feedback-step[aria-checked="true"]`) || el.querySelector(".feedback-step");
    current.focus({ preventScroll: true });
    scrollDown();
  } else {
    delete el.dataset.pending;
  }
}

function renderFeedback(el) {
  const rating = el.dataset.pending ?? el.dataset.rating;
  const has = rating !== undefined && rating !== "";
  el.dataset.level = has ? rating : "";
  const value = el.querySelector(".feedback-value");
  value.textContent = has ? formatRating(Number(rating)) : "";
  const thumb = el.querySelector(".feedback-thumb");
  const label = has
    ? `Réponse notée ${formatRating(Number(rating))} (${FEEDBACK_SCALE.find((s) => String(s.value) === rating)?.label || ""}) : modifier`
    : "Noter cette réponse";
  thumb.setAttribute("aria-label", label);
  thumb.title = label;
  for (const step of el.querySelectorAll(".feedback-step")) {
    step.setAttribute("aria-checked", String(step.dataset.value === rating));
  }
}

function sendFeedback(el, rating, comment) {
  if (!state.ready) {
    showToast("Hors ligne : note non envoyée", "error");
    return;
  }
  send({
    type: "feedback",
    conversation_id: el.dataset.conversation,
    turn: el.dataset.turn,
    rating,
    comment: (comment || "").trim(),
  });
}

function onFeedbackSaved(event) {
  for (const el of feedbackControls(event.turn)) {
    if (el.dataset.conversation !== event.conversation_id) continue;
    el.dataset.rating = String(event.rating);
    el.dataset.comment = event.comment || "";
    delete el.dataset.pending;
    renderFeedback(el);
    if (el.dataset.closeOnSave) {
      delete el.dataset.closeOnSave;
      toggleFeedback(el, false);
      showToast("Merci pour votre avis", "ok", 2000);
    }
  }
  // Note gardée avec la conversation sur cet appareil (réaffichée hors ligne)
  const conv = state.conversations.find((c) => c.id === event.conversation_id);
  const message = conv?.messages?.find((m) => m.turn === event.turn && m.role === "assistant");
  if (message) {
    message.feedback = { rating: event.rating, comment: event.comment || "" };
    saveConversations();
  }
}

function newTurn() {
  state.turnCount += 1;
  return `${Date.now().toString(36)}-${state.turnCount}`;
}

// `forget` : échanges à retirer de l'historique du serveur avant de répondre (relance d'un message)
function sendText(text, forget = [], images = []) {
  interruptAssistant();
  leaveReadonlyConversation();
  const turn = newTurn();
  const bubble = addBubble("user", text);
  bubble.dataset.turn = turn;
  if (images.length) attachImagesToBubble(bubble, images);
  state.busy += 1;
  refreshControls();
  updateTypingIndicator();
  // Les images ne sont pas gardées dans l'historique de l'appareil (trop lourdes) : seule leur mention l'est
  const mention = images.length ? `\n🖼️ [Image(s) jointe(s) : ${images.map((i) => i.name).join(", ")}]` : "";
  recordMessageInCurrentConversation("user", `${text}${mention}`.trim(), turn);
  const payload = { type: "text", text, speak: ui.speak.checked, turn, forget };
  if (images.length) payload.images = images.map((i) => ({ data: i.data, name: i.name }));
  send(payload);
}

function sendAudio(wavBytes) {
  leaveReadonlyConversation();
  const turn = newTurn();
  state.pendingUser = addBubble("user", "🎙️ …");
  state.pendingUser.dataset.turn = turn;
  state.busy += 1;
  refreshControls();
  updateTypingIndicator();
  send({ type: "audio", data: toBase64(wavBytes), speak: ui.speak.checked, turn });
}

ui.textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  unlockAudio();
  const text = ui.text.value.trim();
  const images = state.attachments;
  if ((!text && !images.length) || !state.ready) return;
  ui.text.value = "";
  state.attachments = [];
  renderAttachments();
  updateMainButton();
  sendText(text, [], images);
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

function turnElements(turn, selector = LOG_ITEMS) {
  return [...ui.log.querySelectorAll(selector)].filter((el) => el.dataset.turn === turn);
}

// Bulle de l'utilisateur dont on peut renvoyer le texte (un message vocal sans transcription n'en a pas)
function relaunchSource(el) {
  const [source] = turnElements(el.dataset.turn, ".msg.user");
  return source && !source.textContent.startsWith("🎙️") ? source : null;
}

function openMessageMenu(el) {
  if (ui.msgMenu.open || ui.msgEditor.open) return;
  if (state.readonlyConversation) {
    showToast("Conversation du micro : lecture seule", "warn");
    return;
  }
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
  ui.empty.hidden = ui.log.querySelector(LOG_ITEMS) !== null;
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
    if (next.matches(LOG_ITEMS)) elements.push(next);
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
  if (ui.text.value.trim() || state.attachments.length) {
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
  announceMic(true);
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
  announceMic(false);
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
    announceMic(true);
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
  announceMic(false);
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
    announceMic(false);
  }
  ui.confirmMicBtn?.classList.remove("recording");
  const id = ui.confirm.dataset.requestId;
  if (!id) return;
  delete ui.confirm.dataset.requestId;
  send({ type: "confirm_response", id, accepted: ui.confirm.returnValue === "yes" });
});

// ---- Connexion & réglages ----
// Voix au choix du compte : « par défaut » (celle de l'ordinateur) puis les voix installées
function fillVoices(voices, selected) {
  ui.profileVoiceField.hidden = voices.length === 0;
  ui.profileVoice.replaceChildren();
  const fallback = voices.find((v) => v.default);
  ui.profileVoice.append(new Option(`Par défaut${fallback ? ` (${fallback.label})` : ""}`, ""));
  for (const voice of voices) ui.profileVoice.append(new Option(voice.label, voice.id));
  ui.profileVoice.value = voices.some((v) => v.id === selected) ? selected : "";
}

// Compte connecté : jeton renouvelé à mémoriser, nom affiché, outils d'administration masqués sinon
function resolvePocketBaseAdminUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl || "http://127.0.0.1:8090");
    if ((parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") && location.hostname) {
      parsed.hostname = location.hostname;
    }
    return parsed.origin.replace(/\/$/, "");
  } catch {
    return (rawUrl || "http://127.0.0.1:8090").replace(/\/$/, "");
  }
}

const ROLE_LABELS = {
  superadmin: "Superadmin",
  admin: "Admin",
  member: "Membre",
  guest: "Invité",
  local: "Local",
};

function applyUser(user, accounts, tools = state.tools, pocketbaseUrl = state.pocketbaseUrl) {
  state.user = user || null;
  state.accounts = Boolean(accounts);
  if (user?.token) store.set("userToken", user.token);

  const isSuperadmin = Boolean(user?.superadmin);
  state.superadmin = isSuperadmin;
  state.admin = !user || Boolean(user.admin) || isSuperadmin;

  const displayName = user ? (user.name || user.email || "Utilisateur") : "Accès local";
  const initial = (displayName.trim()[0] || "S").toUpperCase();
  const roleKey = isSuperadmin ? "superadmin" : (user?.role || "local");
  const roleLabel = ROLE_LABELS[roleKey] || roleKey;

  if (ui.userName) ui.userName.textContent = displayName;
  if (ui.connAvatar) ui.connAvatar.textContent = initial;
  if (ui.connRoleBadge) {
    ui.connRoleBadge.textContent = roleLabel;
    ui.connRoleBadge.dataset.role = isSuperadmin ? "superadmin" : (user?.role || "none");
  }
  if (ui.connUserEmail) {
    const sub = user?.email
      ? (isSuperadmin ? `${user.email} · Superadmin PocketBase` : user.email)
      : (user ? `Identifiant : ${user.id}` : `Hôte : ${location.host || "local"}`);
    ui.connUserEmail.textContent = sub;
  }
  if (ui.connAuthType) {
    if (isSuperadmin) {
      ui.connAuthType.textContent = "PocketBase (_superusers)";
    } else if (user?.profile) {
      ui.connAuthType.textContent = "Compte PocketBase";
    } else if (user?.id === "token") {
      ui.connAuthType.textContent = "Jeton passerelle";
    } else {
      ui.connAuthType.textContent = state.accounts ? "PocketBase" : "Réseau local";
    }
  }
  if (ui.connToolsInfo) {
    const count = Array.isArray(tools) ? tools.length : 0;
    ui.connToolsInfo.textContent = count > 0 ? `${count} outil${count > 1 ? "s" : ""} actif${count > 1 ? "s" : ""}` : "Conversation seule";
    ui.connToolsInfo.title = count > 0 ? tools.join(", ") : "Aucun outil système autorisé";
  }

  // Pastille de compte dans la barre supérieure
  if (ui.connPillAvatar) ui.connPillAvatar.textContent = initial;
  if (ui.connPillName) ui.connPillName.textContent = displayName;
  if (ui.connPillRole) {
    ui.connPillRole.textContent = roleLabel;
    ui.connPillRole.dataset.role = isSuperadmin ? "superadmin" : (user?.role || "none");
  }

  // Informations de la console Superadmin PocketBase
  const pbBase = resolvePocketBaseAdminUrl(pocketbaseUrl);
  if (ui.pbUrlDisplay) ui.pbUrlDisplay.textContent = pbBase;
  if (ui.pbSuperEmail) {
    ui.pbSuperEmail.textContent = user?.email ? `Superadmin : ${user.email}` : "Superadmin référencé dans _superusers";
  }
  if (ui.pbDashboardLink) {
    ui.pbDashboardLink.href = `${pbBase}/_/`;
  }

  // Prénom et consignes : seulement pour un compte de l'annuaire (pas le jeton administrateur)
  ui.profile.hidden = !user?.profile;
  if (user?.profile) {
    ui.profileName.value = user.name;
    ui.profileInstructions.value = user.instructions || "";
    if (ui.profileAssistantName) ui.profileAssistantName.value = user.assistant_name || "";
    if ([...ui.profileVoice.options].some((o) => o.value === (user.voice || ""))) ui.profileVoice.value = user.voice || "";
  }
  document.body.classList.toggle("not-admin", !state.admin);
}

function setSetupTab(tabName) {
  state.setupTab = tabName;
  const isAccount = tabName === "account";
  ui.setupTabAccount?.classList.toggle("active", isAccount);
  ui.setupTabAccount?.setAttribute("aria-selected", String(isAccount));
  ui.setupTabToken?.classList.toggle("active", !isAccount);
  ui.setupTabToken?.setAttribute("aria-selected", String(!isAccount));
  if (ui.accountFields) ui.accountFields.hidden = !isAccount;
  if (ui.tokenFields) ui.tokenFields.hidden = isAccount;
  if (isAccount) {
    ui.identity?.focus();
  } else {
    ui.token?.focus();
  }
}

function updateSetupTabs() {
  if (ui.setupTabAccount) {
    ui.setupTabAccount.hidden = state.accounts === false;
  }
  let targetTab = state.setupTab;
  if (!targetTab) {
    if (state.accounts === false) {
      targetTab = "token";
    } else if (state.accounts === true) {
      targetTab = "account";
    } else if (store.get("token") && !store.get("userToken")) {
      targetTab = "token";
    } else {
      targetTab = "account";
    }
  }
  setSetupTab(targetTab);
}

function openSetup(error = "") {
  updateSetupTabs();
  ui.password.value = "";
  ui.token.value = store.get("token", "");
  ui.setupError.textContent = error;
  ui.setupError.hidden = !error;
  if (!ui.setup.open) ui.setup.showModal();
}

ui.setupTabAccount?.addEventListener("click", () => setSetupTab("account"));
ui.setupTabToken?.addEventListener("click", () => setSetupTab("token"));
ui.setupCloseBtn?.addEventListener("click", () => ui.setup.close());
ui.setupCancelBtn?.addEventListener("click", () => ui.setup.close());

ui.setupForm.addEventListener("submit", (e) => {
  e.preventDefault();
  unlockAudio();
  const isAccount = (state.setupTab || "account") === "account";
  if (isAccount) {
    const identity = ui.identity.value.trim();
    const password = ui.password.value;
    if (!identity || !password) {
      ui.setupError.textContent = "Veuillez renseigner votre adresse e-mail et votre mot de passe.";
      ui.setupError.hidden = false;
      return;
    }
    state.pendingLogin = { identity, password };
    state.authTried = true;
    store.set("token", null);
  } else {
    const tokenVal = ui.token.value.trim();
    store.set("token", tokenVal || null);
    store.set("userToken", null);
    state.pendingLogin = null;
    state.authTried = true;
  }
  ui.setupError.hidden = true;
  ui.password.value = "";
  ui.setup.close();
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
  const hasMessages = ui.log.querySelectorAll(LOG_ITEMS).length > 0;
  if (!hasMessages) {
    startNewConversation();
    return;
  }
  if (ui.resetConfirm) {
    ui.resetConfirm.showModal();
  } else if (confirm("Ouvrir une nouvelle conversation ?")) {
    startNewConversation();
  }
}

ui.resetConfirm?.addEventListener("close", () => {
  if (ui.resetConfirm.returnValue === "confirm") {
    startNewConversation();
    showToast("Nouvelle conversation", "ok");
  }
});

ui.newChatBtn?.addEventListener("click", promptResetConversation);

ui.convToggleBtn?.addEventListener("click", () => {
  toggleConvDrawer();
});

ui.convCloseBtn?.addEventListener("click", () => {
  toggleConvDrawer(false);
});

ui.convBackdrop?.addEventListener("click", () => {
  toggleConvDrawer(false);
});

ui.convNewBtn?.addEventListener("click", () => {
  startNewConversation();
});

ui.convSearch?.addEventListener("input", (e) => {
  renderConvList(e.target.value);
});

ui.convDeleteConfirm?.addEventListener("close", () => {
  if (ui.convDeleteConfirm.returnValue === "confirm" && state.pendingDeleteConvId) {
    deleteConversation(state.pendingDeleteConvId);
  }
  state.pendingDeleteConvId = null;
});

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && ui.convDrawer?.classList.contains("open")) {
    toggleConvDrawer(false);
  }
});

ui.profileSave.addEventListener("click", () => {
  setMessage(ui.profileMsg, "Enregistrement…");
  const voice = ui.profileVoiceField.hidden ? {} : { voice: ui.profileVoice.value };
  send({ type: "update_profile", name: ui.profileName.value, instructions: ui.profileInstructions.value,
         assistant_name: ui.profileAssistantName?.value || "", ...voice });
});

ui.wakewordToggle?.addEventListener("change", () => setWakeword(ui.wakewordToggle.checked));
ui.wakewordPill?.addEventListener("click", () => {
  if (state.admin) setWakeword(true);
  else openSettingsModal();
});

ui.profileVoicePlay.addEventListener("click", () => {
  unlockAudio();
  send({ type: "preview_voice", voice: ui.profileVoice.value });
});

function openSettingsModal() {
  renderAgentChoices();
  if (state.memory.enabled) send({ type: "list_memories" });
  ui.settings.showModal();
  ui.modelMsg.textContent = "";
  if (!state.admin) return;
  send({ type: "get_settings" });
  send({ type: "list_models" });
}

function openAdminDialog() {
  if (!state.superadmin || !ui.adminDialog) return;
  if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "");
  if (!ui.adminDialog.open) ui.adminDialog.showModal();
  send({ type: "pb_list_users" });
}

function renderPbUsers() {
  if (!ui.pbUsersList) return;
  const users = state.pbUsers || [];
  if (ui.pbUsersCount) ui.pbUsersCount.textContent = String(users.length);
  ui.pbUsersList.replaceChildren();
  if (!users.length) {
    const empty = document.createElement("p");
    empty.className = "meta";
    empty.textContent = "Aucun compte utilisateur dans la collection users.";
    ui.pbUsersList.append(empty);
    return;
  }

  for (const u of users) {
    const row = document.createElement("div");
    row.className = "pb-user-item";

    const avatar = document.createElement("div");
    avatar.className = "pb-user-avatar";
    avatar.textContent = ((u.name || u.email || "U").trim()[0] || "U").toUpperCase();

    const main = document.createElement("div");
    main.className = "pb-user-main";

    const nameLine = document.createElement("div");
    nameLine.className = "pb-user-name";
    nameLine.textContent = u.name || u.email || u.id;
    if (u.superadmin) {
      const badge = document.createElement("span");
      badge.className = "role-badge";
      badge.dataset.role = "superadmin";
      badge.textContent = "Superadmin PB";
      nameLine.append(badge);
    }

    const emailLine = document.createElement("div");
    emailLine.className = "pb-user-email";
    emailLine.textContent = u.email || `ID : ${u.id}`;

    main.append(nameLine, emailLine);

    const actions = document.createElement("div");
    actions.className = "pb-user-actions";

    const roleSelect = document.createElement("select");
    roleSelect.setAttribute("aria-label", `Rôle de ${u.name || u.email}`);
    for (const [val, label] of [["admin", "admin"], ["member", "member"], ["guest", "guest"]]) {
      roleSelect.append(new Option(label, val));
    }
    roleSelect.value = ["admin", "member", "guest"].includes(u.role) ? u.role : "member";
    roleSelect.addEventListener("change", () => {
      if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "Mise à jour du rôle…");
      send({ type: "pb_update_user", id: u.id, role: roleSelect.value });
    });

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "pb-user-del";
    delBtn.title = `Supprimer ${u.email || u.name}`;
    delBtn.setAttribute("aria-label", `Supprimer ${u.email || u.name}`);
    delBtn.textContent = "×";
    delBtn.addEventListener("click", () => {
      if (!confirm(`Supprimer le compte « ${u.email || u.name} » de PocketBase ?`)) return;
      if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "Suppression…");
      send({ type: "pb_delete_user", id: u.id });
    });

    actions.append(roleSelect, delBtn);
    row.append(avatar, main, actions);
    ui.pbUsersList.append(row);
  }
}

$("settings-btn").addEventListener("click", openSettingsModal);
ui.connPill?.addEventListener("click", openSettingsModal);
ui.adminBtn?.addEventListener("click", openAdminDialog);
ui.connAdminBtn?.addEventListener("click", () => {
  if (ui.settings.open) ui.settings.close();
  openAdminDialog();
});
ui.adminCloseBtn?.addEventListener("click", () => ui.adminDialog?.close());
ui.adminFooterClose?.addEventListener("click", () => ui.adminDialog?.close());
ui.pbUsersRefresh?.addEventListener("click", () => {
  if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "Actualisation…");
  send({ type: "pb_list_users" });
});
ui.pbCreateForm?.addEventListener("submit", (e) => {
  e.preventDefault();
  const email = ui.pbNewEmail?.value.trim() || "";
  const password = ui.pbNewPassword?.value || "";
  const name = ui.pbNewName?.value.trim() || "";
  const role = ui.pbNewRole?.value || "member";
  if (!email || password.length < 8) {
    if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "E-mail requis et mot de passe d'au moins 8 caractères.", "error");
    return;
  }
  if (ui.pbAdminMsg) setMessage(ui.pbAdminMsg, "Création du compte…");
  send({ type: "pb_create_user", email, password, name, role });
});
ui.adminOpenAdvanced?.addEventListener("click", () => {
  ui.adminDialog?.close();
  setMessage(ui.advancedMsg, "");
  $("advanced-restart").hidden = true;
  delete ui.advancedForm.dataset.dirty;
  renderAdvanced();
  ui.advanced.showModal();
  $("advanced-back")?.focus();
  send({ type: "get_settings" });
});
ui.adminOpenRestart?.addEventListener("click", () => {
  ui.adminDialog?.close();
  ui.restartConfirm.showModal();
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
ui.settingsLoginBtn?.addEventListener("click", () => {
  ui.settings.close();
  openSetup();
});
ui.loginBtn?.addEventListener("click", () => openSetup());
ui.status?.addEventListener("click", () => {
  if (state.ready) openSettingsModal();
  else openSetup();
});
ui.authBannerBtn?.addEventListener("click", () => openSetup());

$("logout-btn").addEventListener("click", () => {
  store.set("token", null);
  store.set("userToken", null);
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
  renderBadge();
  renderAttachments();
  ui.modelCurrent.textContent = `Actif : ${llm.model} (${llm.provider})${llm.decision ? " — modèle de décision" : ""}`;
}

// ---- Agents externes (Hermes, Claude, Antigravity...) : la pastille du modèle devient celle de l'agent ----
const SWAP_OUT_MS = 200;
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function badgeView() {
  if (state.agent) {
    return {
      label: state.agent.label,
      agent: true,
      title: `Conversation reliée à ${state.agent.label} — cliquer pour revenir à l'assistant ou changer d'agent`,
    };
  }
  const llm = state.llm;
  if (!llm) return null;
  return {
    label: llm.decision ? `${llm.model} · décision` : llm.model,
    agent: false,
    decision: Boolean(llm.decision),
    title: `${llm.provider} : ${llm.model}${llm.decision ? " (modèle de décision)" : ""}`
      + (state.agents.length ? " — cliquer pour parler à un agent" : ""),
  };
}

function applyBadge(view) {
  const badge = ui.modelBadge;
  badge.classList.toggle("agent", view.agent);
  badge.classList.toggle("decision", Boolean(view.decision));
  badge.classList.toggle("clickable", view.agent || state.agents.length > 0);
  badge.title = view.title;
  badge.setAttribute("aria-label", view.agent ? `Agent : ${view.label}` : `Modèle : ${view.label}`);
  ui.modelBadgeLabel.textContent = view.label;
}

// Bascule animée : le libellé s'efface (flou, glissement), la pastille change de largeur et de couleur,
// un reflet la traverse puis le nouveau nom apparaît.
function renderBadge(animate = false) {
  const view = badgeView();
  const badge = ui.modelBadge;
  if (!view) return;
  badge.hidden = false;
  if (state.agent?.color) document.documentElement.style.setProperty("--agent-color", state.agent.color);
  if (!animate || reducedMotion()) {
    applyBadge(view);
    return;
  }
  clearTimeout(badge._swapTimer);
  const from = badge.getBoundingClientRect().width;
  badge.style.width = `${from}px`;
  badge.classList.remove("sheen");
  badge.classList.add("swapping");
  badge._swapTimer = setTimeout(() => {
    applyBadge(view);
    badge.style.width = "auto";
    const to = badge.getBoundingClientRect().width;
    badge.style.width = `${from}px`;
    void badge.offsetWidth;  // force le calcul : la transition part de l'ancienne largeur
    badge.style.width = `${to}px`;
    badge.classList.remove("swapping");
    badge.classList.add("sheen");
    badge._swapTimer = setTimeout(() => {
      badge.style.width = "";
      badge.classList.remove("sheen");
    }, 900);
  }, SWAP_OUT_MS);
}

function markAgentBubble(el, agent) {
  el.classList.add("agent");
  el.dataset.agent = agent.label;
  el.style.setProperty("--bubble-agent-color", agent.color);
}

function addAgentSwitchNote(agent) {
  const el = document.createElement("div");
  el.className = `agent-switch${agent ? " to-agent" : ""}`;
  if (agent) el.style.setProperty("--bubble-agent-color", agent.color);
  const dot = document.createElement("span");
  dot.className = "agent-switch-dot";
  dot.setAttribute("aria-hidden", "true");
  const label = document.createElement("span");
  label.textContent = agent ? `Conversation reliée à ${agent.label}` : "Retour à l'assistant";
  el.append(dot, label);
  ui.empty.hidden = true;
  ui.log.append(el);
  scrollDown(true);
}

function setAgent(agent, { quiet = false } = {}) {
  const before = state.agent?.name || null;
  const after = agent?.name || null;
  state.agent = agent;
  document.body.classList.toggle("with-agent", Boolean(agent));
  renderAttachments();
  renderAgentChoices();
  if (before === after && !quiet) return;
  renderBadge(!quiet);
  if (!quiet) {
    addAgentSwitchNote(agent);
    announce(agent ? `Conversation reliée à ${agent.label}` : "Retour à l'assistant");
  }
}

function closeAgentMenu() {
  if (ui.agentMenu.hidden) return;
  ui.agentMenu.hidden = true;
  ui.modelBadge.setAttribute("aria-expanded", "false");
}

// Interlocuteurs proposés : l'assistant puis les agents externes permis à ce compte
function agentEntries() {
  return [
    { name: null, label: "Assistant", hint: state.llm?.model || "", color: "" },
    ...state.agents.map((a) => ({ name: a.name, label: a.label, hint: a.description || "", color: a.color })),
  ];
}

function chooseAgent(name) {
  if ((state.agent?.name || null) !== name) send({ type: "set_agent", agent: name });
}

// Carte « Interlocuteur » des réglages : une pastille par interlocuteur, celle en cours cochée
function renderAgentChoices() {
  if (!ui.agentCard) return;
  ui.agentCard.hidden = !state.agents.length;
  if (!state.agents.length) return;
  const currentName = state.agent?.name || null;
  ui.agentCardState.textContent = state.agent
    ? `Conversation reliée à ${state.agent.label}.`
    : "Vous parlez à l'assistant.";
  ui.agentChoices.replaceChildren();
  for (const entry of agentEntries()) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "agent-choice";
    chip.setAttribute("role", "radio");
    const current = currentName === entry.name;
    chip.setAttribute("aria-checked", String(current));
    if (entry.hint) chip.title = entry.hint;
    if (entry.color) chip.style.setProperty("--bubble-agent-color", entry.color);
    chip.disabled = !state.ready;
    const dot = document.createElement("span");
    dot.className = `agent-menu-dot${entry.name ? "" : " assistant"}`;
    dot.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = entry.label;
    chip.append(dot, label);
    chip.addEventListener("click", () => chooseAgent(entry.name));
    ui.agentChoices.append(chip);
  }
}

function openAgentMenu() {
  if (!state.agents.length) return;
  const menu = ui.agentMenu;
  menu.replaceChildren();
  for (const entry of agentEntries()) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "agent-menu-item";
    item.setAttribute("role", "menuitemradio");
    const current = (state.agent?.name || null) === entry.name;
    item.setAttribute("aria-checked", String(current));
    if (entry.color) item.style.setProperty("--bubble-agent-color", entry.color);
    const dot = document.createElement("span");
    dot.className = `agent-menu-dot${entry.name ? "" : " assistant"}`;
    dot.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.className = "agent-menu-text";
    const title = document.createElement("strong");
    title.textContent = entry.label;
    text.append(title);
    if (entry.hint) {
      const hint = document.createElement("small");
      hint.textContent = entry.hint;
      text.append(hint);
    }
    item.append(dot, text);
    item.addEventListener("click", () => {
      closeAgentMenu();
      chooseAgent(entry.name);
    });
    menu.append(item);
  }
  const rect = ui.modelBadge.getBoundingClientRect();
  menu.hidden = false;
  const width = menu.offsetWidth;
  menu.style.top = `${rect.bottom + 8}px`;
  menu.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`;
  ui.modelBadge.setAttribute("aria-expanded", "true");
  (menu.querySelector('[aria-checked="true"]') || menu.firstElementChild)?.focus();
}

ui.modelBadge.addEventListener("click", (e) => {
  e.stopPropagation();
  if (ui.agentMenu.hidden) openAgentMenu();
  else closeAgentMenu();
});
document.addEventListener("click", (e) => {
  if (!ui.agentMenu.contains(e.target)) closeAgentMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !ui.agentMenu.hidden) {
    closeAgentMenu();
    ui.modelBadge.focus();
  }
});
window.addEventListener("resize", closeAgentMenu);

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
  delete ui.advancedForm.dataset.dirty;

  // Fermer la fenêtre de paramètres et revenir sur la conversation
  if (ui.advanced.open) ui.advanced.close();
  if (ui.settings.open) ui.settings.close();
  $("settings-btn")?.focus();

  if (!event.changed.length) {
    showToast("Paramètres : aucun changement.", "info", 3000);
    return;
  }
  const label = (name) => fieldByName(name)?.label || name;
  const parts = ["Paramètres enregistrés."];
  if (event.restart.length) parts.push(`Au prochain démarrage : ${event.restart.map(label).join(", ")}.`);
  if (event.overridden.length) parts.push(`Attention, une variable d'environnement reste prioritaire : ${event.overridden.join(", ")}.`);
  showToast(parts.join(" "), "ok", 5000);
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
    const list = String(formValue("LLM_DECISION_MODELS") || "").toLowerCase().split(",").map((m) => m.trim());
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
        Object.entries(rule).every(([name, allowed]) => {
          const val = formValue(name);
          if (allowed.includes(val)) return true;
          if (typeof val === "boolean" && (allowed.includes(String(val)) || allowed.includes(val ? 1 : 0))) return true;
          if (val !== null && val !== undefined && allowed.map(String).includes(String(val))) return true;
          return false;
        }));
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
    // Listes de choix, nombres et tableaux de messages : contrôle créé plus haut, ajouté ici
    if (!wrap.contains(input)) {
      if (input.tagName !== "DIV") input.id = id;
      wrap.append(label, input);
    }
  }
  input.dataset.name = field.name;
  const onFieldChange = () => {
    let changed = true;
    try { changed = readField(field, input) !== undefined; } catch { /* JSON en cours de saisie */ }
    wrap.classList.toggle("changed", changed);
    ui.advancedForm.dataset.dirty = "1";
    applyVisibility();
  };
  input.addEventListener("input", onFieldChange);
  input.addEventListener("change", onFieldChange);
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
  let refreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!refreshing) {
      refreshing = true;
      window.location.reload();
    }
  });

  navigator.serviceWorker.register("sw.js").then((reg) => {
    reg.update();
    if (reg.waiting) {
      reg.waiting.postMessage({ type: "SKIP_WAITING" });
    }
    reg.addEventListener("updatefound", () => {
      const newWorker = reg.installing;
      if (newWorker) {
        newWorker.addEventListener("statechange", () => {
          if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
            newWorker.postMessage({ type: "SKIP_WAITING" });
          }
        });
      }
    });
  }).catch(() => { /* PWA non installable, l'appli fonctionne quand même */ });
}

$("force-reload-btn")?.addEventListener("click", () => {
  forceReloadApp();
});

async function forceReloadApp() {
  try {
    if ("caches" in window) {
      const keys = await caches.keys();
      for (const k of keys) await caches.delete(k);
    }
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      for (const r of regs) await r.unregister();
    }
  } catch { /* ignore */ }
  window.location.href = window.location.origin + window.location.pathname + "?nocache=" + Date.now();
}

// ---- Comparaison de version avec le dépôt GitHub & pastille de mise à jour ----
function applyVersionInfo(info) {
  if (!info || typeof info !== "object") return;
  state.versionInfo = { ...(state.versionInfo || {}), ...info };
  const v = state.versionInfo;

  const repo = v.repo || "GitHub";
  const branch = v.branch || "main";
  const localShort = v.local_short || (v.local_sha ? v.local_sha.slice(0, 7) : "local");
  const remoteShort = v.remote_short || (v.remote_sha ? v.remote_sha.slice(0, 7) : "");
  const hasDiff = Boolean(v.update_available || v.difference);

  // Carte de connexion dans Réglages
  if (ui.connRepoInfo) {
    ui.connRepoInfo.textContent = repo;
    ui.connRepoInfo.title = v.repo_url || repo;
  }
  if (ui.connVersionInfo) {
    if (hasDiff && remoteShort) {
      ui.connVersionInfo.textContent = `${localShort} → ${remoteShort} (MAJ dispo)`;
      ui.connVersionInfo.style.color = "var(--warn)";
    } else if (remoteShort) {
      ui.connVersionInfo.textContent = `${localShort} (à jour)`;
      ui.connVersionInfo.style.color = "var(--ok)";
    } else {
      ui.connVersionInfo.textContent = `${localShort} (${branch})`;
      ui.connVersionInfo.style.color = "";
    }
  }
  if (ui.connUpdateBtn) {
    ui.connUpdateBtn.hidden = !hasDiff;
  }
  if (ui.versionTagLabel) {
    ui.versionTagLabel.textContent = `SmartHome v18 · ${repo}@${localShort}`;
  }

  // Pastille d'invitation à mettre à jour dans la barre supérieure
  if (ui.updatePill) {
    ui.updatePill.hidden = !hasDiff;
    if (hasDiff) {
      const label = remoteShort ? `MAJ dispo · ${remoteShort}` : "MAJ disponible";
      if (ui.updatePillText) ui.updatePillText.textContent = label;
      ui.updatePill.title = `Nouvelle version détectée sur GitHub (${repo} : ${localShort} → ${remoteShort || "nouveau"}). Cliquer pour mettre à jour.`;
    }
  }

  // Fenêtre de détail de version / mise à jour
  if (ui.updateRepoName) ui.updateRepoName.textContent = repo;
  if (ui.updateBranchName) ui.updateBranchName.textContent = `Branche : ${branch}`;
  if (ui.updateRepoLink && v.repo_url) ui.updateRepoLink.href = v.repo_url;
  if (ui.updateLocalSha) ui.updateLocalSha.textContent = localShort || "—";
  if (ui.updateLocalMsg) {
    ui.updateLocalMsg.textContent = v.local_message || (v.local_date ? `Date : ${v.local_date}` : "Version locale actuelle");
  }
  if (ui.updateRemoteSha) {
    ui.updateRemoteSha.textContent = remoteShort || (v.checked ? "—" : "Vérification…");
  }
  if (ui.updateRemoteMsg) {
    if (v.remote_message) {
      ui.updateRemoteMsg.textContent = v.remote_message;
    } else if (v.error) {
      ui.updateRemoteMsg.textContent = ` Vérification distante : ${v.error}`;
    } else if (v.checked) {
      ui.updateRemoteMsg.textContent = hasDiff ? "Nouvelle version disponible sur GitHub" : "Identique à la version locale";
    }
  }
  if (ui.updateDialogBadge) {
    if (hasDiff) {
      ui.updateDialogBadge.textContent = "Mise à jour disponible";
      ui.updateDialogBadge.dataset.role = "superadmin";
    } else if (v.checked && !v.error) {
      ui.updateDialogBadge.textContent = "À jour";
      ui.updateDialogBadge.dataset.role = "admin";
    } else {
      ui.updateDialogBadge.textContent = "GitHub";
      ui.updateDialogBadge.dataset.role = "member";
    }
  }
  if (ui.updateStatusMsg && v.checked && !ui.updateApplyBtn?.disabled) {
    if (v.error) {
      setMessage(ui.updateStatusMsg, `Impossible de joindre GitHub : ${v.error}`, "error");
    } else if (hasDiff) {
      setMessage(
        ui.updateStatusMsg,
        `Une différence a été détectée avec le dépôt GitHub ${repo} (${localShort} ≠ ${remoteShort}).`,
        "ok"
      );
    } else {
      setMessage(ui.updateStatusMsg, `Votre application est à jour avec ${repo} (${localShort}).`, "ok");
    }
  }
}

function openUpdateDialog() {
  if (!ui.updateDialog) return;
  if (state.versionInfo) applyVersionInfo(state.versionInfo);
  if (!ui.updateDialog.open) ui.updateDialog.showModal();
  if (state.ready) {
    if (ui.updateStatusMsg) setMessage(ui.updateStatusMsg, "Comparaison avec le dépôt GitHub en cours…");
    send({ type: "check_update", force: true });
  }
}

function onUpdateApplied(event) {
  if (ui.updateApplyBtn) ui.updateApplyBtn.disabled = false;
  if (event.version) applyVersionInfo(event.version);
  if (event.ok) {
    if (ui.updateStatusMsg) {
      setMessage(ui.updateStatusMsg, `${event.message || "Mise à jour téléchargée."} Rechargement de l'application…`, "ok");
    }
    showToast("Mise à jour installée — rechargement…", "ok");
    if (state.admin) {
      send({ type: "restart" });
    }
    setTimeout(() => {
      forceReloadApp();
    }, 1200);
  } else {
    if (ui.updateStatusMsg) {
      setMessage(ui.updateStatusMsg, event.message || "Échec de la mise à jour automatique.", "error");
    }
    showToast(event.message || "Échec de la mise à jour", "error");
  }
}

ui.updatePill?.addEventListener("click", openUpdateDialog);
ui.connUpdateBtn?.addEventListener("click", () => {
  if (ui.settings?.open) ui.settings.close();
  openUpdateDialog();
});
ui.updateCloseBtn?.addEventListener("click", () => ui.updateDialog?.close());
ui.updateFooterClose?.addEventListener("click", () => ui.updateDialog?.close());
ui.updateCheckBtn?.addEventListener("click", () => {
  if (ui.updateStatusMsg) setMessage(ui.updateStatusMsg, "Vérification auprès de GitHub…");
  send({ type: "check_update", force: true });
});
ui.updateApplyBtn?.addEventListener("click", () => {
  if (!state.admin) {
    forceReloadApp();
    return;
  }
  if (ui.updateApplyBtn) ui.updateApplyBtn.disabled = true;
  if (ui.updateStatusMsg) setMessage(ui.updateStatusMsg, "Téléchargement de la mise à jour depuis GitHub (git pull)…");
  send({ type: "apply_update" });
});

async function handleUrlNocache() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("nocache") || params.has("clean")) {
    if ("caches" in window) {
      const keys = await caches.keys();
      for (const k of keys) await caches.delete(k);
    }
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      for (const r of regs) await r.unregister();
    }
    params.delete("nocache");
    params.delete("clean");
    const query = params.toString();
    window.location.replace(window.location.pathname + (query ? `?${query}` : "") + window.location.hash);
  }
}

async function checkServerHealth() {
  const hostLabel = location.host || "127.0.0.1:8765";
  if (ui.authBannerHost) ui.authBannerHost.textContent = `Passerelle : ${hostLabel}`;
  try {
    const res = await fetch("/health");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (data.pocketbase_url) state.pocketbaseUrl = data.pocketbase_url;
    if (data.version) applyVersionInfo(data.version);
    if (typeof data.accounts === "boolean") {
      state.accounts = data.accounts;
      updateSetupTabs();
    }
    const modeLabel = data.accounts ? "Annuaire : PocketBase actif" : "Authentification : Jeton / Local";
    if (ui.authBannerMode) ui.authBannerMode.textContent = modeLabel;
    if (ui.setupServerDot) ui.setupServerDot.dataset.state = "online";
    if (ui.setupServerInfo) {
      ui.setupServerInfo.textContent = `Passerelle joignable (${hostLabel}) · ${data.accounts ? "PocketBase" : "Jeton"}`;
    }
  } catch {
    if (ui.authBannerMode) ui.authBannerMode.textContent = "Passerelle hors ligne";
    if (ui.setupServerDot) ui.setupServerDot.dataset.state = "offline";
    if (ui.setupServerInfo) {
      ui.setupServerInfo.textContent = `Passerelle injoignable (${hostLabel})`;
    }
  }
}

handleUrlNocache();
consumePairingToken();
initConversations();
checkServerHealth();
connect();


// ---- Images : jointes aux messages (trombone, coller, glisser-déposer) et montrées par l'assistant ----
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"];
// En dessous de cette taille, une image déjà assez petite part telle quelle (GIF animé conservé)
const IMAGE_KEEP_BYTES = 1_500_000;

function readAsDataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function loadImageElement(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image illisible"));
    img.src = url;
  });
}

// Réduit l'image (plus grand côté `max_side`) en JPEG avant l'envoi : quelques centaines de Ko au lieu de plusieurs Mo
async function prepareImage(file) {
  const cfg = state.imageConfig;
  const original = await readAsDataURL(file);
  const img = await loadImageElement(original);
  const side = Math.max(img.naturalWidth, img.naturalHeight);
  const maxSide = cfg.max_side || 0;
  const small = file.size <= IMAGE_KEEP_BYTES && (!maxSide || side <= maxSide);
  let url = original;
  let mime = file.type;
  if (!small && file.type !== "image/gif") {
    const scale = maxSide && side > maxSide ? maxSide / side : 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";  // transparence : fond blanc (JPEG)
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    url = canvas.toDataURL("image/jpeg", 0.88);
    mime = "image/jpeg";
  }
  const data = url.slice(url.indexOf(",") + 1);
  if (data.length * 0.75 > cfg.max_bytes) throw new Error(`trop lourde (maximum ${Math.round(cfg.max_bytes / 1e6)} Mo)`);
  const base = (file.name || "image").replace(/\.[^.]+$/, "") || "image";
  const name = mime === file.type && file.name ? file.name : `${base}.jpg`;
  return { id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`, name, mime, data, url };
}

async function addAttachments(files) {
  if (!state.ready) return;
  const cfg = state.imageConfig;
  if (cfg.enabled === false) {
    showToast("Les images sont désactivées sur ce serveur.");
    return;
  }
  const images = [...files].filter((f) => IMAGE_TYPES.includes(f.type));
  if (files.length && !images.length) {
    showToast("Seules les images (PNG, JPEG, GIF, WebP, BMP) peuvent être jointes.");
    return;
  }
  for (const file of images) {
    if (state.attachments.length >= cfg.max_per_message) {
      showToast(`${cfg.max_per_message} images au maximum par message.`);
      break;
    }
    try {
      state.attachments.push(await prepareImage(file));
    } catch (e) {
      showToast(`« ${file.name || "image"} » non jointe : ${e.message}`);
    }
  }
  // Modèle sans vision : l'alerte est affichée sous les miniatures (renderAttachments)
  renderAttachments();
  updateMainButton();
  if (state.attachments.length && !visionAvailable()) announce(visionWarning());
  ui.text.focus();
}

// L'image sera-t-elle comprise ? (agent externe : il reçoit le chemin du fichier)
function visionAvailable() {
  return Boolean(state.agent) || Boolean(state.llm?.vision);
}

function visionWarning() {
  const model = state.llm?.model || "actif";
  return `Le modèle ${model} ne sait pas lire les images : seul le texte de votre message lui sera transmis.`;
}

function renderAttachments() {
  if (!ui.attachments) return;
  const items = state.attachments;
  ui.attachments.hidden = !items.length;
  ui.attachList.replaceChildren(...items.map((item) => {
    const el = document.createElement("div");
    el.className = "attachment";
    const img = document.createElement("img");
    img.src = item.url;
    img.alt = item.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-remove";
    remove.setAttribute("aria-label", `Retirer ${item.name}`);
    remove.title = "Retirer";
    remove.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`;
    remove.addEventListener("click", () => {
      state.attachments = state.attachments.filter((a) => a.id !== item.id);
      renderAttachments();
      updateMainButton();
    });
    el.append(img, remove);
    return el;
  }));
  const warn = items.length && !visionAvailable();
  ui.attachNote.hidden = !items.length;
  ui.attachNote.classList.toggle("warn", Boolean(warn));
  ui.attachNote.textContent = warn
    ? `⚠️ ${visionWarning()}`
    : state.agent
      ? `${state.agent.label} recevra le chemin de ${items.length > 1 ? "ces images" : "l'image"} sur l'ordinateur.`
      : `${items.length} image${items.length > 1 ? "s" : ""} pour ${state.llm?.model || "le modèle"}.`;
}

function attachImagesToBubble(bubble, images) {
  const wrap = document.createElement("div");
  wrap.className = "msg-images";
  for (const item of images) {
    const img = document.createElement("img");
    img.src = item.url;
    img.alt = item.name;
    img.loading = "lazy";
    img.addEventListener("click", () => openImageViewer(item.url, item.name));
    wrap.append(img);
  }
  bubble.append(wrap);
  bubble.classList.add("with-images");
}

function addImageBubble(event) {
  const url = `data:${event.mime};base64,${event.data}`;
  const el = addBubble("bot image-msg", "");
  const img = document.createElement("img");
  img.src = url;
  img.alt = event.name || "Image";
  img.addEventListener("click", () => openImageViewer(url, event.path || event.name));
  const caption = document.createElement("span");
  caption.className = "image-caption";
  caption.textContent = event.path || event.name || "";
  el.append(img, caption);
  img.addEventListener("load", () => scrollDown(true), { once: true });
}

function addNotice(message) {
  ui.empty.hidden = true;
  const el = document.createElement("div");
  el.className = "notice";
  el.setAttribute("role", "status");
  el.textContent = message;
  if (state.eventTurn) el.dataset.turn = state.eventTurn;
  ui.log.append(el);
  scrollDown(true);
}

function openImageViewer(url, caption) {
  if (!ui.imageViewer) return;
  ui.imageViewerImg.src = url;
  ui.imageViewerImg.alt = caption || "Image";
  ui.imageViewerCaption.textContent = caption || "";
  ui.imageViewer.showModal();
}

ui.imageViewer?.addEventListener("click", () => ui.imageViewer.close());
ui.imageViewer?.addEventListener("close", () => { ui.imageViewerImg.removeAttribute("src"); });

ui.attachBtn?.addEventListener("click", () => ui.attachInput.click());
ui.attachInput?.addEventListener("change", () => {
  addAttachments(ui.attachInput.files || []);
  ui.attachInput.value = "";
});

// Coller une image (capture d'écran...) dans le champ de saisie ou n'importe où dans la page
document.addEventListener("paste", (e) => {
  const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  e.preventDefault();
  addAttachments(files);
});

// Glisser-déposer : une image déposée sur la page est jointe au prochain message
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
document.addEventListener("dragenter", (e) => {
  if (!hasFiles(e) || !state.ready) return;
  dragDepth += 1;
  document.body.classList.add("dragging-file");
});
document.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) document.body.classList.remove("dragging-file");
});
document.addEventListener("dragover", (e) => {
  if (hasFiles(e)) e.preventDefault();
});
document.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging-file");
  addAttachments(e.dataTransfer.files || []);
});
