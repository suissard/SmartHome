import atexit
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Any, List, Optional

from config import (
    DUCKING_ENABLED,
    DUCKING_VOLUME_PERCENT,
    DUCKING_RESTORE_ON_EXIT,
)


class AudioDucker:
    """
    Gestionnaire d'atténuation audio (Ducking) sous Linux (PipeWire / PulseAudio).
    Baisse le volume des applications externes (navigateurs, musique, etc.)
    pendant l'écoute ou la parole de l'assistant, puis restaure leurs volumes d'origine.
    """

    def __init__(
        self,
        enabled: bool = DUCKING_ENABLED,
        volume_percent: int = DUCKING_VOLUME_PERCENT,
        restore_on_exit: bool = DUCKING_RESTORE_ON_EXIT,
    ):
        self.enabled = enabled
        self.volume_percent = max(0, min(100, volume_percent))
        self.restore_on_exit = restore_on_exit
        self.saved_volumes: Dict[int, Dict[str, Any]] = {}
        self.saved_app_volumes: Dict[str, Dict[str, Any]] = {}
        self.is_ducked: bool = False
        self._pactl_available = shutil.which("pactl") is not None

        if not self._pactl_available and self.enabled:
            print("⚠️ [DUCKING] 'pactl' non trouvé sur le système. Atténuation audio désactivée.")
            self.enabled = False

        if self.restore_on_exit and self.enabled:
            atexit.register(self._cleanup_on_exit)

    def _get_current_pid(self) -> int:
        return os.getpid()

    def _list_sink_inputs(self) -> List[Dict[str, Any]]:
        """Récupère la liste structurée des flux audio actifs via pactl JSON."""
        if not self._pactl_available:
            return []

        try:
            res = subprocess.run(
                ["pactl", "-f", "json", "list", "sink-inputs"],
                capture_output=True,
                text=True,
                check=False,
                timeout=1.5,
            )
            if res.returncode == 0 and res.stdout.strip():
                out = res.stdout.strip()
                idx_start = out.find("[")
                if idx_start != -1:
                    out = out[idx_start:]
                return json.loads(out)
        except Exception:
            pass
        return []

    def duck(self, target_percent: Optional[int] = None) -> bool:
        """
        Atténue tous les flux audio externes.
        Conserve et mémorise le niveau sonore d'origine de chaque application.
        """
        if not self.enabled:
            return False

        target = self.volume_percent if target_percent is None else max(0, min(100, target_percent))
        my_pid = str(self._get_current_pid())
        sink_inputs = self._list_sink_inputs()

        if not sink_inputs:
            self.is_ducked = True
            return True

        ducked_count = 0
        for item in sink_inputs:
            index = item.get("index")
            if index is None:
                continue

            props = item.get("properties", {})
            app_pid = str(props.get("application.process.id", ""))
            app_name = props.get("application.name", props.get("media.name", f"App #{index}"))

            # On ignore notre propre processus (Piper TTS, bips, etc.)
            if app_pid == my_pid:
                continue

            # Mémorisation du volume initial (par index et par nom d'app)
            if index not in self.saved_volumes:
                vol_dict = item.get("volume", {})
                values: List[int] = []
                if isinstance(vol_dict, dict):
                    for ch_info in vol_dict.values():
                        if isinstance(ch_info, dict) and "value" in ch_info:
                            values.append(ch_info["value"])
                
                if not values:
                    values = [65536]

                vol_data = {
                    "values": values,
                    "mute": item.get("mute", False),
                    "app_name": app_name,
                    "app_pid": app_pid,
                }
                self.saved_volumes[index] = vol_data
                if app_name:
                    self.saved_app_volumes[app_name] = vol_data

            # Application de l'atténuation
            try:
                if target <= 0:
                    subprocess.run(
                        ["pactl", "set-sink-input-mute", str(index), "1"],
                        capture_output=True,
                        check=False,
                        timeout=1.0,
                    )
                else:
                    subprocess.run(
                        ["pactl", "set-sink-input-volume", str(index), f"{target}%"],
                        capture_output=True,
                        check=False,
                        timeout=1.0,
                    )
                ducked_count += 1
            except Exception:
                pass

        self.is_ducked = True
        return ducked_count > 0

    def unduck(self) -> bool:
        """
        Rétablit les volumes d'origine pour tous les flux audio.
        Restaure par index, par nom d'application, et réinitialise tout flux resté bridé.
        """
        my_pid = str(self._get_current_pid())
        current_inputs = self._list_sink_inputs()

        # 1. Restauration des flux actuellement actifs
        restored_indices = set()
        for item in current_inputs:
            index = item.get("index")
            if index is None:
                continue

            props = item.get("properties", {})
            app_pid = str(props.get("application.process.id", ""))
            app_name = props.get("application.name", props.get("media.name", ""))

            if app_pid == my_pid:
                continue

            # Trouver les données de volume sauvegardées correspondantes
            saved = self.saved_volumes.get(index)
            if not saved and app_name and app_name in self.saved_app_volumes:
                saved = self.saved_app_volumes[app_name]

            if saved:
                values = saved.get("values", [])
                was_muted = "1" if saved.get("mute", False) else "0"
            else:
                # Si le flux n'était pas mémorisé mais qu'il est potentiellement bridé, restauration 100%
                values = [65536]
                was_muted = "0"

            try:
                if values:
                    val_args = [str(v) for v in values]
                    subprocess.run(
                        ["pactl", "set-sink-input-volume", str(index)] + val_args,
                        capture_output=True,
                        check=False,
                        timeout=1.0,
                    )
                else:
                    subprocess.run(
                        ["pactl", "set-sink-input-volume", str(index), "100%"],
                        capture_output=True,
                        check=False,
                        timeout=1.0,
                    )

                subprocess.run(
                    ["pactl", "set-sink-input-mute", str(index), was_muted],
                    capture_output=True,
                    check=False,
                    timeout=1.0,
                )
                restored_indices.add(index)
            except Exception:
                pass

        # 2. Tentative de restauration sur les anciens index sauvegardés
        for index, data in list(self.saved_volumes.items()):
            if index in restored_indices:
                continue
            try:
                values = data.get("values", [])
                if values:
                    subprocess.run(
                        ["pactl", "set-sink-input-volume", str(index)] + [str(v) for v in values],
                        capture_output=True,
                        check=False,
                        timeout=0.5,
                    )
                was_muted = "1" if data.get("mute", False) else "0"
                subprocess.run(
                    ["pactl", "set-sink-input-mute", str(index), was_muted],
                    capture_output=True,
                    check=False,
                    timeout=0.5,
                )
            except Exception:
                pass

        self.saved_volumes.clear()
        self.saved_app_volumes.clear()
        self.is_ducked = False
        return True

    @staticmethod
    def reset_all() -> bool:
        """
        Commande d'urgence / remise d'équerre :
        Remet tous les flux audio (sink-inputs) à 100%, retire les mutes,
        et s'assure que la sortie son principale est active et démutée.
        """
        if shutil.which("pactl") is None:
            print("⚠️ [RESET] 'pactl' non trouvé sur le système.")
            return False

        print("🔄 [RESET] Remise d'équerre de tous les flux audio...")
        try:
            # 1. Rétablissement de tous les flux d'applications
            res = subprocess.run(
                ["pactl", "-f", "json", "list", "sink-inputs"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
            )
            count = 0
            if res.returncode == 0 and res.stdout.strip():
                out = res.stdout.strip()
                idx_start = out.find("[")
                if idx_start != -1:
                    inputs = json.loads(out[idx_start:])
                    for item in inputs:
                        idx = item.get("index")
                        if idx is not None:
                            subprocess.run(["pactl", "set-sink-input-volume", str(idx), "100%"], check=False)
                            subprocess.run(["pactl", "set-sink-input-mute", str(idx), "0"], check=False)
                            count += 1

            # 2. Démuter la sortie principale
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=False)
            print(f"✅ [RESET] Audio rétabli avec succès ({count} application(s) réinitialisée(s) à 100%).")
            return True
        except Exception as e:
            print(f"❌ [RESET] Erreur lors de la réinitialisation : {e}")
            return False

    def _cleanup_on_exit(self):
        """Assure la restauration du son en cas d'arrêt inattendu du programme."""
        if self.is_ducked or self.saved_volumes:
            self.unduck()

    def __enter__(self):
        self.duck()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unduck()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--reset", "--restore", "-r"):
        AudioDucker.reset_all()
        sys.exit(0)

    print("🧪 [DEBUG] Test du module Ducking Audio (PipeWire / PulseAudio)...")
    ducker = AudioDucker(enabled=True, volume_percent=DUCKING_VOLUME_PERCENT)

    print(f"  • Statut Ducking     : {'Activé' if ducker.enabled else 'Désactivé'}")
    print(f"  • Niveau d'écoute    : {ducker.volume_percent}%")

    sink_inputs = ducker._list_sink_inputs()
    print(f"\n📡 {len(sink_inputs)} flux audio actifs détectés :")
    for s in sink_inputs:
        props = s.get("properties", {})
        print(f"  - [{s.get('index')}] {props.get('application.name', 'Inconnu')} (PID: {props.get('application.process.id')}) | Volume: {s.get('volume')}")

    if not sink_inputs:
        print("\n💡 Astuce : Lancez une vidéo YouTube ou de la musique pour tester l'atténuation en direct.")

    print("\n👉 Atténuation en cours (ducking)...")
    ducker.duck()
    print(f"  • Flux atténués : {list(ducker.saved_volumes.keys())}")

    print("⏳ Attente de 3 secondes en mode atténué...")
    time.sleep(3.0)

    print("\n👉 Restauration du volume (unducking)...")
    ducker.unduck()
    print("✅ Volume d'origine rétabli avec succès.")

