"""
Découpage en phrases d'une réponse reçue en streaming, pour la prononcer au fil de l'eau.

Une fin de phrase (. ! ? … ou retour à la ligne) n'est validée que lorsque le caractère suivant est connu
et est un espace : « 40.5 » n'est donc jamais coupé, même si « 40. » et « 5 » arrivent séparément.
Les tags d'actions ([VOLUME 40]) sont retirés du texte prononcé.
"""

import re

_BOUNDARY = re.compile(r"(?:[.!?…]+[\"»)]*|\n+)(?=\s)")
_TAGS = re.compile(r"\[[A-Z_]+(?:\s+[^\]]+)?\]")
_HAS_WORD = re.compile(r"\w")


def clean_for_speech(text: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub("", text)).strip()


class SentenceSplitter:
    def __init__(self, min_chars: int = 25):
        self.min_chars = min_chars
        self.buffer = ""

    def feed(self, token: str) -> list[str]:
        """Ajoute un fragment et retourne les phrases désormais complètes (assez longues pour être dites)."""
        self.buffer += token
        sentences = []
        start = 0
        for match in _BOUNDARY.finditer(self.buffer):
            candidate = clean_for_speech(self.buffer[start:match.end()])
            if len(candidate) >= self.min_chars:
                sentences.append(candidate)
                start = match.end()
        self.buffer = self.buffer[start:]
        return [s for s in sentences if _HAS_WORD.search(s)]

    def flush(self) -> list[str]:
        """Retourne le reste du texte (fin de réponse)."""
        rest = clean_for_speech(self.buffer)
        self.buffer = ""
        return [rest] if _HAS_WORD.search(rest) else []


if __name__ == "__main__":
    print("🧪 [DEBUG] Découpage d'un flux simulé :")
    splitter = SentenceSplitter(min_chars=20)
    stream = ["[VOLUME 40] Très", " bien, le volume", " est réglé à 40.", "5 %. Autre", " chose ? Je", " peux aussi ouvrir", " une application."]
    for token in stream:
        for sentence in splitter.feed(token):
            print(f"  • « {sentence} »")
    for sentence in splitter.flush():
        print(f"  • « {sentence} » (fin)")
