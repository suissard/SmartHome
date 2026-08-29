#!/usr/bin/env bash
# Script de contrôle multimédia pour SmartHome
# Compatible playerctl et D-Bus MPRIS2 natif (Spotify, Chrome, Firefox, VLC, Elisa, etc.)
# Usage :
#   media.sh play-pause
#   media.sh next
#   media.sh previous
#   media.sh stop

CMD="${1:-play-pause}"

# Normalisation du nom de la méthode MPRIS
case "$CMD" in
    play-pause|play_pause|toggle)
        PLAYERCTL_CMD="play-pause"
        MPRIS_METHOD="PlayPause"
        ;;
    next)
        PLAYERCTL_CMD="next"
        MPRIS_METHOD="Next"
        ;;
    previous|prev)
        PLAYERCTL_CMD="previous"
        MPRIS_METHOD="Previous"
        ;;
    stop)
        PLAYERCTL_CMD="stop"
        MPRIS_METHOD="Stop"
        ;;
    play)
        PLAYERCTL_CMD="play"
        MPRIS_METHOD="Play"
        ;;
    pause)
        PLAYERCTL_CMD="pause"
        MPRIS_METHOD="Pause"
        ;;
    *)
        echo "Commande multimédia inconnue : $CMD" >&2
        exit 1
        ;;
esac

# 1. Utilisation de playerctl si présent
if command -v playerctl >/dev/null 2>&1; then
    if playerctl "$PLAYERCTL_CMD" 2>/dev/null; then
        exit 0
    fi
fi

# 2. Fallback D-Bus MPRIS2 direct
called=0

# Recherche des lecteurs actifs via busctl
if command -v busctl >/dev/null 2>&1; then
    players=$(busctl --user list 2>/dev/null | awk '/org\.mpris\.MediaPlayer2/{print $1}')
    for p in $players; do
        if busctl --user call "$p" /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player "$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

# Recherche des lecteurs actifs via dbus-send
if [ $called -eq 0 ] && command -v dbus-send >/dev/null 2>&1; then
    players=$(dbus-send --session --dest=org.freedesktop.DBus --type=method_call --print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>/dev/null | grep -o 'org\.mpris\.MediaPlayer2[^"]*')
    for p in $players; do
        if dbus-send --type=method_call --dest="$p" /org/mpris/MediaPlayer2 "org.mpris.MediaPlayer2.Player.$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

# Recherche des lecteurs actifs via qdbus6 ou qdbus
if [ $called -eq 0 ]; then
    QDBUS_BIN=""
    if command -v qdbus6 >/dev/null 2>&1; then
        QDBUS_BIN="qdbus6"
    elif command -v qdbus >/dev/null 2>&1; then
        QDBUS_BIN="qdbus"
    fi

    if [ -n "$QDBUS_BIN" ]; then
        players=$($QDBUS_BIN 2>/dev/null | grep 'org\.mpris\.MediaPlayer2')
        for p in $players; do
            if $QDBUS_BIN "$p" /org/mpris/MediaPlayer2 "org.mpris.MediaPlayer2.Player.$MPRIS_METHOD" >/dev/null 2>&1; then
                called=1
            fi
        done
    fi
fi

if [ $called -eq 1 ]; then
    exit 0
fi

# Aucun lecteur ou outil n'a répondu
echo "Avertissement : Aucun lecteur multimédia actif trouvé (MPRIS / playerctl)." >&2
exit 0

