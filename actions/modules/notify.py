"""
Module d'action pour l'affichage de notifications sur le bureau.
Contient les métadonnées et le script bash embarqué.
"""

from typing import List, Tuple
import subprocess
from actions.base import BaseAction

_NOTIFY_SCRIPT = r"""
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
"""


class NotifyAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="NOTIFY",
            description="Afficher une notification sur le bureau.",
            script_code=_NOTIFY_SCRIPT,
            has_args=True,
            args_hint="<message>",
            example_prompt="Affiche un rappel pour sortir le chien.",
            example_response="[NOTIFY Sortir le chien] Notification affichée."
        )

    def build_args(self, args: str = "") -> List[str]:
        msg = (args or "").strip()
        return [msg] if msg else []

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        msg = (args or "").strip()
        if not msg:
            return 1, "", "Usage : notify <message>"
        try:
            print(f"🔔 [NOTIFY] [Windows] {msg}")
            import base64
            b64_msg = base64.b64encode(msg.encode("utf-8")).decode("ascii")
            ps = (
                "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null\n"
                "$n = New-Object System.Windows.Forms.NotifyIcon\n"
                "$n.Icon = [System.Drawing.SystemIcons]::Information\n"
                "$n.Visible = $true\n"
                f"$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{b64_msg}'))\n"
                "$n.ShowBalloonTip(5000, 'SmartHome', $text, [System.Windows.Forms.ToolTipIcon]::Info)\n"
                "Start-Sleep -Seconds 1\n"
                "$n.Dispose()\n"
            )
            encoded = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
            return 0, f"Notification envoyée : {msg}", ""
        except Exception as e:
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [NotifyAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/notify.py")
    code, out, err = ACTIONS[0].execute_sync("Test de notification directe")
    print(f"Code : {code} | Sortie : {out.strip()}")
