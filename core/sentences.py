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
_NON_WORD = re.compile(r"[^\w'\- ]+")


def clean_for_speech(text: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub("", text)).strip()


def normalize_utterance(text: str) -> str:
    """Minuscules, apostrophes unifiées, ponctuation retirée : « Au revoir ! » -> « au revoir »."""
    text = (text or "").lower().replace("’", "'")
    return " ".join(_NON_WORD.sub(" ", text).split())


def matches_phrase(text: str, phrases: list[str], fillers: list[str] = ()) -> bool:
    """True si l'énoncé entier est l'une des phrases, aux mots de remplissage près en début ou en fin
    (« Merci, au revoir ! » correspond à « au revoir », mais pas « baisse le son au revoir »)."""
    words = normalize_utterance(text).split()
    targets = {normalize_utterance(p) for p in phrases}
    filler_set = {normalize_utterance(f) for f in fillers}
    lead = next((i for i, w in enumerate(words) if w not in filler_set), len(words))
    trail = next((i for i, w in enumerate(reversed(words)) if w not in filler_set), len(words))
    # Toutes les façons de retirer des mots de remplissage aux extrémités (« c'est tout » garde son « c'est »)
    for i in range(lead + 1):
        for j in range(trail + 1):
            candidate = " ".join(words[i:len(words) - j])
            if candidate and candidate in targets:
                return True
    return False


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
