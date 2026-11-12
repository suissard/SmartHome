// Administration des comptes PocketBase (superadmins uniquement).

export const ROLE_LABELS = {
  superadmin: "Superadmin",
  admin: "Admin",
  member: "Membre",
  guest: "Invité",
  local: "Local",
};

export function resolvePocketBaseAdminUrl(rawUrl) {
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

export function initPbAdmin({ ui, state, send, setMessage, onOpenAdvanced }) {
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

  ui.adminBtn?.addEventListener("click", openAdminDialog);
  ui.connAdminBtn?.addEventListener("click", () => {
    if (ui.settings.open) ui.settings.close();
    openAdminDialog();
  });
  ui.adminCloseBtn?.addEventListener("click", () => ui.adminDialog?.close());
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
    onOpenAdvanced?.();
  });
  ui.adminOpenRestart?.addEventListener("click", () => {
    ui.adminDialog?.close();
    ui.restartConfirm.showModal();
  });

  return { openAdminDialog, renderPbUsers };
}
