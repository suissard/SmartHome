// Gestion des images jointes aux messages et des images montrées par l'assistant.

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"];
// En dessous de cette taille, une image déjà assez petite part telle quelle (GIF animé conservé)
export const IMAGE_KEEP_BYTES = 1_500_000;

export function readAsDataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export function loadImageElement(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image illisible"));
    img.src = url;
  });
}

// Réduit l'image (plus grand côté `max_side`) en JPEG avant l'envoi : quelques centaines de Ko au lieu de plusieurs Mo
export async function prepareImage(file, cfg) {
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

export function initImages({ ui, state, showToast, announce, updateMainButton, addBubble, scrollDown }) {
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
        state.attachments.push(await prepareImage(file, cfg));
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

  function openImageViewer(url, caption) {
    if (!ui.imageViewer) return;
    ui.imageViewerImg.src = url;
    ui.imageViewerImg.alt = caption || "Image";
    ui.imageViewerCaption.textContent = caption || "";
    ui.imageViewer.showModal();
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

  return {
    addAttachments,
    visionAvailable,
    visionWarning,
    renderAttachments,
    attachImagesToBubble,
    addImageBubble,
    addNotice,
    openImageViewer,
  };
}
