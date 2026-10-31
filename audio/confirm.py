"""
Confirmation vocale des actions dangereuses : pose la question via le TTS, écoute la réponse
et l'interprète (mots de confirmation, ou classification par le LLM en mode STT direct).
S'installe comme gestionnaire global via `core.tools.set_confirmation_handler`.
"""

import re
import sys
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

_NON_WORD = re.compile(r"[^\w'\- ]+")


def is_affirmative(answer: str, confirm_words: list[str], cancel_words: list[str]) -> bool:
    """True si la réponse contient un mot de confirmation et aucun mot d'annulation."""
    text = " " + _NON_WORD.sub(" ", (answer or "").lower()) + " "

    def contains(word: str) -> bool:
        return f" {word} " in text

    if any(contains(w) for w in cancel_words):
        return False
    return any(contains(w) for w in confirm_words)


class VoiceConfirmer:
    """Gestionnaire de confirmation utilisant le haut-parleur et le micro partagés."""

    def __init__(self, tts, transcriber, stream, settings: Optional[Settings] = None, conversation=None):
        self.tts = tts
        self.transcriber = transcriber
        self.stream = stream
        self.settings = settings or get_settings()
        self.conversation = conversation

    def __call__(self, description: str) -> bool:
        s = self.settings
        question = s.ACTIONS_CONFIRM_PROMPT.format(action=description.strip().rstrip(".").lower())
        print(f"\n❓ [CONFIRMATION] {question}")
        self.tts.speak(question)

        answer, _, _ = self.transcriber.record_and_transcribe(self.stream, timeout_silence=s.ACTIONS_CONFIRM_TIMEOUT)
        if isinstance(answer, bytes):
            answer = self._classify_audio(answer, description)

        accepted = is_affirmative(answer, s.ACTIONS_CONFIRM_WORDS, s.ACTIONS_CANCEL_WORDS)
        print(f"{'✅' if accepted else '⛔'} [CONFIRMATION] Réponse : « {answer or '(silence)'} »")
        return accepted

    def _classify_audio(self, wav: bytes, description: str) -> str:
        """Mode STT direct : demande au LLM multimodal si la réponse enregistrée est un oui."""
        if self.conversation is None:
            return ""
        messages = [
            {"role": "system", "content": "Réponds uniquement par le mot oui ou le mot non."},
            {"role": "user", "content": f"Dans cet enregistrement, l'utilisateur confirme-t-il l'action « {description} » ?"},
        ]
        try:
            return self.conversation.provider.chat(messages, audio_wav=wav).text
        except Exception as e:
            print(f"⚠️ [CONFIRMATION] Interprétation audio impossible : {e}")
            return ""


if __name__ == "__main__":
    s = get_settings()
    print("🧪 [DEBUG] Test de l'interprétation des réponses de confirmation :")
    for sample in ("Oui, vas-y.", "Non surtout pas !", "D'accord", "Euh... attends", "ok go", ""):
        print(f"  • « {sample} » -> {is_affirmative(sample, s.ACTIONS_CONFIRM_WORDS, s.ACTIONS_CANCEL_WORDS)}")
