// Comparaison de version avec le dépôt GitHub & pastille / fenêtre de mise à jour.

export function initVersion({ ui, state, send, setMessage, showToast, forceReloadApp }) {
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
      ui.versionTagLabel.textContent = `SmartHome v19 · ${repo}@${localShort}`;
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

  return { applyVersionInfo, openUpdateDialog, onUpdateApplied };
}
