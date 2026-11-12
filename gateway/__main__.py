"""
Serveur SmartHome sans micro : `python -m gateway`.
Expose l'assistant (LLM, outils, actions sur cette machine, voix synthétisée pour le client) via la passerelle.
"""

import sys
from pathlib import Path

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.assistant import AssistantCore
from core.config import get_settings
from core.pairing import print_pairing
from core.pocketbase import ensure_running
from core.profiles import warn_shadowed_profile
from core.restart import restart_if_requested
from core.security import require_token_for_host
from gateway.app import build_server
from llm.providers import LLM_PROVIDERS


def main():
    s = get_settings()
    require_token_for_host(s.GATEWAY_HOST, s.GATEWAY_AUTH_TOKEN, "GATEWAY", "GATEWAY_AUTH_TOKEN")

    hub = None
    if s.MCP_CLIENT_ENABLED:
        from core.mcp_hub import get_mcp_hub
        hub = get_mcp_hub()
        hub.connect_all()

    # Comptes de la PWA (AUTH_PROVIDER=pocketbase) : annuaire lancé avec la passerelle s'il ne tourne pas déjà
    pocketbase = ensure_running(s)
    core = AssistantCore(s)
    tools = core.tools.all()
    auth = "jeton requis" if s.GATEWAY_AUTH_TOKEN else "sans jeton (loopback uniquement)"
    print("🟢 Passerelle SmartHome (sans micro)")
    warn_shadowed_profile()
    print(f"  • Cerveau LLM : {LLM_PROVIDERS.get(s.LLM_PROVIDER).describe(s)}")
    print(f"  • Outils      : {len(tools)} ({sum(t.danger == 'confirm' for t in tools)} avec confirmation)")
    print(f"  • Écoute      : ws://{s.GATEWAY_HOST}:{s.GATEWAY_PORT}/ws — {auth}")
    print_pairing(s)
    print()
    core.start_scheduler()
    try:
        build_server(core, s).run()
    except KeyboardInterrupt:
        pass
    finally:
        core.stop_scheduler()
        if hub:
            hub.disconnect_all()
        if pocketbase:
            pocketbase.stop()
    restart_if_requested()


if __name__ == "__main__":
    main()
