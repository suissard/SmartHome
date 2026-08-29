#!/usr/bin/env bash
# Script d'arrêt du système pour SmartHome

# Tentative via systemctl (systemd standard), fallback sur shutdown
if command -v systemctl >/dev/null 2>&1; then
    systemctl poweroff
elif command -v shutdown >/dev/null 2>&1; then
    shutdown -h now
else
    echo "Erreur : Commande d'extinction introuvable." >&2
    exit 1
fi
