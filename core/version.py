#!/usr/bin/env python3
"""
Vérification de version et de mise à jour via GitHub.
Récupère automatiquement le nom du dépôt GitHub (`owner/repo`) depuis le remote Git local (`origin`),
compare la version locale (commit HEAD) avec la branche distante sur GitHub, et indique si une
différence / mise à jour est disponible pour afficher une pastille dans l'interface web.

Diagnostic autonome :
    python -m core.version
"""

import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_GITHUB_REPO = "suissard/SmartHome"
CACHE_TTL_SECONDS = 300.0

_cache: dict = {"timestamp": 0.0, "data": None}


def _git(*args: str, timeout: float = 3.0) -> str:
    """Exécute une commande git dans le dépôt du projet et renvoie sa sortie nettoyée (ou chaîne vide)."""
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(_ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return res.stdout.strip() if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_github_repo(remote_url: str) -> Optional[str]:
    """Extrait `owner/repo` d'une URL Git SSH (`git@github.com:owner/repo.git`) ou HTTPS (`https://github.com/owner/repo`)."""
    raw = (remote_url or "").strip()
    if not raw:
        return None
    # Format SSH : git@github.com:owner/repo.git ou ssh://git@github.com/owner/repo.git
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", raw)
    if m:
        return m.group(1)
    # Format court déjà "owner/repo"
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        return raw.removesuffix(".git")
    return None


def detect_github_repo(fallback: str = DEFAULT_GITHUB_REPO) -> str:
    """Récupère le nom du dépôt GitHub (`owner/repo`) depuis la configuration Git locale."""
    remote_url = _git("config", "--get", "remote.origin.url")
    return parse_github_repo(remote_url) or fallback


def local_version_info() -> dict:
    """Lit la branche et le commit courants du dépôt Git local."""
    repo = detect_github_repo()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "main"
    if branch == "HEAD":
        branch = "main"
    sha = _git("rev-parse", "HEAD")
    short = sha[:7] if sha else ""
    log_line = _git("log", "-1", "--format=%s%n%cI")
    lines = log_line.splitlines() if log_line else []
    message = lines[0].strip() if lines else ""
    date = lines[1].strip() if len(lines) > 1 else ""
    tag = _git("describe", "--tags", "--exact-match")
    return {
        "repo": repo,
        "repo_url": f"https://github.com/{repo}",
        "branch": branch,
        "local_sha": sha,
        "local_short": short,
        "local_message": message,
        "local_date": date,
        "local_tag": tag,
    }


def fetch_github_branch_info(repo: str, branch: str = "main", timeout: float = 3.5) -> dict:
    """Interroge l'API publique GitHub pour connaître le dernier commit de la branche du dépôt."""
    safe_branch = urllib.parse.quote(branch, safe="")
    url = f"https://api.github.com/repos/{repo}/commits/{safe_branch}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "SmartHome-VersionChecker/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read() or b"{}")
        sha = str(data.get("sha") or "").strip()
        commit = data.get("commit") or {}
        msg = str(commit.get("message") or "").splitlines()[0].strip() if commit.get("message") else ""
        committer = commit.get("committer") or commit.get("author") or {}
        date = str(committer.get("date") or "").strip()
        if sha:
            return {
                "remote_sha": sha,
                "remote_short": sha[:7],
                "remote_message": msg,
                "remote_date": date,
                "source": "github_api",
                "error": "",
            }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        api_err = str(exc)
    else:
        api_err = "Réponse GitHub vide."

    # Repli sur `git ls-remote origin` (ex. dépôt privé en SSH ou hors accès à api.github.com)
    ls_out = _git("ls-remote", "origin", f"refs/heads/{branch}", timeout=timeout)
    if ls_out:
        sha = ls_out.split()[0].strip()
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return {
                "remote_sha": sha,
                "remote_short": sha[:7],
                "remote_message": "",
                "remote_date": "",
                "source": "git_ls_remote",
                "error": "",
            }

    return {
        "remote_sha": "",
        "remote_short": "",
        "remote_message": "",
        "remote_date": "",
        "source": "none",
        "error": f"Impossible de vérifier le dépôt GitHub ({repo}) : {api_err}",
    }


def _determine_status(local_sha: str, remote_sha: str) -> str:
    """Détermine la relation entre le commit local et le commit GitHub."""
    if not local_sha or not remote_sha:
        return "unknown"
    if local_sha == remote_sha:
        return "up_to_date"
    # Vérifie si le commit local est un ancêtre du commit distant (retard par rapport à GitHub)
    try:
        res_behind = subprocess.run(
            ["git", "merge-base", "--is-ancestor", local_sha, remote_sha],
            cwd=str(_ROOT_DIR),
            capture_output=True,
            timeout=2.0,
            stdin=subprocess.DEVNULL,
        )
        if res_behind.returncode == 0:
            return "behind"
    except (OSError, subprocess.SubprocessError):
        pass
    return "different"


def check_version(force: bool = False, timeout: float = 3.5) -> dict:
    """Compare la version locale avec celle du dépôt GitHub et met le résultat en cache."""
    now = time.monotonic()
    if not force and _cache["data"] is not None and (now - _cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _cache["data"]

    local = local_version_info()
    remote = fetch_github_branch_info(local["repo"], local["branch"], timeout=timeout)
    local_sha = local["local_sha"]
    remote_sha = remote["remote_sha"]
    difference = bool(local_sha and remote_sha and local_sha != remote_sha)
    status = _determine_status(local_sha, remote_sha)

    result = {
        **local,
        **remote,
        "difference": difference,
        "update_available": difference,
        "status": status,
        "checked_at": int(time.time()),
    }
    _cache["timestamp"] = now
    _cache["data"] = result
    return result


def pull_update() -> dict:
    """Tente de récupérer et d'appliquer les dernières modifications depuis `origin` (`git pull --ff-only`)."""
    local = local_version_info()
    branch = local["branch"]
    try:
        fetch_res = subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=str(_ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=15.0,
            stdin=subprocess.DEVNULL,
        )
        pull_res = subprocess.run(
            ["git", "pull", "--ff-only", "origin", branch],
            cwd=str(_ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=15.0,
            stdin=subprocess.DEVNULL,
        )
        output = (pull_res.stdout or pull_res.stderr or fetch_res.stderr or "").strip()
        ok = pull_res.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        ok = False
        output = str(exc)

    fresh = check_version(force=True)
    return {
        "ok": ok,
        "output": output or ("Mise à jour appliquée." if ok else "Mise à jour Git non appliquée."),
        "version": fresh,
    }


if __name__ == "__main__":
    info = check_version(force=True)
    print(f"📦 Dépôt GitHub   : {info['repo']} ({info['repo_url']})")
    print(f"🌿 Branche        : {info['branch']}")
    print(f"💻 Version locale : {info['local_short'] or 'inconnue'} — {info['local_message'] or '—'}")
    print(f"☁️  Version GitHub : {info['remote_short'] or 'inconnue'} — {info['remote_message'] or info['error'] or '—'}")
    if info["update_available"]:
        print(f"⬆️  Différence détectée (statut : {info['status']}) — pastille de mise à jour active.")
    else:
        print("✅ Version locale identique au dépôt GitHub.")
