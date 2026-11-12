"""
Rappels et routines programmés (SCHEDULER_ENABLED).

- **Rappel** : « rappelle-moi dans 10 minutes de sortir le linge » → à l'échéance, l'assistant le dit à voix haute sur
  l'ordinateur (SCHEDULER_LOCAL_ANNOUNCE) et l'affiche dans la PWA du compte (notification du navigateur).
- **Routine** : « tous les matins à 7 h, donne-moi la météo » → à l'échéance, la consigne est envoyée à l'assistant
  (session `routine-<n>`, droits du compte qui l'a créée, sans confirmation possible : les actions sensibles sont
  refusées) et sa réponse est annoncée comme un rappel.

Tout est rangé dans une base SQLite locale (SCHEDULER_DB_PATH) : les rappels survivent au redémarrage, ceux manqués
pendant un arrêt sont dits au retour s'ils datent de moins de SCHEDULER_MISSED_GRACE secondes. Un rappel ajouté par
un autre processus (serveur MCP) est vu au plus tard après SCHEDULER_POLL_SECONDS.

Événement publié à l'échéance (session « scheduler », abonnés globaux) :
`reminder` {id, kind, text, message, user_id, user_name, due_at, late, repeat}.

Les dates sont lues en français par `parse_when()` (« dans 1 h 30 », « à 18h », « demain 7h », « lundi à 9h15 »,
« ce soir à 8h », « le 24 décembre à 20h », ou ISO 8601) et `split_repeat()` (« tous les jours », « en semaine »,
« chaque lundi »...). Bibliothèque standard uniquement.
"""

import re
import sqlite3
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from string import Template
from typing import Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

SCHEDULER_SESSION = "scheduler"
KIND_REMINDER = "reminder"
KIND_ROUTINE = "routine"
REPEAT_NONE, REPEAT_DAILY, REPEAT_WEEKDAYS, REPEAT_WEEKLY = "", "daily", "weekdays", "weekly"
REPEAT_LABELS = {REPEAT_NONE: "une fois", REPEAT_DAILY: "tous les jours", REPEAT_WEEKDAYS: "en semaine",
                 REPEAT_WEEKLY: "toutes les semaines"}

# Dossier de référence d'un SCHEDULER_DB_PATH relatif (les tests le redirigent vers un dossier temporaire)
SCHEDULER_ROOT = _ROOT_DIR

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre",
          "decembre"]
_NUMBER_WORDS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "vingt": 20, "trente": 30, "quarante": 40, "quarante-cinq": 45, "cinquante": 50,
}
_NUM = r"(\d+|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_UNITS = {"s": 1, "sec": 1, "seconde": 1, "secondes": 1, "min": 60, "mn": 60, "minute": 60, "minutes": 60,
          "h": 3600, "heure": 3600, "heures": 3600, "jour": 86400, "jours": 86400, "semaine": 604800, "semaines": 604800}

_REPEAT_PATTERNS = [
    (REPEAT_WEEKDAYS, r"\b(en semaine|les jours ouvres|jours ouvrables|du lundi au vendredi|weekdays?)\b"),
    (REPEAT_DAILY, r"\b(tous les (jours|matins|soirs)|chaque (jour|matin|soir)|quotidien(nement)?|daily)\b"),
    (REPEAT_WEEKLY, r"\b(toutes les semaines|chaque semaine|hebdo(madaire)?|weekly)\b"),
    (REPEAT_WEEKLY, r"\b(tous les|chaque) (?=(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche))"),
]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("’", "'"))
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def _number(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBER_WORDS[word]


def _local(d: date, t: dtime) -> datetime:
    """Date et heure locales (fuseau de la machine, heure d'été comprise)."""
    return datetime.combine(d, t).astimezone()


def split_repeat(text: str) -> tuple[str, str]:
    """« tous les jours à 7h » → (« à 7h », "daily"). La répétition est retirée du texte de l'échéance."""
    norm = _norm(text)
    for repeat, pattern in _REPEAT_PATTERNS:
        if re.search(pattern, norm):
            norm = re.sub(pattern, " ", norm)
            if repeat == REPEAT_DAILY:  # « tous les soirs » garde l'indice du moment de la journée
                norm += " soir" if re.search(r"soirs?\b", _norm(text)) else ""
            return re.sub(r"\s+", " ", norm).strip(), repeat
    return norm, REPEAT_NONE


def parse_repeat(text: str) -> str:
    """Répétition demandée explicitement (« tous les jours », "daily"...) ; vide : une seule fois."""
    norm = _norm(text)
    if norm in ("", "non", "aucune", "une fois", "none", "once", REPEAT_NONE):
        return REPEAT_NONE
    if norm in (REPEAT_DAILY, REPEAT_WEEKDAYS, REPEAT_WEEKLY):
        return norm
    _, repeat = split_repeat(norm)
    if repeat == REPEAT_NONE:
        raise ValueError(f"Répétition « {text} » inconnue : tous les jours, en semaine ou toutes les semaines.")
    return repeat


def _parse_clock(norm: str) -> Optional[dtime]:
    """Heure du jour dans le texte : « 18h30 », « 7 heures et demie », « 18:30 », « midi », « minuit »."""
    if re.search(r"(?<!apres-)(?<!apres )\bmidi\b", norm):
        hour, minute = 12, 0
    elif re.search(r"\bminuit\b", norm):
        hour, minute = 0, 0
    else:
        m = re.search(r"\b(\d{1,2}) ?(?:h|heures?|:) ?(\d{2})?\b", norm) or \
            re.search(r"\b" + _NUM + r" heures?\b", norm)
        if not m:
            return None
        hour = _number(m.group(1))
        minute = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else 0
    if re.search(r"\bet demie?\b", norm):
        minute += 30
    elif re.search(r"\bet quart\b", norm):
        minute += 15
    elif re.search(r"\bmoins le quart\b", norm):
        hour, minute = hour - 1, minute + 45
    if re.search(r"\b(soir|apres-midi|apres midi)\b", norm) and 1 <= hour < 12:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Heure invalide : {hour}h{minute:02d}.")
    return dtime(hour % 24, minute)


def _parse_day(norm: str, today: date) -> Optional[date]:
    if re.search(r"\bapres-?demain\b|\bapres demain\b", norm):
        return today + timedelta(days=2)
    if re.search(r"\bdemain\b", norm):
        return today + timedelta(days=1)
    if re.search(r"\b(aujourd'hui|ce soir|ce matin|cet apres-midi|tout a l'heure)\b", norm):
        return today
    m = re.search(r"\b(\d{1,2})(?:er)? (" + "|".join(MONTHS) + r")(?: (\d{4}))?\b", norm)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        d = date(year, MONTHS.index(m.group(2)) + 1, int(m.group(1)))
        return d if m.group(3) or d >= today else date(year + 1, d.month, d.day)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", norm)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        year += 2000 if year < 100 else 0
        d = date(year, int(m.group(2)), int(m.group(1)))
        return d if m.group(3) or d >= today else date(year + 1, d.month, d.day)
    for index, name in enumerate(WEEKDAYS):
        if re.search(r"\b" + name + r"s?\b", norm):
            ahead = (index - today.weekday()) % 7
            if re.search(r"\b" + name + r" prochain\b", norm) and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead)
    return None


def parse_when(text: str, now: Optional[datetime] = None, default_hour: int = 9) -> datetime:
    """Échéance (datetime locale avec fuseau) d'un texte en français ou ISO 8601. Lève ValueError si incompris
    ou déjà passée."""
    now = (now or datetime.now()).astimezone()
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Indique quand : « dans 10 minutes », « demain à 7h », « lundi à 18h30 »...")
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        when = when.astimezone() if when.tzinfo else when.astimezone()
    except ValueError:
        when = None
    if when is None:
        norm = _norm(raw)
        if re.search(r"\b(dans|d'ici)\b", norm):
            seconds = 0
            if re.search(r"\b(un|1) quart d'heure\b", norm):
                seconds += 900
            if re.search(r"\bune? demi-?heure\b|\bune demi heure\b", norm):
                seconds += 1800
            m = re.search(r"\b(\d{1,2}) ?h ?(\d{1,2})\b", norm)
            if m:
                seconds += int(m.group(1)) * 3600 + int(m.group(2)) * 60
                norm = norm.replace(m.group(0), " ")
            for number, unit in re.findall(_NUM + r" ?(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b", norm):
                seconds += _number(number) * _UNITS[unit]
            if re.search(r"\bheures? et demie\b", norm):
                seconds += 1800
            if seconds <= 0:
                raise ValueError(f"Durée incomprise : « {raw} ».")
            when = now + timedelta(seconds=seconds)
        else:
            if re.search(r"\b(hier|avant-hier|la veille)\b", norm):
                raise ValueError(f"L'échéance « {raw} » est déjà passée.")
            clock = _parse_clock(norm)
            day = _parse_day(norm, now.date())
            if clock is None and day is None:
                raise ValueError(f"Je n'ai pas compris quand : « {raw} ». Exemples : « dans 10 minutes », "
                                 "« demain à 7h », « lundi à 18h30 », « le 24 décembre à 20h ».")
            if clock is None:
                clock = dtime(19, 0) if re.search(r"\bce soir\b", norm) else dtime(default_hour, 0)
            when = _local(day or now.date(), clock)
            if day is None and when <= now:  # « à 7h » alors qu'il est 8h : demain
                when = _local(now.date() + timedelta(days=1), clock)
            elif day is not None and when <= now and re.search("|".join(WEEKDAYS), norm):
                when = _local(day + timedelta(days=7), clock)
    if when <= now:
        raise ValueError(f"L'échéance « {raw} » est déjà passée.")
    return when


def next_occurrence(due: datetime, repeat: str, now: datetime) -> Optional[datetime]:
    """Prochaine échéance d'un rappel répété, strictement après `now` (même heure locale)."""
    if repeat == REPEAT_NONE:
        return None
    step = 7 if repeat == REPEAT_WEEKLY else 1
    clock = due.astimezone().timetz().replace(tzinfo=None)
    day = due.astimezone().date()
    while True:
        day += timedelta(days=step)
        if repeat == REPEAT_WEEKDAYS and day.weekday() >= 5:
            continue
        candidate = _local(day, clock)
        if candidate > now:
            return candidate


def describe_due(when: datetime, now: Optional[datetime] = None) -> str:
    """« aujourd'hui à 18:30 », « demain à 07:00 », « lundi 17 novembre à 09:00 »."""
    now = (now or datetime.now()).astimezone()
    when = when.astimezone()
    delta = (when.date() - now.date()).days
    clock = when.strftime("%H:%M")
    if delta == 0:
        return f"aujourd'hui à {clock}"
    if delta == 1:
        return f"demain à {clock}"
    month = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"][when.month - 1]
    return f"{WEEKDAYS[when.weekday()]} {when.day} {month} à {clock}"


@dataclass
class Reminder:
    id: int
    kind: str
    message: str           # ce qu'il faut rappeler (rappel) ou la consigne à exécuter (routine)
    due_at: float          # prochaine échéance (horodatage Unix)
    repeat: str = REPEAT_NONE
    user_id: str = ""
    user_name: str = ""
    user_role: str = ""
    superadmin: bool = False
    fired_count: int = 0

    @property
    def due(self) -> datetime:
        return datetime.fromtimestamp(self.due_at).astimezone()

    def public(self, now: Optional[datetime] = None) -> dict:
        return {"id": self.id, "kind": self.kind, "message": self.message, "due_at": self.due_at,
                "due": describe_due(self.due, now), "repeat": self.repeat, "user": self.user_name}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    message      TEXT NOT NULL,
    due_at       REAL NOT NULL,
    repeat       TEXT NOT NULL DEFAULT '',
    user_id      TEXT NOT NULL DEFAULT '',
    user_name    TEXT NOT NULL DEFAULT '',
    user_role    TEXT NOT NULL DEFAULT '',
    superadmin   INTEGER NOT NULL DEFAULT 0,
    fired_count  INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    finished_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (finished_at, due_at);
"""


class ReminderStore:
    """Rappels en attente (SQLite, une connexion par opération : partagée sans risque entre fils et processus)."""

    def __init__(self, settings: Optional[Settings] = None, path: Optional[Path] = None):
        self.settings = settings or get_settings()
        raw = Path(path or self.settings.SCHEDULER_DB_PATH)
        self.path = raw if raw.is_absolute() else SCHEDULER_ROOT / raw
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        if not self._ready:
            conn.executescript(_SCHEMA)
            self._ready = True
        return conn

    def _execute(self, sql: str, params=()) -> tuple[list[sqlite3.Row], Optional[int]]:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute(sql, tuple(params))
                    return cur.fetchall(), cur.lastrowid
            finally:
                conn.close()

    def _query(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self._execute(sql, params)[0]

    @staticmethod
    def _row(r: sqlite3.Row) -> Reminder:
        return Reminder(r["id"], r["kind"], r["message"], r["due_at"], r["repeat"], r["user_id"], r["user_name"],
                        r["user_role"], bool(r["superadmin"]), r["fired_count"])

    def add(self, kind: str, message: str, due: datetime, repeat: str = REPEAT_NONE, user=None) -> Reminder:
        user_id = getattr(user, "id", "") or ""
        if len(self.active(user_id)) >= self.settings.SCHEDULER_MAX_PER_USER:
            raise ValueError(f"Trop de rappels en attente ({self.settings.SCHEDULER_MAX_PER_USER} au plus) : "
                             "annule-en avant d'en ajouter.")
        _, new_id = self._execute(
            "INSERT INTO reminders (kind, message, due_at, repeat, user_id, user_name, user_role, superadmin, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, message, due.timestamp(), repeat, user_id, getattr(user, "name", "") or "",
             getattr(user, "role", "") or "", int(bool(getattr(user, "superadmin", False))), time.time()))
        return self.get(new_id)

    def get(self, reminder_id: int) -> Optional[Reminder]:
        rows = self._query("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        return self._row(rows[0]) if rows else None

    def active(self, user_id: Optional[str] = None) -> list[Reminder]:
        """Rappels en attente (de ce compte si `user_id` n'est pas None), le plus proche d'abord."""
        if user_id is None:
            rows = self._query("SELECT * FROM reminders WHERE finished_at IS NULL ORDER BY due_at")
        else:
            rows = self._query("SELECT * FROM reminders WHERE finished_at IS NULL AND user_id = ? ORDER BY due_at",
                               (user_id,))
        return [self._row(r) for r in rows]

    def due(self, now: float) -> list[Reminder]:
        rows = self._query("SELECT * FROM reminders WHERE finished_at IS NULL AND due_at <= ? ORDER BY due_at", (now,))
        return [self._row(r) for r in rows]

    def next_due_at(self) -> Optional[float]:
        rows = self._query("SELECT MIN(due_at) AS t FROM reminders WHERE finished_at IS NULL")
        return rows[0]["t"] if rows and rows[0]["t"] is not None else None

    def reschedule(self, reminder_id: int, due: datetime, fired: bool = True):
        self._query("UPDATE reminders SET due_at = ?, fired_count = fired_count + ? WHERE id = ?",
                    (due.timestamp(), int(fired), reminder_id))

    def finish(self, reminder_id: int, fired: bool = True):
        self._query("UPDATE reminders SET finished_at = ?, fired_count = fired_count + ? WHERE id = ?",
                    (time.time(), int(fired), reminder_id))

    def cancel(self, reminder_id: int, user_id: Optional[str] = None) -> bool:
        """Annule un rappel en attente (seulement s'il appartient à `user_id`, quand il est donné)."""
        reminder = self.get(reminder_id)
        if reminder is None or (user_id is not None and reminder.user_id != user_id):
            return False
        self.finish(reminder_id, fired=False)
        return True


class Scheduler:
    """Déclenche les rappels à l'échéance dans un fil d'arrière-plan (start/stop) ; `run_due()` pour les tests."""

    def __init__(self, core, settings: Optional[Settings] = None, store: Optional[ReminderStore] = None,
                 clock: Callable[[], float] = time.time):
        self.core = core
        self._settings = settings
        self.store = store or ReminderStore(self.settings)
        self.clock = clock
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def settings(self) -> Settings:
        # Réglages à jour du cœur (modifiés à chaud depuis l'interface), sinon ceux donnés à la création
        return getattr(self.core, "settings", None) or self._settings or get_settings()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running or not self.settings.SCHEDULER_ENABLED:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="smarthome-scheduler", daemon=True)
        self._thread.start()
        pending = self.store.active()
        print(f"⏰ [SCHEDULER] Démarré : {len(pending)} rappel(s) en attente.")

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def wake(self):
        """Un rappel vient d'être ajouté : l'échéance est recalculée sans attendre."""
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.run_due()
                next_at = self.store.next_due_at()
            except Exception as e:  # base illisible, etc. : on réessaie plus tard sans jamais tuer le fil
                print(f"⚠️ [SCHEDULER] {e}")
                next_at = None
            wait = self.settings.SCHEDULER_POLL_SECONDS
            if next_at is not None:
                wait = max(0.2, min(wait, next_at - self.clock()))
            self._wake.wait(timeout=wait)
            self._wake.clear()

    def run_due(self) -> list[dict]:
        """Déclenche tout ce qui est échu ; retourne les événements publiés."""
        now = self.clock()
        fired = []
        for reminder in self.store.due(now):
            late_by = now - reminder.due_at
            if late_by > self.settings.SCHEDULER_MISSED_GRACE:
                print(f"⏰ [SCHEDULER] Rappel n°{reminder.id} manqué depuis trop longtemps ({late_by / 3600:.1f} h) : ignoré.")
                event = None
            else:
                event = self._fire(reminder, late=late_by > 120)
                fired.append(event)
            upcoming = next_occurrence(reminder.due, reminder.repeat, datetime.fromtimestamp(now).astimezone())
            if upcoming is not None:
                self.store.reschedule(reminder.id, upcoming, fired=event is not None)
            else:
                self.store.finish(reminder.id, fired=event is not None)
        return fired

    def _routine_user(self, reminder: Reminder):
        from core.users import LOCAL_USER_ID, User, local_user
        if not reminder.user_id or reminder.user_id == LOCAL_USER_ID:
            return local_user(self.settings)
        return User(reminder.user_id, reminder.user_name, reminder.user_role, superadmin=reminder.superadmin)

    def _fire(self, reminder: Reminder, late: bool) -> dict:
        s = self.settings
        if reminder.kind == KIND_ROUTINE:
            try:
                reply = self.core.respond(f"routine-{reminder.id}", text=reminder.message,
                                          user=self._routine_user(reminder))
                text = reply.text or ""
            except Exception as e:
                text = Template(s.SCHEDULER_ROUTINE_ERROR).safe_substitute(MESSAGE=reminder.message, ERROR=str(e))
        else:
            template = s.SCHEDULER_LATE_TEMPLATE if late else s.SCHEDULER_REMINDER_TEMPLATE
            text = Template(template).safe_substitute(MESSAGE=reminder.message, TIME=reminder.due.strftime("%H:%M"))
        print(f"⏰ [SCHEDULER] {reminder.kind} n°{reminder.id} ({reminder.user_name or 'foyer'}) : {text}")
        data = {"id": reminder.id, "kind": reminder.kind, "text": text, "message": reminder.message,
                "user_id": reminder.user_id, "user_name": reminder.user_name, "due_at": reminder.due_at,
                "late": late, "repeat": reminder.repeat}
        events = getattr(self.core, "events", None)
        if events is not None:
            events.emit("reminder", SCHEDULER_SESSION, **data)
        return data


if __name__ == "__main__":
    now = datetime.now().astimezone()
    print(f"🧪 [DEBUG] Maintenant : {now:%A %d/%m %H:%M}")
    for sample in ["dans 10 minutes", "dans 1h30", "dans une demi-heure", "à 18h30", "demain à 7h",
                   "lundi à 9h15", "ce soir à 8h", "le 24 décembre à 20h", "tous les jours à 7h", "en semaine à 6h45"]:
        rest, repeat = split_repeat(sample)
        try:
            when = parse_when(rest, now)
            print(f"  « {sample} » → {describe_due(when, now)} ({REPEAT_LABELS[repeat]})")
        except ValueError as e:
            print(f"  « {sample} » → ⚠️ {e}")
    store = ReminderStore()
    print(f"🧪 [DEBUG] Base : {store.path} — {len(store.active())} rappel(s) en attente")
    for r in store.active():
        print(f"  ⏰ n°{r.id} {r.kind} {describe_due(r.due, now)} ({REPEAT_LABELS.get(r.repeat, r.repeat)}) : {r.message}")
