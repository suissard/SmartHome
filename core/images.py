"""
Images de la conversation et recherche de fichiers.

- Images envoyées par l'interface web : `decode_upload()` vérifie la taille (IMAGES_MAX_BYTES) et le format réel
  (signature des octets, jamais le type annoncé par le navigateur), `save_upload()` les copie dans IMAGES_UPLOAD_DIR
  pour un agent externe (il reçoit leur chemin).
- Images montrées par l'assistant : `search_files()` cherche dans les seuls dossiers FILES_SEARCH_DIRS (sous-dossiers
  jusqu'à FILES_SEARCH_MAX_DEPTH, fichiers et dossiers cachés ignorés) ; `load_image()` lit une image de ces dossiers.
  `resolve_allowed()` refuse tout chemin qui en sort (« .. », lien symbolique vers l'extérieur).
"""

import base64
import fnmatch
import hashlib
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

# Signatures des formats d'image acceptés : (début du fichier, type MIME, extension)
_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"BM", "image/bmp", ".bmp"),
]


class ImageError(ValueError):
    """Image refusée (format, taille, chemin hors des dossiers permis)."""


@dataclass
class Image:
    data: bytes
    mime: str
    name: str = ""

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    @property
    def data_url(self) -> str:
        return f"data:{self.mime};base64,{self.base64}"

    def public(self, **extra) -> dict:
        """Forme envoyée au client (événement « image »)."""
        return {"name": self.name, "mime": self.mime, "data": self.base64, **extra}


def sniff_mime(data: bytes) -> Optional[str]:
    """Type MIME d'après les premiers octets (None : pas une image reconnue)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime, _ in _SIGNATURES:
        if data.startswith(magic):
            return mime
    return None


def _extension(mime: str) -> str:
    if mime == "image/webp":
        return ".webp"
    return next((ext for _, m, ext in _SIGNATURES if m == mime), ".img")


def decode_upload(item, settings: Optional[Settings] = None) -> Image:
    """Image reçue du client : {"data": base64 (ou data URL), "name"?}. Lève ImageError si elle est refusée."""
    s = settings or get_settings()
    if not isinstance(item, dict) or not isinstance(item.get("data"), str):
        raise ImageError("Image mal formée.")
    raw = item["data"]
    if raw.startswith("data:"):
        raw = raw.partition(",")[2]
    # Taille estimée avant décodage : un envoi géant n'est jamais décodé
    if len(raw) * 3 // 4 > s.IMAGES_MAX_BYTES:
        raise ImageError(f"Image trop lourde (maximum {s.IMAGES_MAX_BYTES // 1_000_000} Mo).")
    try:
        data = base64.b64decode(raw, validate=True)
    except ValueError:
        raise ImageError("Image illisible (base64 invalide).") from None
    if len(data) > s.IMAGES_MAX_BYTES:
        raise ImageError(f"Image trop lourde (maximum {s.IMAGES_MAX_BYTES // 1_000_000} Mo).")
    mime = sniff_mime(data)
    if mime is None:
        raise ImageError("Format d'image non pris en charge (PNG, JPEG, GIF, WebP ou BMP).")
    name = Path(str(item.get("name") or "")).name[:120] or f"image{_extension(mime)}"
    return Image(data, mime, name)


def decode_uploads(items, settings: Optional[Settings] = None) -> list[Image]:
    s = settings or get_settings()
    if not items:
        return []
    if not s.IMAGES_ENABLED:
        raise ImageError("Les images sont désactivées (IMAGES_ENABLED=false).")
    if not isinstance(items, list):
        raise ImageError("Liste d'images attendue.")
    if len(items) > s.IMAGES_MAX_PER_MESSAGE:
        raise ImageError(f"{s.IMAGES_MAX_PER_MESSAGE} images au maximum par message.")
    return [decode_upload(item, s) for item in items]


def save_upload(image: Image, settings: Optional[Settings] = None) -> Path:
    """Copie l'image dans IMAGES_UPLOAD_DIR (nom tiré de son contenu : un même envoi n'est écrit qu'une fois)."""
    s = settings or get_settings()
    folder = Path(s.IMAGES_UPLOAD_DIR).expanduser()
    if not folder.is_absolute():
        folder = _ROOT_DIR / folder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{hashlib.sha256(image.data).hexdigest()[:16]}{_extension(image.mime)}"
    if not path.exists():
        path.write_bytes(image.data)
    return path


# ==========================================
# Recherche dans les dossiers permis
# ==========================================
def search_roots(settings: Optional[Settings] = None) -> list[Path]:
    """Dossiers FILES_SEARCH_DIRS existants, chemins absolus résolus (doublons retirés)."""
    s = settings or get_settings()
    roots = []
    for entry in s.FILES_SEARCH_DIRS:
        path = Path(os.path.expandvars(entry)).expanduser()
        if not path.is_absolute():
            path = _ROOT_DIR / path
        try:
            path = path.resolve(strict=True)
        except OSError:
            continue
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def _fold(text: str) -> str:
    """Minuscules sans accents, pour comparer un nom de fichier à la demande."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _display(path: Path, roots: list[Path]) -> str:
    """Chemin affiché : ~/… sous le dossier personnel, sinon absolu."""
    home = Path.home()
    return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)


def resolve_allowed(path_text: str, settings: Optional[Settings] = None) -> Path:
    """Fichier existant situé dans un dossier FILES_SEARCH_DIRS. Lève ImageError sinon."""
    roots = search_roots(settings)
    if not roots:
        raise ImageError("Aucun dossier de recherche configuré (FILES_SEARCH_DIRS).")
    text = (path_text or "").strip().strip("\"'")
    if not text:
        raise ImageError("Chemin du fichier manquant.")
    candidate = Path(os.path.expandvars(text)).expanduser()
    # Chemin relatif : cherché dans chaque dossier permis, dans l'ordre
    options = [candidate] if candidate.is_absolute() else [root / candidate for root in roots]
    for option in options:
        try:
            resolved = option.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and any(resolved.is_relative_to(root) for root in roots):
            return resolved
        if resolved.exists():
            break
    if any(_safe_exists(o) for o in options):
        raise ImageError(f"« {text} » est en dehors des dossiers permis ({', '.join(_display(r, roots) for r in roots)}).")
    raise ImageError(f"Fichier « {text} » introuvable.")


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def search_files(query: str, settings: Optional[Settings] = None, images_only: bool = False) -> list[str]:
    """Fichiers des dossiers permis dont le chemin contient tous les mots de `query` (accents et casse ignorés),
    ou correspondant au motif s'il contient * ou ?. Les plus récents d'abord, au plus FILES_SEARCH_MAX_RESULTS."""
    s = settings or get_settings()
    roots = search_roots(s)
    pattern = (query or "").strip().strip("\"'")
    is_glob = any(c in pattern for c in "*?[")
    words = _fold(pattern).replace("/", " ").replace("_", " ").replace("-", " ").split() if not is_glob else []
    extensions = {e if e.startswith(".") else f".{e}" for e in s.FILES_IMAGE_EXTENSIONS}
    found: list[tuple[float, Path]] = []
    seen: set[Path] = set()
    # Parcours borné : au-delà de ce nombre de fichiers examinés, la recherche s'arrête (dossier personnel entier...)
    budget = 50_000

    for root in roots:
        for folder, dirs, files in os.walk(root):
            depth = len(Path(folder).relative_to(root).parts)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if depth < s.FILES_SEARCH_MAX_DEPTH else []
            for name in files:
                budget -= 1
                if budget < 0:
                    break
                if name.startswith("."):
                    continue
                path = Path(folder) / name
                if images_only and path.suffix.lower() not in extensions:
                    continue
                relative = str(path.relative_to(root))
                if is_glob:
                    if not (fnmatch.fnmatch(_fold(name), _fold(pattern)) or fnmatch.fnmatch(_fold(relative), _fold(pattern))):
                        continue
                else:
                    folded = _fold(relative).replace("_", " ").replace("-", " ")
                    if not all(w in folded for w in words):
                        continue
                if path in seen:
                    continue
                seen.add(path)
                try:
                    found.append((path.stat().st_mtime, path))
                except OSError:
                    continue
            if budget < 0:
                break
    found.sort(key=lambda item: item[0], reverse=True)
    return [_display(p, roots) for _, p in found[: s.FILES_SEARCH_MAX_RESULTS]]


def load_image(path_text: str, settings: Optional[Settings] = None) -> tuple[Image, str]:
    """Image d'un dossier permis : (image, chemin affiché). Lève ImageError."""
    s = settings or get_settings()
    path = resolve_allowed(path_text, s)
    extensions = {e if e.startswith(".") else f".{e}" for e in s.FILES_IMAGE_EXTENSIONS}
    if path.suffix.lower() not in extensions:
        raise ImageError(f"« {path.name} » n'est pas une image ({', '.join(sorted(extensions))}).")
    size = path.stat().st_size
    if size > s.IMAGES_MAX_BYTES:
        raise ImageError(f"« {path.name} » est trop lourde ({size // 1_000_000} Mo, maximum {s.IMAGES_MAX_BYTES // 1_000_000} Mo).")
    data = path.read_bytes()
    mime = sniff_mime(data)
    if mime is None:
        raise ImageError(f"« {path.name} » n'est pas une image lisible.")
    return Image(data, mime, path.name), _display(path, search_roots(s))


if __name__ == "__main__":
    s = get_settings()
    print("🧪 [DEBUG] Test du module core/images.py")
    roots = search_roots(s)
    print(f"Dossiers de recherche : {', '.join(map(str, roots)) or 'aucun (FILES_SEARCH_DIRS)'}")
    query = " ".join(sys.argv[1:])
    if query:
        results = search_files(query, s)
        print(f"Résultats pour « {query} » ({len(results)}) :")
        for r in results:
            print(f"  • {r}")
        images = [r for r in results if Path(r).suffix.lower() in s.FILES_IMAGE_EXTENSIONS]
        if images:
            image, shown = load_image(images[0], s)
            print(f"Première image : {shown} ({image.mime}, {len(image.data)} octets)")
    else:
        print("Usage : python -m core.images <recherche>")
