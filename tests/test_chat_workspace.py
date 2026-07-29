from __future__ import annotations

import base64
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from rich.console import Console

from qortium_cli.features import chat, social
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import get_member_groups
from qortium_cli.storage import load_chat_settings
from qortium_cli.ui import menu


class ChatWorkspaceTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
            account=AccountSettings(
                name="alice",
                account_address="Qalice1111111111111111111111111111",
                public_key="public-key",
                private_key="private-key",
                api_key="api-key",
            ),
            chat=ChatSettings(tx_group_id=7),
            debug=False,
        )

    def test_actions_make_room_switching_a_primary_choice(self) -> None:
        actions = chat.chat_actions((), ())

        self.assertEqual(
            [(action.key, action.label) for action in actions],
            [
                ("1", "Send message"),
                ("2", "Switch room"),
                ("3", "Reply to message"),
                ("4", "React to message"),
                ("5", "Edit my message"),
                ("6", "Refresh conversation"),
                ("7", "Manage groups"),
                ("8", "Change chat fee"),
            ],
        )

    def test_member_rooms_are_named_deduplicated_and_sorted(self) -> None:
        rooms = chat._member_rooms(
            [
                {"groupId": 9, "groupName": "Zeta"},
                {"groupId": 7, "groupName": "Builders"},
                {"groupId": 9, "groupName": "Zeta Updated"},
                {"groupId": 0, "groupName": "Public"},
                {"groupId": "bad", "groupName": "Ignored"},
            ]
        )

        self.assertEqual(
            [(room.group_id, room.name) for room in rooms],
            [(7, "Builders"), (9, "Zeta Updated")],
        )

    def test_switch_room_persists_selected_joined_group(self) -> None:
        with TemporaryDirectory() as tmp:
            ctx = self._context(Path(tmp))
            rooms = (chat.ChatRoom(7, "Builders"), chat.ChatRoom(9, "Artists"))
            with (
                patch.object(chat, "render_header"),
                patch.object(chat, "render_options"),
                patch.object(chat, "read_menu_choice", return_value="3"),
            ):
                chat._switch_room(ctx, rooms)

            self.assertEqual(ctx.chat.tx_group_id, 9)
            self.assertEqual(load_chat_settings(Path(tmp)).tx_group_id, 9)

    def test_chat_and_groups_opens_conversation_without_intermediate_menu(self) -> None:
        with TemporaryDirectory() as tmp:
            ctx = self._context(Path(tmp))
            with patch(
                "qortium_cli.features.chat.open_chat_workspace"
            ) as open_workspace:
                social.open_social_hub(ctx)

        open_workspace.assert_called_once_with(ctx)

    def test_workspace_stacks_cleanly_at_sixty_columns(self) -> None:
        output = StringIO()
        narrow_console = Console(
            file=output,
            width=60,
            height=32,
            color_system=None,
            highlight=False,
        )
        encoded = base64.b64encode(b"Hello from the builders room").decode("ascii")
        state = chat.ChatWorkspaceState(
            room=chat.ChatRoom(7, "Builders"),
            groups=(chat.ChatRoom(7, "Builders"),),
            messages=(
                {
                    "timestamp": 1_800_000_000_000,
                    "sender": "Qalice1111111111111111111111111111",
                    "senderName": "Alice",
                    "signature": "signature-1",
                    "data": encoded,
                    "encoding": "BASE64",
                    "isText": True,
                    "isEncrypted": False,
                },
            ),
        )

        with TemporaryDirectory() as tmp:
            with (
                patch.object(chat, "console", narrow_console),
                patch.object(menu, "console", narrow_console),
                patch.object(menu, "clear_screen"),
            ):
                chat.render_chat_workspace(self._context(Path(tmp)), state)

        rendered = output.getvalue()
        self.assertIn("ACTIVE CONVERSATION", rendered)
        self.assertIn("Builders", rendered)
        self.assertIn("TIMELINE", rendered)
        self.assertIn("Hello from the builders room", rendered)
        self.assertIn("Switch room", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))

    def test_workspace_places_context_and_quick_keys_side_by_side_when_wide(self) -> None:
        output = StringIO()
        wide_console = Console(
            file=output,
            width=120,
            height=36,
            color_system=None,
            highlight=False,
        )
        state = chat.ChatWorkspaceState(
            room=chat.ChatRoom(0, "General Chat"),
            groups=(),
            messages=(),
        )

        with TemporaryDirectory() as tmp:
            with (
                patch.object(chat, "console", wide_console),
                patch.object(menu, "console", wide_console),
                patch.object(menu, "clear_screen"),
            ):
                chat.render_chat_workspace(self._context(Path(tmp)), state)

        rendered = output.getvalue()
        context_title = next(
            line for line in rendered.splitlines() if "ACTIVE CONVERSATION" in line
        )
        self.assertIn("QUICK KEYS", context_title)
        self.assertTrue(all(len(line) <= 120 for line in rendered.splitlines()))


class ChatGroupServiceTests(TestCase):
    def test_member_group_lookup_uses_current_account_address(self) -> None:
        with TemporaryDirectory() as tmp:
            ctx = ChatWorkspaceTests._context(Path(tmp))
            response = MagicMock()
            response.json.return_value = [
                {"groupId": 7, "groupName": "Builders"},
                "not-a-group",
            ]
            session = MagicMock()
            session.get.return_value = response

            groups = get_member_groups(ctx, ctx.account.account_address, session)

        self.assertEqual(groups, [{"groupId": 7, "groupName": "Builders"}])
        session.get.assert_called_once_with(
            "http://127.0.0.1:24891/groups/member/"
            "Qalice1111111111111111111111111111",
            timeout=5,
        )
        response.raise_for_status.assert_called_once_with()
