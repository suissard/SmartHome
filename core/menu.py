"""
Menus du terminal : choix aux flèches, en couleur, avec repli textuel (Windows, sortie non interactive).

Tout est affiché sur stderr : stdout est réservé au résultat, capturé par start.sh.
"""

import getpass
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

try:
    import termios
    import tty
except ImportError:  # Windows : menu textuel
    termios = None

# Une touche : séquence de flèche ou caractère seul
_KEYS = re.compile(rb"\x1b[\[O][A-D]|.", re.DOTALL)


class GoBack(Exception):
    """L'utilisateur demande la question précédente (flèche gauche)."""


@dataclass
class Option:
    label: str
    value: Any = None
    detail: str = ""
    tag: str = ""


def style(code: str, text: str) -> str:
    return text if os.environ.get("NO_COLOR") else f"\x1b[{code}m{text}\x1b[0m"


def note(text: str):
    print("  " + style("33", text), file=sys.stderr)


def answered(question: str, answer: str):
    print("  " + style("1;32", "✔") + f" {question} : " + style("1", answer), file=sys.stderr)


def menu_lines(title: str, options: list[Option], index: int, width: int, can_go_back: bool = False) -> list[str]:
    """Lignes du menu, tronquées à la largeur du terminal (une ligne repliée fausserait le réaffichage)."""
    room = max(width - 5, 10)
    lines = ["", "  " + style("1;36", title[:room]), ""]
    for i, option in enumerate(options):
        tag = f" · {option.tag}" if option.tag else ""
        selected = i == index
        head = f"{option.label}{tag}"[:room]
        label, tag = head[:len(option.label)], head[len(option.label):]
        lines.append(("  " + style("1;36", f"❯ {label}") + style("2;36", tag)) if selected
                     else ("    " + style("1", label) + style("2", tag)))
        if option.detail:
            lines.append("    " + style("36" if selected else "2", option.detail[:room]))
    keys = "↑/↓ choisir · Entrée valider" + (" · ← retour" if can_go_back else "") + " · q quitter"
    lines += ["", "  " + style("2", keys[:room]), ""]
    return lines


def _arrow_menu(title: str, options: list[Option], index: int, can_go_back: bool) -> int:
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    drawn = 0

    def draw():
        nonlocal drawn
        # Mesurée sur stderr : stdout est capturé par start.sh, shutil.get_terminal_size() y verrait 80 colonnes
        lines = menu_lines(title, options, index, os.get_terminal_size(sys.stderr.fileno()).columns, can_go_back)
        prefix = f"\x1b[{drawn}A\r\x1b[J" if drawn else ""
        sys.stderr.write(prefix + "\n".join(lines) + "\n")
        sys.stderr.flush()
        drawn = len(lines)

    try:
        tty.setcbreak(fd, termios.TCSADRAIN)
        sys.stderr.write("\x1b[?25l")
        draw()
        while True:
            data = os.read(fd, 32)
            if not data:
                raise KeyboardInterrupt
            for key in _KEYS.findall(data):
                if key in (b"\x1b[A", b"\x1bOA", b"k"):
                    index = (index - 1) % len(options)
                elif key in (b"\x1b[B", b"\x1bOB", b"j"):
                    index = (index + 1) % len(options)
                elif key.isdigit() and 1 <= int(key) <= len(options):
                    index = int(key) - 1
                elif key in (b"\r", b"\n"):
                    sys.stderr.write(f"\x1b[{drawn}A\r\x1b[J")
                    return index
                elif key in (b"\x1b[D", b"\x1bOD") and can_go_back:
                    sys.stderr.write(f"\x1b[{drawn}A\r\x1b[J")
                    raise GoBack
                elif key in (b"q", b"\x1b"):
                    raise KeyboardInterrupt
            draw()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    finally:
        sys.stderr.write("\x1b[?25h")
        sys.stderr.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _text_menu(title: str, options: list[Option], index: int) -> int:
    print(f"\n{title}", file=sys.stderr)
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option.label}" + (f" — {option.detail}" if option.detail else ""), file=sys.stderr)
    while True:
        print(f"Numéro ou nom [{options[index].label}] : ", end="", file=sys.stderr, flush=True)
        answer = input().strip()
        if not answer:
            return index
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        for i, option in enumerate(options):
            if answer == option.label:
                return i
        print("Choix invalide.", file=sys.stderr)


def choose(title: str, options: list[Option], index: int = 0, can_go_back: bool = False) -> Option:
    """Pose la question et retourne l'option choisie. Lève GoBack si l'utilisateur revient en arrière."""
    interactive = termios is not None and sys.stdin.isatty() and sys.stderr.isatty()
    chosen = _arrow_menu(title, options, index, can_go_back) if interactive else _text_menu(title, options, index)
    return options[chosen]


def ask_text(prompt: str, secret: bool = False) -> str:
    """Saisie libre ; `secret` masque la frappe."""
    text = f"  {prompt} : "
    try:
        if secret:
            return getpass.getpass(text, stream=sys.stderr).strip()
        print(text, end="", file=sys.stderr, flush=True)
        return input().strip()
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    picked = choose("🧪 [DEBUG] Menu de test", [Option("Un", 1, "Premier choix"), Option("Deux", 2, tag="étiquette")])
    print(f"Choix : {picked.label}")
