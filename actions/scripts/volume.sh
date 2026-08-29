#!/usr/bin/env bash
# Script de réglage du volume audio pour SmartHome
# Usage :
#   volume.sh 50       -> Règle le volume à 50%
#   volume.sh up       -> Augmente de 5%
#   volume.sh down     -> Diminue de 5%
#   volume.sh mute     -> Coupe le son
#   volume.sh unmute   -> Réactive le son
#   volume.sh toggle   -> Bascule muet/actif

TARGET="${1:-toggle}"

# Support PipeWire (wpctl) ou PulseAudio / PipeWire-Pulse (pactl)
if command -v pactl >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            pactl set-sink-mute @DEFAULT_SINK@ 1
            ;;
        unmute)
            pactl set-sink-mute @DEFAULT_SINK@ 0
            ;;
        toggle)
            pactl set-sink-mute @DEFAULT_SINK@ toggle
            ;;
        up|+*)
            # Démute automatiquement lors de l'augmentation du volume
            pactl set-sink-mute @DEFAULT_SINK@ 0
            pactl set-sink-volume @DEFAULT_SINK@ +5%
            ;;
        down|-*)
            pactl set-sink-volume @DEFAULT_SINK@ -5%
            ;;
        *)
            # Si un nombre est passé (ex: 50 ou 50%)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    pactl set-sink-mute @DEFAULT_SINK@ 0
                fi
                pactl set-sink-volume @DEFAULT_SINK@ "${val}%"
            fi
            ;;
    esac
elif command -v wpctl >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ 1
            ;;
        unmute)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
            ;;
        toggle)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
            ;;
        up|+*)
            # Démute automatiquement lors de l'augmentation du volume
            wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
            wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+
            ;;
        down|-*)
            wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
            ;;
        *)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
                fi
                frac=$(awk "BEGIN {print $val/100}")
                wpctl set-volume @DEFAULT_AUDIO_SINK@ "$frac"
            fi
            ;;
    esac
elif command -v amixer >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            amixer set Master mute
            ;;
        unmute)
            amixer set Master unmute
            ;;
        toggle)
            amixer set Master toggle
            ;;
        up|+*)
            # Démute automatiquement lors de l'augmentation du volume
            amixer set Master unmute
            amixer set Master 5%+
            ;;
        down|-*)
            amixer set Master 5%-
            ;;
        *)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    amixer set Master unmute
                fi
                amixer set Master "${val}%"
            fi
            ;;
    esac
else
    echo "Erreur : Aucun contrôleur audio trouvé (pactl, wpctl, amixer)." >&2
    exit 1
fi


