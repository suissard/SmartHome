// Rendu des outils et pastilles d'actions dans le fil de conversation SmartHome.

export function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (s) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[s]));
}

export function formatActionSignature(name, args = {}) {
  const entries = Object.entries(args || {});
  if (!entries.length) return `${name}()`;
  const formatted = entries
    .map(([k, v]) => `${k}=${typeof v === "string" ? `"${v}"` : JSON.stringify(v)}`)
    .join(", ");
  return `${name}(${formatted})`;
}

export const TOOL_ICONS = {
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
  default: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>`,
};

TOOL_ICONS.list_memories = TOOL_ICONS.forget_memory = TOOL_ICONS.remember;

export function getToolIcon(name) {
  const key = (name || "").toLowerCase().trim();
  return TOOL_ICONS[key] || TOOL_ICONS[key.replace(/_action$/, "")] || TOOL_ICONS.default;
}

export function formatActionLabel(name, args = {}, executed = true) {
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

export function buildToolPastille(tool, turn = null, onNotify = null) {
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
    onNotify?.(`${signature}${tool.output ? ` : ${tool.output}` : ""}`, isOk ? "ok" : "error");
  });

  return el;
}
