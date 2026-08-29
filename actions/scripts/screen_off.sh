#!/usr/bin/env bash
# Script pour éteindre / mettre en veille les écrans
# Compatible KDE Plasma (Wayland/X11), Hyprland, Sway, GNOME et X11

# 1. KDE Plasma (Wayland ou X11) via kscreen-doctor
if command -v kscreen-doctor >/dev/null 2>&1; then
    kscreen-doctor --dpms off && exit 0
fi

# 2. KDE via raccourci PowerDevil D-Bus
if command -v qdbus6 >/dev/null 2>&1; then
    qdbus6 org.kde.kglobalaccel /component/org_kde_powerdevil invokeShortcut "Turn Off Screen" 2>/dev/null && exit 0
elif command -v qdbus >/dev/null 2>&1; then
    qdbus org.kde.kglobalaccel /component/org_kde_powerdevil invokeShortcut "Turn Off Screen" 2>/dev/null && exit 0
fi

# 3. Hyprland
if command -v hyprctl >/dev/null 2>&1; then
    hyprctl dispatch dpms off && exit 0
fi

# 4. Sway
if command -v swaymsg >/dev/null 2>&1; then
    swaymsg "output * dpms off" && exit 0
fi

# 5. Generic Wayland wlroots (wlopm)
if command -v wlopm >/dev/null 2>&1; then
    wlopm --off '*' && exit 0
fi

# 6. X11 DPMS (uniquement si sous X11)
if [ "$XDG_SESSION_TYPE" != "wayland" ] && command -v xset >/dev/null 2>&1; then
    xset dpms force off && exit 0
fi

echo "Erreur : Aucune commande de gestion d'affichage compatible détectée." >&2
exit 1

