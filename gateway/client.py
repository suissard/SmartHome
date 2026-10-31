"""
Client console de la passerelle : discuter avec SmartHome depuis un autre appareil (ou pour déboguer).

    python -m gateway.client --url ws://100.x.y.z:8765/ws --token <GATEWAY_AUTH_TOKEN>
    python -m gateway.client --wav question.wav --speak     # envoie un enregistrement, joue la réponse vocale

Les demandes de confirmation (extinction...) s'affichent et attendent « o » ou « n ».
"""

import argparse
import base64
import io
import json
import sys
from pathlib import Path

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from websockets.sync.client import connect

from core.config import get_settings


def play_wav(data: bytes):
    import sounddevice as sd
    from scipy.io import wavfile
    sample_rate, samples = wavfile.read(io.BytesIO(data))
    sd.play(samples, samplerate=sample_rate)
    sd.wait()


def run_request(ws, message: dict, speak: bool):
    """Envoie une demande puis affiche les événements jusqu'à {"type": "done"}."""
    ws.send(json.dumps({**message, "speak": speak}))
    while True:
        event = json.loads(ws.recv())
        kind = event.get("type")
        if kind == "token":
            print(event["text"], end="", flush=True)
        elif kind == "transcript":
            print(f"👤 (transcrit) « {event['text']} »\n🤖 ", end="", flush=True)
        elif kind == "tool":
            status = "✅" if event["executed"] else "⛔"
            print(f"\n   {status} outil {event['name']}({json.dumps(event['arguments'], ensure_ascii=False)}) → {event['output']}")
        elif kind == "confirm_request":
            answer = input(f"\n❓ {event['question']} [o/N] ").strip().lower()
            ws.send(json.dumps({"type": "confirm_response", "id": event["id"], "accepted": answer in ("o", "oui", "y", "yes")}))
        elif kind == "response":
            print(f"\n🗣️  « {event['text']} »")
        elif kind == "audio" and speak:
            play_wav(base64.b64decode(event["data"]))
        elif kind == "error":
            print(f"\n⚠️ {event['message']}")
        elif kind == "done":
            return


def main():
    s = get_settings()
    parser = argparse.ArgumentParser(description="Client console de la passerelle SmartHome.")
    parser.add_argument("--url", default=f"ws://{s.GATEWAY_HOST}:{s.GATEWAY_PORT}/ws")
    parser.add_argument("--token", default=s.GATEWAY_AUTH_TOKEN, help="Jeton de la passerelle (défaut : GATEWAY_AUTH_TOKEN)")
    parser.add_argument("--session", default=None, help="Reprendre une session existante (historique conservé)")
    parser.add_argument("--wav", default=None, help="Envoyer ce fichier WAV au lieu de taper du texte")
    parser.add_argument("--speak", action="store_true", help="Demander la réponse vocale et la jouer ici")
    args = parser.parse_args()

    url = f"{args.url}{'&' if '?' in args.url else '?'}session={args.session}" if args.session else args.url
    with connect(url, max_size=s.GATEWAY_MAX_MESSAGE_BYTES) as ws:
        # Authentification par premier message (même mécanisme qu'un navigateur)
        if args.token:
            ws.send(json.dumps({"type": "auth", "token": args.token, "session": args.session}))
        ready = json.loads(ws.recv())
        if ready.get("type") != "ready":
            print(f"❌ Connexion refusée : {ready.get('message', ready)}")
            sys.exit(1)
        print(f"🟢 Connecté (session {ready['session']}, {len(ready['tools'])} outils). Ctrl+C pour quitter.")

        if args.wav:
            data = base64.b64encode(Path(args.wav).read_bytes()).decode()
            run_request(ws, {"type": "audio", "data": data}, args.speak)
            return

        while True:
            try:
                text = input("\nToi > ").strip()
            except (KeyboardInterrupt, EOFError):
                break
            if text == "/reset":
                ws.send(json.dumps({"type": "reset"}))
                ws.recv()
                print("🧹 Historique réinitialisé.")
            elif text:
                print("🤖 ", end="", flush=True)
                run_request(ws, {"type": "text", "text": text}, args.speak)


if __name__ == "__main__":
    main()
