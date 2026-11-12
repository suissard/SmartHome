#!/usr/bin/env python3
"""Tests de [CREATE_COMMAND] : droits réservés aux superadmins, consigne envoyée à l'agent, lancement en arrière-plan."""

import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.modules.create_command import CreateCommandAction, agent_directory, build_command, build_prompt
from actions.registry import get_command_by_tag
from core.config import Settings
from core.users import User, admin_user, local_user, tool_policy


class TestSuperadminOnly(unittest.TestCase):
    def setUp(self):
        self.s = Settings(MCP_CLIENT_ENABLED=False)

    def test_reserved_to_superadmins(self):
        superadmin = User("pb_s", "Sam", "admin", superadmin=True)
        self.assertTrue(tool_policy(superadmin, self.s).allows("create_command", "confirm"))
        # Rôle inconnu de AUTH_ROLE_TOOLS : le superadmin reçoit les droits administrateur
        self.assertTrue(tool_policy(User("pb_t", "T", "autre", superadmin=True), self.s).allows("create_command", "confirm"))
        for user in (User("pb_a", "Admin", "admin"), User("pb_m", "Marie", "member"), admin_user(self.s), local_user(self.s)):
            with self.subTest(user=user.name):
                policy = tool_policy(user, self.s)
                self.assertFalse(policy.allows("create_command", "confirm"))
                self.assertTrue(policy.allows("volume", "safe"))

    def test_hidden_from_tag_prompt(self):
        from actions.manager import ActionManager
        manager = ActionManager()
        member = tool_policy(User("pb_m", "Marie", "member"), self.s)
        self.assertNotIn("[CREATE_COMMAND", manager.build_dynamic_system_prompt("Base.", policy=member))
        superadmin = tool_policy(User("pb_s", "Sam", "admin", superadmin=True), self.s)
        self.assertIn("[CREATE_COMMAND", manager.build_dynamic_system_prompt("Base.", policy=superadmin))

    def test_mcp_execute_action_refused(self):
        import mcp_server
        self.assertIn("réservée", mcp_server.execute_action("CREATE_COMMAND", "test"))


class TestAgentLaunch(unittest.TestCase):
    def test_registered_and_confirmed(self):
        action = get_command_by_tag("CREATE_COMMAND")
        self.assertIsNotNone(action)
        self.assertEqual(action.danger, "confirm")

    def test_prompt_and_command(self):
        s = Settings(MCP_CLIENT_ENABLED=False, ACTIONS_AGENT_MODEL="gemini-4-argon-high", ACTIONS_AGENT_TIMEOUT=600)
        prompt = build_prompt("Vider la corbeille", s)
        self.assertIn("Vider la corbeille", prompt)
        self.assertIn("Guide : créer une commande personnalisée", prompt)
        cmd = build_command(prompt, s)
        self.assertEqual(cmd[:2], ["agy", "--dangerously-skip-permissions"])
        self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-4-argon-high")
        self.assertEqual(cmd[cmd.index("--add-dir") + 1], str(ROOT_DIR))
        self.assertEqual(cmd[cmd.index("--print-timeout") + 1], "600s")
        self.assertEqual(cmd[-2:], ["-p", prompt])

    def test_launch_runs_agent_in_directory(self):
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as logs:
            # Faux agent (Python, pour Linux comme Windows) : écrit son répertoire et ses arguments dans le journal
            script = Path(logs) / "fake_agent.py"
            script.write_text("import sys\nfrom pathlib import Path\nprint(Path.cwd().resolve())\nprint(' '.join(sys.argv[1:]))\n")
            quote = (lambda x: x) if sys.platform == "win32" else shlex.quote
            s = Settings(MCP_CLIENT_ENABLED=False, ACTIONS_AGENT_COMMAND=f"{quote(sys.executable)} {quote(str(script))}",
                         ACTIONS_AGENT_DIR=work, ACTIONS_AGENT_LOG_DIR=logs, ACTIONS_AGENT_MODEL="m1")
            self.assertEqual(agent_directory(s), Path(work))
            with patch("actions.modules.create_command._notify") as notify:
                code, out, err = CreateCommandAction().launch("Une commande de test", s)
                self.assertEqual(code, 0, err)
                for _ in range(100):
                    if notify.called:
                        break
                    time.sleep(0.05)
            notify.assert_called_once()
            log = next(Path(logs).glob("create_command_*.log")).read_text(encoding="utf-8")
            self.assertIn(str(Path(work).resolve()), log)
            self.assertIn("--model m1", log)
            self.assertIn("Une commande de test", log)

    def test_launch_rejects_bad_input(self):
        s = Settings(MCP_CLIENT_ENABLED=False, ACTIONS_AGENT_MAX_REQUEST_CHARS=10)
        action = CreateCommandAction()
        self.assertEqual(action.launch("", s)[0], 1)
        self.assertEqual(action.launch("x" * 11, s)[0], 1)
        missing = Settings(MCP_CLIENT_ENABLED=False, ACTIONS_AGENT_DIR="/nexiste/pas")
        self.assertEqual(action.launch("ok", missing)[0], 1)
        unknown = Settings(MCP_CLIENT_ENABLED=False, ACTIONS_AGENT_COMMAND="agent-introuvable-xyz")
        with tempfile.TemporaryDirectory() as logs:
            unknown = Settings(**{**unknown.model_dump(), "ACTIONS_AGENT_LOG_DIR": logs})
            code, _, err = action.launch("ok", unknown)
        self.assertEqual(code, 1)
        self.assertIn("agent-introuvable-xyz", err)

    def test_unique_logs_and_active_tracking(self):
        from actions.modules.create_command import active_agent_count, stop_active_agents
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as logs:
            script = Path(logs) / "slow_agent.py"
            script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
            quote = (lambda x: x) if sys.platform == "win32" else shlex.quote
            s = Settings(MCP_CLIENT_ENABLED=False, ACTIONS_AGENT_COMMAND=f"{quote(sys.executable)} {quote(str(script))}",
                         ACTIONS_AGENT_DIR=work, ACTIONS_AGENT_LOG_DIR=logs, ACTIONS_AGENT_MODEL="m1")
            with patch("actions.modules.create_command._notify"):
                code1, _, err1 = CreateCommandAction().launch("commande un", s)
                code2, _, err2 = CreateCommandAction().launch("commande deux", s)
                self.assertEqual((code1, code2), (0, 0), f"{err1} / {err2}")
                log_files = list(Path(logs).glob("create_command_*.log"))
                self.assertEqual(len(log_files), 2)
                self.assertGreaterEqual(active_agent_count(), 2)
                stop_active_agents()
                for _ in range(50):
                    if active_agent_count() == 0:
                        break
                    time.sleep(0.05)
                self.assertEqual(active_agent_count(), 0)


if __name__ == "__main__":
    unittest.main()
