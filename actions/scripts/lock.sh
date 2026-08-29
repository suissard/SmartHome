#!/usr/bin/env bash
# Script de verrouillage de session pour SmartHome
# Compatible systemd/loginctl, D-Bus freedesktop ScreenSaver, KDE, GNOME, Hyprland, Sway

# 1. loginctl (standard systemd multi-environnements)
if command -v loginctl >/dev/null 2>&1; then
    loginctl lock-session && exit 0
fi

# 2. D-Bus freedesktop ScreenSaver
if command -v qdbus6 >/dev/null 2>&1; then
    qdbus6 org.freedesktop.ScreenSaver /ScreenSaver Lock 2>/dev/null && exit 0
elif command -v qdbus >/dev/null 2>&1; then
    qdbus org.freedesktop.ScreenSaver /ScreenSaver Lock 2>/dev/null && exit 0
elif command -v dbus-send >/dev/null 2>&1; then
    dbus-send --type=method_call --dest=org.freedesktop.ScreenSaver /ScreenSaver org.freedesktop.ScreenSaver.Lock 2>/dev/null && exit 0
fi

# 3. xdg-screensaver
if command -v xdg-screensaver >/dev/null 2>&1; then
    xdg-screensaver lock && exit 0
fi

# 4. GNOME screensaver
if command -v gnome-screensaver-command >/dev/null 2>&1; then
    gnome-screensaver-command -l && exit 0
fi

# 5. Hyprlock / Swaylock
if command -v hyprlock >/dev/null 2>&1; then
    nohup hyprlock >/dev/null 2>&1 &
    exit 0
elif command -v swaylock >/dev/null 2>&1; then
    nohup swaylock >/dev/null 2>&1 &
    exit 0
fi

echo "Erreur : Aucun gestionnaire de verrouillage détecté." >&2
exit 1

