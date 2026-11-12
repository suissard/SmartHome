"""
Mesure de la latence de chaque tour, étape par étape (METRICS_ENABLED).

`TurnTimer` part au début de `AssistantCore.respond()` et note la première fois que chaque étape est atteinte :
- `stt`            : transcription terminée (enregistrement reçu) ;
- `first_token`    : premier fragment généré par le LLM ;
- `first_sentence` : première phrase prête à être dite (c'est ce qu'entend l'utilisateur) ;
- `llm`            : génération terminée (outils compris) ;
- `tts`            : synthèse de la réponse complète terminée (clients sans voix en streaming) ;
- `total`          : fin du tour.

Les mesures (en millisecondes depuis le début du tour) sont publiées par l'événement `timings`, affichées dans la
console, et rangées dans l'archive SQLite (table `timings`) pour suivre les régressions dans le temps :
`python core/metrics.py [jours]` affiche médiane et 90e centile par modèle.
"""

import sys
import time
from pathlib import Path
from typing import Iterable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# Étapes dans l'ordre du pipeline, et leur libellé (console, PWA, rapport)
STAGES = {
    "stt": "transcription",
    "first_token": "1er fragment",
    "first_sentence": "1re phrase",
    "llm": "génération",
    "tts": "synthèse",
    "total": "total",
}


class TurnTimer:
    """Chronomètre d'un tour : chaque étape n'est notée qu'une fois (la première)."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.start = clock()
        self.marks: dict[str, float] = {}

    def mark(self, stage: str) -> None:
        if stage not in self.marks:
            self.marks[stage] = self._clock()

    def as_ms(self) -> dict[str, int]:
        """Durées depuis le début du tour, en ms, dans l'ordre du pipeline."""
        known = [s for s in STAGES if s in self.marks] + [s for s in self.marks if s not in STAGES]
        return {s: round((self.marks[s] - self.start) * 1000) for s in known}


def format_timings(timings: dict[str, int]) -> str:
    """« transcription 320 ms · 1re phrase 910 ms · total 2,4 s »"""
    def fmt(ms: int) -> str:
        return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s".replace(".", ",")
    return " · ".join(f"{STAGES.get(s, s)} {fmt(ms)}" for s, ms in timings.items() if s != "first_token")


def percentile(values: list[float], q: float) -> Optional[float]:
    """Centile par interpolation linéaire (None pour une liste vide)."""
    if not values:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * q
    low = int(pos)
    high = min(low + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (pos - low)


def summarize(rows: Iterable[dict]) -> dict[str, dict[str, dict]]:
    """{modèle: {étape: {n, p50, p90}}} à partir de lignes {model, timings: {étape: ms}}."""
    by_model: dict[str, dict[str, list]] = {}
    for row in rows:
        stages = by_model.setdefault(row.get("model") or "?", {})
        for stage, ms in (row.get("timings") or {}).items():
            stages.setdefault(stage, []).append(ms)
    return {
        model: {stage: {"n": len(v), "p50": round(percentile(v, 0.5)), "p90": round(percentile(v, 0.9))}
                for stage, v in sorted(stages.items(), key=lambda kv: list(STAGES).index(kv[0]) if kv[0] in STAGES else 99)}
        for model, stages in by_model.items()
    }


if __name__ == "__main__":
    from core.archive import ConversationArchive

    days = float(sys.argv[1]) if len(sys.argv) > 1 else 7
    archive = ConversationArchive()
    rows = archive.timings_since(days)
    print(f"⏱️ [METRICS] {len(rows)} tour(s) mesuré(s) sur {days:g} jour(s) ({archive.path})")
    for model, stages in summarize(rows).items():
        print(f"\n  🧠 {model}")
        for stage, s in stages.items():
            print(f"    {STAGES.get(stage, stage):<14} médiane {s['p50']:>6} ms   p90 {s['p90']:>6} ms   ({s['n']} tours)")
    # Démonstration du chronomètre
    t = TurnTimer()
    t.mark("first_sentence")
    t.mark("total")
    print(f"\n🧪 [DEBUG] Exemple : {format_timings(t.as_ms())}")
