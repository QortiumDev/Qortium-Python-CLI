import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from textual.widgets import Button, Input, OptionList, Static

from qortium_cli.features.chat_backend import (
    ChatConversation,
    ChatReadState,
    ConversationInbox,
)
from qortium_cli.features.chat_tui import (
    ChatHelpScreen,
    ChatWorkspaceApp,
    ReactionPickerScreen,
)
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings


def encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def context(settings_dir: Path) -> AppContext:
    return AppContext(
        settings_dir=settings_dir,
        endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
        account=AccountSettings(
            name="Alice",
            account_address="Qalice",
            public_key="public-key",
            private_key="private-key",
            api_key="api-key",
        ),
        chat=ChatSettings(tx_group_id=7),
        debug=False,
    )


class FakeGateway:
    def __init__(self, messages):
        self.messages = tuple(messages)
        self.sent = []

    def list_conversations(self):
        return ConversationInbox(())

    def load_messages(self, conversation):
        return self.messages

    def send_text(self, conversation, text, **kwargs):
        self.sent.append((conversation, text, kwargs))
        return {"signature": "sent"}

    def send_payload(self, conversation, payload, **kwargs):
        self.sent.append((conversation, payload, kwargs))
        return {"signature": "sent"}

    def resolve_direct_recipient(self, value):
        return ChatConversation(
            key="direct:Qbob",
            kind="direct",
            title=value,
            address="Qbob",
        )


class ChatWorkspaceAppTests(IsolatedAsyncioTestCase):
    def _fixture(self, settings_dir: Path):
        direct = ChatConversation(
            key="direct:Qbob",
            kind="direct",
            title="Bob",
            address="Qbob",
            timestamp=200,
            preview="Direct hello",
        )
        group = ChatConversation(
            key="group:7",
            kind="group",
            title="Development",
            group_id=7,
            member_count=35,
            timestamp=100,
            preview="Group hello",
        )
        messages = (
            {
                "timestamp": 100,
                "sender": "Qbob",
                "senderName": "Bob",
                "signature": "message-signature",
                "data": encoded("Hello from Bob"),
                "encoding": "BASE64",
                "isText": True,
                "isEncrypted": False,
            },
        )
        gateway = FakeGateway(messages)
        app = ChatWorkspaceApp(
            context(settings_dir),
            gateway,
            ConversationInbox((direct, group)),
            group,
            messages,
            ChatReadState(),
            refresh_seconds=0,
            show_first_use_help=False,
        )
        return app, gateway

    async def test_workspace_mounts_with_inbox_timeline_and_composer(self) -> None:
        with TemporaryDirectory() as tmp:
            app, _ = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                self.assertTrue(app.query_one("#sidebar").display)
                self.assertEqual(app.query_one("#direct-list", OptionList).option_count, 1)
                self.assertEqual(app.query_one("#group-list", OptionList).option_count, 1)
                self.assertEqual(app.query_one("#timeline", OptionList).option_count, 1)
                self.assertTrue(app.query_one("#composer", Input).has_focus)

    async def test_focused_composer_keeps_typed_text_visible(self) -> None:
        with TemporaryDirectory() as tmp:
            app, _ = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.press(*tuple("visible draft"))
                await pilot.pause()

                composer = app.query_one("#composer", Input)
                self.assertEqual(composer.value, "visible draft")
                self.assertEqual(composer.styles.color.hex, "#FFFFFF")
                self.assertEqual(composer.styles.outline.top[0], "")
                screenshot = app.export_screenshot().lower().replace("&#160;", " ")
                self.assertIn("visible draft", screenshot)

    async def test_narrow_layout_turns_conversations_into_a_toggleable_view(self) -> None:
        with TemporaryDirectory() as tmp:
            app, _ = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.resize_terminal(60, 24)
                await pilot.pause()
                self.assertFalse(app.query_one("#sidebar").display)

                await pilot.press("f2")
                await pilot.pause()
                self.assertTrue(app.query_one("#sidebar").display)

                await pilot.press("f4")
                await pilot.pause()
                self.assertFalse(app.query_one("#sidebar").display)

    async def test_reply_flow_uses_selected_message_without_leaving_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            app, gateway = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.press("f3", "r", "f4")
                await pilot.press("H", "i", "enter")
                await pilot.pause(0.2)

                self.assertEqual(len(gateway.sent), 1)
                _, text, kwargs = gateway.sent[0]
                self.assertEqual(text, "Hi")
                self.assertEqual(kwargs["replied_to"], "message-signature")

    async def test_contextual_numbers_react_and_edit_selected_message(self) -> None:
        with TemporaryDirectory() as tmp:
            app, gateway = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.press("f3", "2")
                await pilot.pause()
                self.assertIsInstance(app.screen, ReactionPickerScreen)
                self.assertEqual(gateway.sent, [])
                self.assertIn(
                    "+1",
                    app.screen.query_one("#reaction-1", Button).label.plain,
                )

                await pilot.click("#reaction-1")
                await pilot.pause(0.2)

                self.assertEqual(len(gateway.sent), 1)
                _, payload, kwargs = gateway.sent[0]
                self.assertIn('"type":"reaction"', payload)
                self.assertEqual(kwargs["chat_reference"], "message-signature")

                await pilot.press("f3", "3")
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#composer", Input).value,
                    "",
                    "Another user's message must not enter edit mode.",
                )

    async def test_sidebar_numbers_switch_conversations_only_when_sidebar_is_focused(self) -> None:
        with TemporaryDirectory() as tmp:
            app, _ = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.press("f2", "1")
                await pilot.pause(0.2)

                self.assertIsNotNone(app.conversation)
                self.assertEqual(app.conversation.key, "direct:Qbob")

                await pilot.press("f4", "1")
                await pilot.pause()
                self.assertEqual(app.query_one("#composer", Input).value, "1")

    async def test_footer_teaches_controls_for_the_active_pane(self) -> None:
        with TemporaryDirectory() as tmp:
            app, _ = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                footer = app.query_one("#keybar", Static)
                self.assertIn("COMPOSER ACTIVE", footer.render().plain)
                self.assertIn("EXIT CHAT: Ctrl+Q", footer.render().plain)

                await pilot.press("f3")
                await pilot.pause()
                self.assertIn("MESSAGES ACTIVE", footer.render().plain)
                self.assertIn("1 Reply", footer.render().plain)

                await pilot.press("f2")
                await pilot.pause()
                self.assertIn("GROUPS ACTIVE", footer.render().plain)
                self.assertIn("Enter Open", footer.render().plain)

    async def test_help_is_a_real_dialog_with_clear_exit_instructions(self) -> None:
        with TemporaryDirectory() as tmp:
            app, _ = self._fixture(Path(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.press("f1")
                await pilot.pause()

                self.assertIsInstance(app.screen, ChatHelpScreen)
                exit_note = app.screen.query_one("#help-exit-note", Static)
                self.assertIn("EXIT CHAT ANYTIME", exit_note.render().plain)
                self.assertIn("/back", exit_note.render().plain)

                await pilot.press("escape")
                await pilot.pause()
                self.assertNotIsInstance(app.screen, ChatHelpScreen)

    async def test_first_use_help_opens_once_and_persists_that_it_was_seen(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            app, _ = self._fixture(settings_dir)
            app.show_first_use_help = True
            async with app.run_test(size=(60, 24)) as pilot:
                await pilot.pause()
                self.assertIsInstance(app.screen, ChatHelpScreen)
                self.assertTrue(app.read_state.help_seen)

                await pilot.press("escape")
                await pilot.pause()

            app_again, _ = self._fixture(settings_dir)
            app_again.read_state.help_seen = True
            app_again.show_first_use_help = True
            async with app_again.run_test(size=(60, 24)) as pilot:
                await pilot.pause()
                self.assertNotIsInstance(app_again.screen, ChatHelpScreen)
