from __future__ import annotations

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from rich.console import Console

from qortium_cli.features import node
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.ui import menu


class NodeHubTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
            account=AccountSettings(
                name="alice",
                account_address="Qexample",
                api_key="local-api-key",
            ),
            chat=ChatSettings(),
        )

    def test_actions_combine_node_and_minting_workflows(self) -> None:
        actions = node.node_actions()

        self.assertEqual(
            [(action.key, action.label) for action in actions],
            [
                ("1", "Refresh status"),
                ("2", "View loaded minting accounts"),
                ("3", "Set up self-share"),
                ("4", "Add existing minting key"),
                ("5", "View node settings"),
                ("6", "Bootstrap node"),
                ("7", "Restart node"),
                ("8", "Stop node"),
            ],
        )
        labels = {action.label for action in actions}
        self.assertNotIn("Node dashboard", labels)
        self.assertNotIn("Minting status", labels)
        self.assertTrue(all(action.destructive for action in actions[-3:]))

    def test_workspace_stacks_status_and_actions_at_sixty_columns(self) -> None:
        output = StringIO()
        narrow_console = Console(
            file=output,
            width=60,
            color_system=None,
            highlight=False,
        )
        state = node.NodeMintingState(
            snapshot={
                "info": {
                    "uptime": 90_000,
                    "buildVersion": "Qortium Core 5.0.0",
                },
                "status": {
                    "height": 123456,
                    "syncPercent": 100,
                    "isSynchronizing": False,
                    "isMintingPossible": True,
                    "numberOfConnections": 8,
                    "numberOfDataConnections": 3,
                },
            },
            loaded_minting_accounts=1,
        )

        with TemporaryDirectory() as tmp:
            with (
                patch.object(node, "console", narrow_console),
                patch.object(menu, "console", narrow_console),
                patch.object(menu, "clear_screen"),
            ):
                node.render_node_hub(self._context(Path(tmp)), state)

        rendered = output.getvalue()
        self.assertIn("NODE STATUS", rendered)
        self.assertIn("MINTING STATUS", rendered)
        self.assertIn("MINTING", rendered)
        self.assertNotIn("MINTING POSSIBLE", rendered)
        self.assertIn("View loaded minting accounts", rendered)
        self.assertIn("Bootstrap node", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))

    def test_workspace_uses_two_status_columns_when_wide(self) -> None:
        output = StringIO()
        wide_console = Console(
            file=output,
            width=120,
            color_system=None,
            highlight=False,
        )
        state = node.NodeMintingState(
            snapshot={
                "info": {"uptime": 1_000, "buildVersion": "5.0.0"},
                "status": {
                    "height": 1,
                    "isSynchronizing": True,
                    "isMintingPossible": False,
                },
            },
            loaded_minting_accounts=0,
        )

        with TemporaryDirectory() as tmp:
            with (
                patch.object(node, "console", wide_console),
                patch.object(menu, "console", wide_console),
                patch.object(menu, "clear_screen"),
            ):
                node.render_node_hub(self._context(Path(tmp)), state)

        title_line = next(
            line for line in output.getvalue().splitlines() if "NODE STATUS" in line
        )
        self.assertIn("MINTING STATUS", title_line)
        self.assertTrue(all(len(line) <= 120 for line in output.getvalue().splitlines()))
