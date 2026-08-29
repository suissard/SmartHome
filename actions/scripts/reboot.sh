#!/usr/bin/env bash
# Script de redémarrage du système pour SmartHome

if command -v systemctl >/dev/null 2>&1; then
    systemctl reboot
elif command -v reboot >/dev/null 2>&1; then
    reboot
else
    echo "Erreur : Commande de redémarrage introuvable." >&2
    exit 1
fi
