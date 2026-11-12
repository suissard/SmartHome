"""
Package de tests et d'outils de validation pour SmartHome.
"""

import atexit
import itertools
import shutil
import tempfile
from pathlib import Path

# L'archive des conversations (core/archive.py) ne reçoit jamais les échanges des tests : chaque archive créée
# sans chemin explicite a sa propre base, dans un dossier temporaire (un cœur de test ne voit pas ceux des autres)
import core.archive

_ARCHIVE_TMP = Path(tempfile.mkdtemp(prefix="smarthome-tests-archive-"))
atexit.register(shutil.rmtree, _ARCHIVE_TMP, ignore_errors=True)
core.archive.ARCHIVE_ROOT = _ARCHIVE_TMP
_numbers = itertools.count()
_original_init = core.archive.ConversationArchive.__init__


def _isolated_init(self, settings=None, path=None):
    _original_init(self, settings, path or _ARCHIVE_TMP / f"archive-{next(_numbers)}.sqlite3")


core.archive.ConversationArchive.__init__ = _isolated_init

# Même chose pour les rappels programmés (core/scheduler.py) : une base temporaire par magasin
import core.scheduler

core.scheduler.SCHEDULER_ROOT = _ARCHIVE_TMP
_original_store_init = core.scheduler.ReminderStore.__init__


def _isolated_store_init(self, settings=None, path=None):
    _original_store_init(self, settings, path or _ARCHIVE_TMP / f"scheduler-{next(_numbers)}.sqlite3")


core.scheduler.ReminderStore.__init__ = _isolated_store_init

# Et pour la mémoire à long terme (core/memory.py)
import core.memory

core.memory.MEMORY_ROOT = _ARCHIVE_TMP
_original_memory_init = core.memory.MemoryStore.__init__


def _isolated_memory_init(self, settings=None, path=None, embedder=None):
    _original_memory_init(self, settings, path or _ARCHIVE_TMP / f"memory-{next(_numbers)}.sqlite3", embedder)


core.memory.MemoryStore.__init__ = _isolated_memory_init
