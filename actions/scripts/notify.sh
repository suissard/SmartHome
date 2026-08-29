#!/usr/bin/env bash
# Script pour afficher une notification de bureau pour SmartHome
# Usage :
#   notify.sh "Mon message"
#   notify.sh "Titre" "Mon message"

if [ $# -eq 0 ]; then
    echo "Usage : notify.sh [titre] <message>" >&2
    exit 1
fi

TITLE="SmartHome"
MSG=""

if [ $# -eq 1 ]; then
    MSG="$1"
elif [ $# -eq 2 ]; then
    TITLE="$1"
    MSG="$2"
else
    TITLE="$1"
    shift
    MSG="$*"
fi

# 1. notify-send (standard freedesktop)
if command -v notify-send >/dev/null 2>&1; then
    notify-send "$TITLE" "$MSG"
    exit 0
fi

# 2. kdialog (KDE)
if command -v kdialog >/dev/null 2>&1; then
    kdialog --title "$TITLE" --passivepopup "$MSG" 5 >/dev/null 2>&1
    exit 0
fi

# 3. zenity (GNOME / multi)
if command -v zenity >/dev/null 2>&1; then
    zenity --notification --text="[$TITLE] $MSG" >/dev/null 2>&1
    exit 0
fi

echo "[$TITLE] $MSG"
exit 0

