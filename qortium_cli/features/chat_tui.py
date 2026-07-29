"""Responsive full-screen terminal chat workspace."""

from __future__ import annotations

import datetime
import hashlib
import sys
from dataclasses import replace
from typing import Any

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from qortium_cli.chat_format import (
    DEFAULT_REACTION_OPTIONS,
    build_chat_message_text,
    build_message_reaction_index,
    build_message_threads,
    build_reaction_message_text,
    decode_chat_message,
    terminal_reaction,
)
from qortium_cli.constants import APP_VERSION
from qortium_cli.features.chat_backend import (
    ChatConversation,
    ChatGateway,
    ChatReadState,
    ConversationInbox,
    load_chat_read_state,
    save_chat_read_state,
)
from qortium_cli.models import AppContext
from qortium_cli.storage import write_chat_settings
from qortium_cli.ui.theme import CHAT_USER_HEX
from qortium_cli.ui.widgets import spinner

REACTION_KEYS = tuple(DEFAULT_REACTION_OPTIONS[:6])
REACTION_DESCRIPTIONS = (
    "Agree",
    "Love",
    "Laugh",
    "Surprised",
    "Sad",
    "Thanks",
)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _time_label(timestamp: Any) -> str:
    value = _integer(timestamp)
    if value <= 0:
        return ""
    try:
        moment = datetime.datetime.fromtimestamp(value / 1000)
        now = datetime.datetime.now()
        if moment.date() == now.date():
            return moment.strftime("%H:%M")
        if moment.year == now.year:
            return moment.strftime("%b %d")
        return moment.strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def _sender_label(message: dict[str, Any]) -> str:
    name = str(message.get("senderName") or "").strip()
    if name:
        return name
    address = str(message.get("sender") or "").strip()
    return f"{address[:8]}…{address[-5:]}" if len(address) > 16 else address or "Unknown"


def _sender_color(message: dict[str, Any]) -> str:
    identity = str(message.get("sender") or _sender_label(message)).casefold()
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return CHAT_USER_HEX[int.from_bytes(digest[:2], "big") % len(CHAT_USER_HEX)]


def _signature(message: dict[str, Any]) -> str:
    return str(message.get("signature") or "").strip()


def _select_initial_conversation(
    ctx: AppContext,
    inbox: ConversationInbox,
    read_state: ChatReadState,
) -> ChatConversation | None:
    selected = inbox.by_key(read_state.active_key)
    if selected is not None:
        return selected
    selected = inbox.by_key(f"group:{int(ctx.chat.tx_group_id)}")
    return selected or (inbox.conversations[0] if inbox.conversations else None)


class ChatHelpScreen(ModalScreen[None]):
    """A workflow-oriented guide to the chat workspace."""

    BINDINGS = [
        Binding("escape", "close_help", "Close", show=False),
        Binding("ctrl+q", "exit_chat", "Exit Chat", show=False),
    ]

    CSS = """
    ChatHelpScreen {
        align: center middle;
        background: #07080db8;
    }

    #help-dialog {
        width: 82;
        max-width: 95%;
        height: auto;
        max-height: 95%;
        padding: 1 2;
        background: #151720;
        border: heavy #8d6bff;
    }

    #help-title {
        height: 2;
        color: #ffffff;
        text-style: bold;
        content-align: center middle;
    }

    #help-subtitle {
        height: 2;
        color: #b9b1ca;
        content-align: center top;
    }

    #help-body {
        height: auto;
        padding: 1 1;
        background: #101218;
        color: #e9e7f2;
    }

    #help-exit-note {
        height: 3;
        padding: 1 1 0 1;
        color: #72e7ff;
        text-style: bold;
        content-align: center middle;
    }

    #help-buttons {
        height: 3;
        align: center middle;
    }

    #help-buttons Button {
        width: 18;
        min-width: 14;
        height: 3;
        margin: 0 1;
        border: none;
        text-style: bold;
    }

    #close-help {
        background: #6844a3;
        color: #ffffff;
    }

    #exit-chat {
        background: #343746;
        color: #ffffff;
    }

    ChatHelpScreen.narrow #help-dialog {
        width: 96%;
        padding: 0 1;
    }

    ChatHelpScreen.short #help-subtitle {
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        body = Text()
        body.append("1  GROUPS", style="bold #72e7ff")
        body.append("\n   Press F2, then use Up/Down and Enter. Numbers 1-9 switch quickly.\n\n")
        body.append("2  MESSAGES", style="bold #cf8cff")
        body.append(
            "\n   Press F3, select a message, then: "
            "1 Reply  /  2 React  /  3 Edit  /  4 Copy.\n\n"
        )
        body.append("3  COMPOSER", style="bold #80ef9d")
        body.append(
            "\n   Press F4, type your message, and press Enter to send. "
            "Use /help for this guide or /back to leave chat.\n\n"
        )
        body.append("OTHER", style="bold #f2c66d")
        body.append(
            "\n   Ctrl+N starts a direct chat. Ctrl+R refreshes. "
            "Escape cancels reply, edit, reaction, or new-chat mode."
        )

        with Vertical(id="help-dialog"):
            yield Static("HOW TO USE QORTIUM CHAT", id="help-title")
            yield Static(
                "Move between three panes; the bright highlight shows which one is active.",
                id="help-subtitle",
            )
            yield Static(body, id="help-body")
            yield Static(
                "EXIT CHAT ANYTIME:  Ctrl+Q   |   From the composer: /back",
                id="help-exit-note",
            )
            with Horizontal(id="help-buttons"):
                yield Button("GOT IT", id="close-help", variant="primary")
                yield Button("EXIT CHAT", id="exit-chat")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 72, "narrow")
        self.set_class(self.size.height < 25, "short")
        self.query_one("#close-help", Button).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 72, "narrow")
        self.set_class(event.size.height < 25, "short")

    @on(Button.Pressed)
    def _help_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit-chat":
            self.action_exit_chat()
        else:
            self.action_close_help()

    def action_close_help(self) -> None:
        self.dismiss(None)

    def action_exit_chat(self) -> None:
        self.app.action_back()


class ReactionPickerScreen(ModalScreen[str | None]):
    """A mouse- and keyboard-friendly terminal reaction picker."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    ReactionPickerScreen {
        align: center middle;
        background: #07080db8;
    }

    #reaction-dialog {
        width: 58;
        max-width: 94%;
        height: auto;
        padding: 1 2;
        background: #151720;
        border: heavy #8d6bff;
    }

    #reaction-title {
        height: 2;
        content-align: center middle;
        color: #ffffff;
        text-style: bold;
    }

    #reaction-subtitle {
        height: auto;
        margin-bottom: 1;
        color: #aaa4ba;
        text-align: center;
    }

    .reaction-row {
        height: 3;
    }

    .reaction-choice {
        width: 1fr;
        margin: 0 1 1 0;
        background: #282b39;
        color: #ffffff;
        border: tall #4e5368;
    }

    .reaction-choice:focus {
        background: #6844a3;
        border: tall #b88cff;
        text-style: bold;
    }

    #cancel-reaction {
        width: 100%;
        background: #343746;
        color: #ffffff;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="reaction-dialog"):
            yield Static("CHOOSE A REACTION", id="reaction-title")
            yield Static(
                "Stored compatibly on-chain; shown here as terminal-friendly text.",
                id="reaction-subtitle",
            )
            for row_start in range(0, len(REACTION_KEYS), 2):
                with Horizontal(classes="reaction-row"):
                    for index in range(row_start, min(row_start + 2, len(REACTION_KEYS))):
                        reaction = REACTION_KEYS[index]
                        yield Button(
                            f"[{index + 1}]  {terminal_reaction(reaction)}  {REACTION_DESCRIPTIONS[index]}",
                            id=f"reaction-{index + 1}",
                            classes="reaction-choice",
                        )
            yield Button("CANCEL", id="cancel-reaction")

    def on_mount(self) -> None:
        self.query_one("#reaction-1", Button).focus()

    @on(Button.Pressed)
    def _button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-reaction":
            self.dismiss(None)
            return
        if event.button.id and event.button.id.startswith("reaction-"):
            index = int(event.button.id.rsplit("-", 1)[1]) - 1
            self.dismiss(REACTION_KEYS[index])

    def on_key(self, event: events.Key) -> None:
        if event.key.isdigit():
            index = int(event.key) - 1
            if 0 <= index < len(REACTION_KEYS):
                self.dismiss(REACTION_KEYS[index])
                event.prevent_default()
                event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChatWorkspaceApp(App[str]):
    """A conversation-first Qortium chat client that lives entirely in the terminal."""

    TITLE = "Qortium Chat"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "back", "Exit Chat", show=False),
        Binding("ctrl+r", "refresh", "Refresh", show=False),
        Binding("ctrl+n", "new_direct", "New Direct", show=False),
        Binding("f2", "focus_rooms", "Groups", show=False),
        Binding("f3", "focus_timeline", "Timeline", show=False),
        Binding("f4", "focus_composer", "Message", show=False),
        Binding("f1", "help", "Help", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    CSS = """
    Screen {
        layout: vertical;
        background: #0b0c12;
        color: #e9e7f2;
        layers: base overlay;
    }

    #topbar {
        height: 2;
        padding: 0 1;
        content-align: left middle;
        background: #171923;
        border-bottom: solid #3a4050;
    }

    #workspace {
        height: 1fr;
        width: 100%;
    }

    #sidebar {
        width: 34;
        min-width: 24;
        height: 100%;
        background: #101218;
        border-right: solid #353949;
    }

    .section-title {
        height: 2;
        padding: 0 1;
        content-align: left middle;
        color: #d8c7ff;
        text-style: bold;
        background: #151720;
    }

    #direct-list {
        height: auto;
        min-height: 3;
        max-height: 35%;
    }

    #group-list {
        height: 1fr;
    }

    OptionList {
        background: #101218;
        color: #d9d7e2;
        border: none;
        padding: 0;
        scrollbar-color: #6f4ba5;
        scrollbar-color-hover: #9b6ee0;
        scrollbar-background: #101218;
    }

    OptionList:focus {
        border: none;
    }

    #direct-list:focus, #group-list:focus {
        outline: heavy #72e7ff;
        background: #151922;
    }

    OptionList > .option-list--option {
        padding: 0 1;
    }

    OptionList > .option-list--option-highlighted {
        background: #292637;
        color: #ffffff;
        text-style: bold;
    }

    #chat-pane {
        width: 1fr;
        height: 100%;
        background: #0b0c12;
    }

    #room-header {
        height: 4;
        padding: 0 2;
        content-align: left middle;
        background: #101218;
        border-bottom: solid #353949;
    }

    #timeline {
        height: 1fr;
        padding: 0 1;
        background: #0b0c12;
    }

    #timeline:focus {
        outline: heavy #cf8cff;
        background: #101019;
    }

    #timeline > .option-list--option {
        padding: 0 1;
    }

    #timeline > .option-list--option-highlighted {
        background: #252232;
        color: #ffffff;
        text-style: none;
    }

    #composer-row {
        height: 4;
        padding: 0 1;
        background: #151720;
        border-top: solid #353949;
    }

    #composer-row:focus-within {
        background: #19221f;
        border-top: solid #80ef9d;
    }

    #composer {
        width: 1fr;
        height: 3;
        border: none;
        background: #222532;
        color: #ffffff;
        padding: 0 1;
    }

    #composer:focus {
        border: none;
        background: #292d3d;
        color: #ffffff;
    }

    #send {
        width: 10;
        height: 3;
        min-width: 8;
        border: none;
        background: #6844a3;
        color: white;
        text-style: bold;
    }

    #send:hover {
        background: #8259c4;
    }

    #keybar {
        height: 2;
        padding: 0 1;
        content-align: left middle;
        background: #171923;
        color: #a9a4b8;
        border-top: solid #353949;
    }

    Screen.compact #sidebar {
        width: 27;
    }

    Screen.narrow #sidebar {
        display: none;
    }

    Screen.narrow.show-sidebar #sidebar {
        display: block;
        width: 100%;
        height: 100%;
        layer: overlay;
    }

    Screen.narrow.show-sidebar #chat-pane {
        display: none;
    }

    Screen.short #room-header {
        height: 3;
    }

    Screen.short #keybar {
        height: 1;
    }
    """

    def __init__(
        self,
        ctx: AppContext,
        gateway: ChatGateway,
        inbox: ConversationInbox,
        conversation: ChatConversation | None,
        messages: tuple[dict[str, Any], ...],
        read_state: ChatReadState,
        *,
        refresh_seconds: float = 5.0,
        show_first_use_help: bool = True,
    ) -> None:
        super().__init__()
        self.ctx = ctx
        self.gateway = gateway
        self.inbox = inbox
        self.conversation = conversation
        self.messages = messages
        self.read_state = read_state
        self.refresh_seconds = refresh_seconds
        self.show_first_use_help = show_first_use_help
        self._message_options: dict[str, Any] = {}
        self._room_numbers: dict[int, str] = {}
        self._sending = False
        self._reply_signature = ""
        self._edit_signature = ""
        self._edit_replied_to = ""
        self._reaction_signature = ""
        self._new_direct_mode = False
        self._loading_older = False
        self._history_exhausted: set[str] = set()
        self._last_status = "READY"

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Static("DIRECT", classes="section-title")
                yield OptionList(id="direct-list")
                yield Static("GROUPS", classes="section-title")
                yield OptionList(id="group-list")
            with Vertical(id="chat-pane"):
                yield Static(id="room-header")
                yield OptionList(id="timeline")
                with Horizontal(id="composer-row"):
                    yield Input(
                        placeholder="Write a message…",
                        id="composer",
                        select_on_focus=False,
                    )
                    yield Button("SEND", id="send", flat=True)
        yield Static(id="keybar")

    def on_mount(self) -> None:
        self._apply_responsive_classes(self.size.width, self.size.height)
        self._render_topbar()
        self._render_conversations()
        self._render_room_header()
        self._render_timeline()
        self._set_status("READY")
        self.query_one("#composer", Input).focus()
        if self.conversation is not None:
            self._mark_current_seen()
        if self.refresh_seconds > 0:
            self.set_interval(self.refresh_seconds, self.refresh_messages)
            self.set_interval(max(15.0, self.refresh_seconds * 3), self.refresh_inbox)
        if self.show_first_use_help and not self.read_state.help_seen:
            self.call_after_refresh(self.action_help)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_classes(event.size.width, event.size.height)
        self._render_topbar()
        self._render_conversations()
        self._render_room_header()

    def _apply_responsive_classes(self, width: int, height: int) -> None:
        self.screen.set_class(width < 104, "compact")
        self.screen.set_class(width < 72, "narrow")
        self.screen.set_class(height < 25, "short")
        if width >= 72:
            self.screen.remove_class("show-sidebar")

    def _render_topbar(self) -> None:
        width = self.size.width
        identity = self.ctx.account.name or self.ctx.account.account_address
        unlocked = bool(
            self.ctx.account.private_key
            and str(self.ctx.account.private_key).strip().lower() not in {"", "x"}
        )
        line = Text()
        line.append("QORTIUM CHAT", style="bold #f1edff")
        line.append(f"  v{APP_VERSION}", style="dim #9d96af")
        if width >= 72:
            line.append("    ")
            line.append(identity, style="bold #d8c7ff")
            line.append("  ")
            line.append("UNLOCKED" if unlocked else "LOCKED", style="bold green" if unlocked else "bold yellow")
            if width >= 110:
                line.append(f"    NODE {self.ctx.endpoint.base_url}", style="dim #8f8a9f")
        self.query_one("#topbar", Static).update(line)

    def _render_room_header(self) -> None:
        header = Text()
        if self.conversation is None:
            header.append("NO GROUP SELECTED", style="bold #d8c7ff")
            header.append("\nChoose a group with F2.", style="dim #aaa4ba")
        else:
            icon = "◆" if self.conversation.is_private else "◎"
            header.append(f"{icon} {self.conversation.title}", style="bold #f1edff")
            kind = self.conversation.kind.replace("_", " ").upper()
            details = [kind]
            if self.conversation.member_count:
                details.append(f"{self.conversation.member_count} MEMBERS")
            if self.conversation.status:
                details.append(self.conversation.status.replace("_", " "))
            header.append("\n" + "  •  ".join(details), style="dim #aaa4ba")
        self.query_one("#room-header", Static).update(header)

    def _sidebar_option(
        self,
        conversation: ChatConversation,
        number: int,
        *,
        compact: bool,
    ) -> Option:
        unread = self.read_state.unread(conversation)
        line = Text()
        line.append(f"[{number}] ", style="bold #72e7ff")
        line.append(conversation.title, style="bold #f1edff")
        if unread:
            line.append("  ●", style="bold #cf8cff")
        time = _time_label(conversation.timestamp)
        if time:
            line.append(f"  {time}", style="dim #9d96af")
        if conversation.preview and not compact:
            preview = conversation.preview
            if len(preview) > 52:
                preview = preview[:51] + "…"
            line.append("\n" + preview, style="#9fa8c7")
        return Option(line, id=conversation.key)

    def _render_conversations(self) -> None:
        direct_list = self.query_one("#direct-list", OptionList)
        group_list = self.query_one("#group-list", OptionList)
        compact = self.size.width < 104
        self._room_numbers = {}
        direct_options: list[Option] = []
        group_options: list[Option] = []

        for number, conversation in enumerate(self.inbox.conversations, start=1):
            self._room_numbers[number] = conversation.key
            option = self._sidebar_option(conversation, number, compact=compact)
            if conversation.is_direct:
                direct_options.append(option)
            else:
                group_options.append(option)

        if not direct_options:
            direct_options = [
                Option(
                    Text("No direct chats\nCtrl+N to start one", style="dim #8f8a9f"),
                    id="empty-direct",
                    disabled=True,
                )
            ]
        if not group_options:
            group_options = [
                Option(Text("No groups available", style="dim #8f8a9f"), id="empty-groups", disabled=True)
            ]
        direct_list.set_options(direct_options)
        group_list.set_options(group_options)

        if self.conversation is not None:
            target = direct_list if self.conversation.is_direct else group_list
            try:
                target.highlighted = target.get_option_index(self.conversation.key)
            except Exception:
                pass

    def _render_timeline(
        self,
        *,
        follow_end: bool = True,
        selected_signature: str = "",
        highlight_index: int | None = None,
    ) -> None:
        timeline = self.query_one("#timeline", OptionList)
        threads = build_message_threads(list(self.messages))
        reactions = build_message_reaction_index(
            list(self.messages),
            self_address=self.ctx.account.account_address,
        )
        threads_by_signature = {
            _signature(dict(thread.original)): thread
            for thread in threads
            if _signature(dict(thread.original))
        }
        self._message_options = {}
        options: list[Option] = []

        for number, thread in enumerate(threads, start=1):
            original = dict(thread.original)
            latest = dict(thread.latest)
            signature = _signature(original)
            option_id = f"message:{number}:{signature or _integer(original.get('timestamp'))}"
            self._message_options[option_id] = thread
            decoded = decode_chat_message(latest)
            own = str(original.get("sender") or "") == self.ctx.account.account_address

            text = Text()
            text.append(f"#{number:02d}  ", style="bold #72e7ff")
            text.append("YOU" if own else _sender_label(original), style=f"bold {_sender_color(original)}")
            timestamp = _time_label(original.get("timestamp"))
            if timestamp:
                text.append(f"  {timestamp}", style="dim #928ba2")
            if thread.revisions:
                text.append("  EDITED", style="dim #cf8cff")
            if original.get("_unconfirmed") or latest.get("_unconfirmed"):
                text.append("  PENDING", style="bold #ffd166")

            if decoded.replied_to:
                parent = threads_by_signature.get(decoded.replied_to)
                if parent is not None:
                    parent_message = dict(parent.latest)
                    snippet = " ".join(decode_chat_message(parent_message).body.split())
                    if len(snippet) > 70:
                        snippet = snippet[:69] + "…"
                    text.append(
                        f"\n  ↳ {_sender_label(dict(parent.original))}: {snippet}",
                        style="dim #ba9de8",
                    )
                else:
                    text.append("\n  ↳ Earlier message", style="dim #ba9de8")

            body = decoded.body.strip() or "[no text payload]"
            text.append("\n" + body, style="#ffffff")

            summaries = reactions.get(signature, ())
            if summaries:
                text.append("\n")
                for index, summary in enumerate(summaries):
                    if index:
                        text.append("  ")
                    style = "bold #72e7ff" if summary.reacted_by_self else "#c6bed4"
                    text.append(
                        f"{terminal_reaction(summary.content)} {summary.count}",
                        style=style,
                    )

            options.append(Option(text, id=option_id))

        if not options:
            options = [
                Option(
                    Text(
                        "No messages yet.\nWrite below to start the conversation.",
                        style="dim #aaa4ba",
                    ),
                    id="empty-timeline",
                    disabled=True,
                )
            ]
        timeline.set_options(options)
        if threads:
            target_index = len(options) - 1
            if highlight_index is not None:
                target_index = max(0, min(highlight_index, len(options) - 1))
            elif selected_signature and not follow_end:
                for index, thread in enumerate(threads):
                    if _signature(dict(thread.original)) == selected_signature:
                        target_index = index
                        break
            timeline.highlighted = target_index
            if follow_end:
                timeline.call_after_refresh(timeline.scroll_end, animate=False)

    def _active_pane(self) -> str:
        if self.query_one("#composer", Input).has_focus:
            return "composer"
        if self.query_one("#timeline", OptionList).has_focus:
            return "messages"
        if (
            self.query_one("#direct-list", OptionList).has_focus
            or self.query_one("#group-list", OptionList).has_focus
        ):
            return "conversations"
        return ""

    def _render_keybar(self) -> None:
        line = Text()
        line.append(
            self._last_status,
            style="bold #72e7ff" if self._last_status == "READY" else "#e4d7ff",
        )

        pane = self._active_pane()
        if pane == "conversations":
            line.append("    [ GROUPS ACTIVE ]", style="bold #72e7ff")
            hint = "  Up/Down Choose  Enter Open  1-9 Quick switch  F3 Messages  F4 Compose"
        elif pane == "messages":
            line.append("    [ MESSAGES ACTIVE ]", style="bold #cf8cff")
            hint = "  Up/Down Select  1 Reply  2 React  3 Edit  4 Copy  F4 Compose"
        elif pane == "composer":
            line.append("    [ COMPOSER ACTIVE ]", style="bold #80ef9d")
            hint = "  Type message  Enter Send  F2 Groups  F3 Messages  F1 Help"
        else:
            line.append("    [ CHAT ]", style="bold #d8c7ff")
            hint = "  F2 Groups  F3 Messages  F4 Compose  F1 Help"

        line.append(hint, style="dim #aaa4ba")
        line.append("  |  EXIT CHAT: Ctrl+Q", style="bold #f2c66d")
        self.query_one("#keybar", Static).update(line)

    def _set_status(self, status: str) -> None:
        self._last_status = status
        self._render_keybar()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self.call_after_refresh(self._render_keybar)

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self.call_after_refresh(self._render_keybar)

    def _selected_thread(self) -> Any | None:
        timeline = self.query_one("#timeline", OptionList)
        option = timeline.highlighted_option
        return self._message_options.get(option.id) if option is not None else None

    def _mark_current_seen(self) -> None:
        if self.conversation is None:
            return
        previous = (self.read_state.seen_timestamps or {}).get(self.conversation.key, 0)
        self.read_state.mark_seen(self.conversation)
        if previous != (self.read_state.seen_timestamps or {}).get(self.conversation.key, 0):
            save_chat_read_state(self.ctx.settings_dir, self.read_state)

    def _select_conversation(self, key: str) -> None:
        selected = self.inbox.by_key(key)
        if selected is None:
            return
        self.conversation = selected
        self.messages = ()
        self._cancel_context_mode(clear_input=False)
        self.read_state.active_key = selected.key
        save_chat_read_state(self.ctx.settings_dir, self.read_state)
        if selected.group_id is not None:
            self.ctx.chat.tx_group_id = selected.group_id
            write_chat_settings(self.ctx.settings_dir, self.ctx.chat)
        self.screen.remove_class("show-sidebar")
        self._render_conversations()
        self._render_room_header()
        self._render_timeline()
        self._set_status(f"LOADING {selected.title.upper()}…")
        self.refresh_messages()

    @on(OptionList.OptionSelected)
    def _option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id in {"direct-list", "group-list"} and event.option_id:
            self._select_conversation(event.option_id)
            self.query_one("#composer", Input).focus()
        elif event.option_list.id == "timeline":
            self._set_status("MESSAGE SELECTED  [1] REPLY  [2] REACT  [3] EDIT  [4] COPY")

    @on(OptionList.OptionHighlighted, "#timeline")
    def _timeline_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if (
            event.option_index == 0
            and event.option_list.highlighted == 0
            and event.option_list.has_focus
            and self.messages
            and not self._loading_older
            and self.conversation is not None
            and self.conversation.key not in self._history_exhausted
        ):
            self._loading_older = True
            self._set_status("LOADING OLDER MESSAGES…")
            self.load_older_messages()

    @on(Input.Submitted, "#composer")
    def _composer_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if self._new_direct_mode:
            if value:
                self._set_status(f"FINDING {value}…")
                self.resolve_direct(value)
            return
        if not value:
            return
        if value.startswith("/") and not value.startswith("//"):
            self._run_command(value)
            return
        if value.startswith("//"):
            value = value[1:]
        self._begin_send(value)

    @on(Button.Pressed, "#send")
    def _send_pressed(self) -> None:
        composer = self.query_one("#composer", Input)
        self._composer_submitted(Input.Submitted(composer, composer.value, None))

    def _run_command(self, value: str) -> None:
        command, _, argument = value.partition(" ")
        command = command.casefold()
        if command in {"/back", "/quit", "/exit"}:
            self.action_back()
        elif command in {"/refresh", "/reload"}:
            self.action_refresh()
        elif command in {"/direct", "/dm"}:
            if argument.strip():
                self.resolve_direct(argument.strip())
            else:
                self.action_new_direct()
        elif command == "/room":
            try:
                key = self._room_numbers[int(argument.strip())]
            except (ValueError, KeyError):
                self._set_status("ROOM COMMAND: /room <number>")
            else:
                self._select_conversation(key)
        elif command in {"/help", "/?"}:
            self.action_help()
        else:
            self._set_status("UNKNOWN COMMAND  /help lists chat commands")

    def _begin_send(self, text: str) -> None:
        if self._sending or self.conversation is None:
            return
        self._sending = True
        self.query_one("#send", Button).disabled = True
        self.query_one("#composer", Input).disabled = True
        self._set_status("SENDING  BUILDING TRANSACTION + COMPUTING MEMPOW…")
        self.send_message(
            self.conversation,
            text,
            self._reply_signature,
            self._edit_signature,
            self._edit_replied_to,
        )

    @work(thread=True, group="chat-send")
    def send_message(
        self,
        conversation: ChatConversation,
        text: str,
        reply_signature: str,
        edit_signature: str,
        edit_replied_to: str,
    ) -> None:
        try:
            replied_to = edit_replied_to if edit_signature else reply_signature
            result = self.gateway.send_text(
                conversation,
                text,
                replied_to=replied_to,
                chat_reference=edit_signature,
            )
        except Exception as exc:
            self.call_from_thread(self._send_failed, str(exc), text)
        else:
            self.call_from_thread(self._send_finished, result)

    def _send_finished(self, result: Any) -> None:
        self._sending = False
        composer = self.query_one("#composer", Input)
        composer.disabled = False
        composer.value = ""
        self.query_one("#send", Button).disabled = False
        self._cancel_context_mode(clear_input=False)
        self._set_status("SENT  REFRESHING CONVERSATION…")
        self.notify("Message submitted to Qortium Core.", severity="information", timeout=3)
        composer.focus()
        self.refresh_messages()
        self.refresh_inbox()

    def _send_failed(self, detail: str, draft: str) -> None:
        self._sending = False
        composer = self.query_one("#composer", Input)
        composer.disabled = False
        if not composer.value:
            composer.value = draft
        self.query_one("#send", Button).disabled = False
        self._set_status("SEND FAILED  Draft preserved")
        self.notify(detail, title="Unable to send", severity="error", timeout=8)
        composer.focus()

    @work(thread=True, exclusive=True, group="chat-messages")
    def refresh_messages(self) -> None:
        conversation = self.conversation
        if conversation is None:
            return
        try:
            messages = self.gateway.load_messages(conversation)
        except Exception as exc:
            self.call_from_thread(self._messages_failed, conversation.key, str(exc))
        else:
            self.call_from_thread(self._apply_messages, conversation.key, messages)

    def _apply_messages(
        self,
        conversation_key: str,
        messages: tuple[dict[str, Any], ...],
    ) -> None:
        if self.conversation is None or self.conversation.key != conversation_key:
            return
        timeline = self.query_one("#timeline", OptionList)
        follow_end = (
            not timeline.has_focus
            or timeline.highlighted is None
            or timeline.highlighted >= max(0, timeline.option_count - 1)
        )
        selected_thread = self._selected_thread()
        selected_signature = (
            _signature(dict(selected_thread.original)) if selected_thread is not None else ""
        )
        self.messages = messages
        if messages:
            latest_timestamp = max(_integer(row.get("timestamp")) for row in messages)
            if latest_timestamp > self.conversation.timestamp:
                self.conversation = replace(self.conversation, timestamp=latest_timestamp)
        self._mark_current_seen()
        self._render_timeline(
            follow_end=follow_end,
            selected_signature=selected_signature,
        )
        self._render_conversations()
        if not self._sending:
            self._set_status("READY")

    def _messages_failed(self, conversation_key: str, detail: str) -> None:
        if self.conversation is None or self.conversation.key != conversation_key:
            return
        self._set_status("CONVERSATION UNAVAILABLE  Ctrl+R to retry")
        self.notify(detail, title="Unable to load messages", severity="error", timeout=7)

    @work(thread=True, exclusive=True, group="chat-history")
    def load_older_messages(self) -> None:
        conversation = self.conversation
        if conversation is None or not self.messages:
            self.call_from_thread(self._older_messages_finished, "", ())
            return
        before = min(_integer(row.get("timestamp")) for row in self.messages)
        try:
            older = self.gateway.load_messages(conversation, before=before)
        except Exception as exc:
            self.call_from_thread(self._older_messages_failed, str(exc))
        else:
            self.call_from_thread(
                self._older_messages_finished,
                conversation.key,
                older,
            )

    def _older_messages_finished(
        self,
        conversation_key: str,
        older: tuple[dict[str, Any], ...],
    ) -> None:
        self._loading_older = False
        if self.conversation is None or self.conversation.key != conversation_key:
            return
        existing_keys = {
            (
                str(row.get("signature") or ""),
                _integer(row.get("timestamp")),
                str(row.get("sender") or ""),
            )
            for row in self.messages
        }
        added = [
            row
            for row in older
            if (
                str(row.get("signature") or ""),
                _integer(row.get("timestamp")),
                str(row.get("sender") or ""),
            )
            not in existing_keys
        ]
        if not added:
            self._history_exhausted.add(conversation_key)
            self._set_status("BEGINNING OF AVAILABLE HISTORY")
            return
        combined = [*added, *self.messages]
        combined.sort(key=lambda row: _integer(row.get("timestamp")))
        self.messages = tuple(combined)
        self._render_timeline(
            follow_end=False,
            highlight_index=len(added),
        )
        self._set_status(f"LOADED {len(added)} OLDER MESSAGES")

    def _older_messages_failed(self, detail: str) -> None:
        self._loading_older = False
        self._set_status("OLDER HISTORY UNAVAILABLE")
        self.notify(detail, title="Unable to load older messages", severity="warning", timeout=5)

    @work(thread=True, exclusive=True, group="chat-inbox")
    def refresh_inbox(self) -> None:
        try:
            inbox = self.gateway.list_conversations()
        except Exception as exc:
            self.call_from_thread(
                self.notify,
                str(exc),
                title="Unable to refresh conversations",
                severity="warning",
                timeout=5,
            )
        else:
            self.call_from_thread(self._apply_inbox, inbox)

    def _apply_inbox(self, inbox: ConversationInbox) -> None:
        if self.conversation is not None and inbox.by_key(self.conversation.key) is None:
            conversations = tuple((*inbox.conversations, self.conversation))
            inbox = ConversationInbox(conversations, inbox.warnings)
        self.inbox = inbox
        if self.conversation is not None:
            refreshed = inbox.by_key(self.conversation.key)
            if refreshed is not None:
                self.conversation = refreshed
        self._render_conversations()
        self._render_room_header()
        if inbox.warnings:
            self.notify(inbox.warnings[0], title="Partial chat refresh", severity="warning", timeout=5)

    def action_reply(self) -> None:
        thread = self._selected_thread()
        if thread is None:
            self._set_status("SELECT A MESSAGE FIRST")
            return
        signature = _signature(dict(thread.original))
        if not signature:
            self._set_status("THAT MESSAGE CANNOT BE REFERENCED YET")
            return
        self._reply_signature = signature
        self._edit_signature = ""
        self._reaction_signature = ""
        sender = _sender_label(dict(thread.original))
        self._set_status(f"REPLYING TO {sender.upper()}  Esc cancels")
        self.query_one("#composer", Input).focus()

    def action_edit(self) -> None:
        thread = self._selected_thread()
        if thread is None:
            self._set_status("SELECT ONE OF YOUR MESSAGES FIRST")
            return
        original = dict(thread.original)
        if str(original.get("sender") or "") != self.ctx.account.account_address:
            self._set_status("ONLY YOUR OWN MESSAGES CAN BE EDITED")
            return
        signature = _signature(original)
        if not signature:
            self._set_status("PENDING MESSAGES CANNOT BE EDITED")
            return
        decoded = decode_chat_message(dict(thread.latest))
        self._edit_signature = signature
        self._edit_replied_to = decoded.replied_to or ""
        self._reply_signature = ""
        composer = self.query_one("#composer", Input)
        composer.value = decoded.body
        composer.cursor_position = len(composer.value)
        composer.focus()
        self._set_status("EDITING MESSAGE  Enter submits  Esc cancels")

    def action_react(self) -> None:
        thread = self._selected_thread()
        if thread is None:
            self._set_status("SELECT A MESSAGE FIRST")
            return
        signature = _signature(dict(thread.original))
        if not signature:
            self._set_status("PENDING MESSAGES CANNOT RECEIVE REACTIONS")
            return
        self._reaction_signature = signature
        self._set_status("CHOOSING REACTION")
        self.push_screen(ReactionPickerScreen(), self._reaction_selected)

    def _reaction_selected(self, reaction: str | None) -> None:
        if reaction is None:
            self._reaction_signature = ""
            self._set_status("READY")
            return
        self._send_reaction(reaction)

    def _send_reaction(self, reaction: str) -> None:
        if self.conversation is None or not self._reaction_signature:
            return
        index = build_message_reaction_index(
            list(self.messages),
            self_address=self.ctx.account.account_address,
        )
        existing = index.get(self._reaction_signature, ())
        reacted = any(
            summary.content == reaction and summary.reacted_by_self
            for summary in existing
        )
        payload = build_reaction_message_text(reaction, not reacted)
        self._sending = True
        self._set_status("SENDING REACTION…")
        self.send_reaction_payload(
            self.conversation,
            payload,
            self._reaction_signature,
        )

    @work(thread=True, group="chat-send")
    def send_reaction_payload(
        self,
        conversation: ChatConversation,
        payload: str,
        signature: str,
    ) -> None:
        try:
            result = self.gateway.send_payload(
                conversation,
                payload,
                chat_reference=signature,
            )
        except Exception as exc:
            self.call_from_thread(self._reaction_failed, str(exc))
        else:
            self.call_from_thread(self._reaction_finished, result)

    def _reaction_finished(self, result: Any) -> None:
        self._sending = False
        self._reaction_signature = ""
        self._set_status("REACTION SENT  REFRESHING…")
        self.notify("Reaction submitted.", severity="information", timeout=2)
        self.refresh_messages()

    def _reaction_failed(self, detail: str) -> None:
        self._sending = False
        self._reaction_signature = ""
        self._set_status("REACTION FAILED")
        self.notify(detail, title="Unable to react", severity="error", timeout=7)

    def action_copy(self) -> None:
        thread = self._selected_thread()
        if thread is None:
            self._set_status("SELECT A MESSAGE FIRST")
            return
        body = decode_chat_message(dict(thread.latest)).body
        self.copy_to_clipboard(body)
        self._set_status("MESSAGE COPIED TO TERMINAL CLIPBOARD")

    def action_new_direct(self) -> None:
        self._cancel_context_mode(clear_input=True)
        self._new_direct_mode = True
        composer = self.query_one("#composer", Input)
        composer.placeholder = "Qortium name or Q address"
        composer.focus()
        self._set_status("NEW DIRECT CHAT  Enter a name or address  Esc cancels")

    @work(thread=True, exclusive=True, group="direct-resolve")
    def resolve_direct(self, value: str) -> None:
        try:
            conversation = self.gateway.resolve_direct_recipient(value)
        except Exception as exc:
            self.call_from_thread(self._direct_failed, str(exc))
        else:
            self.call_from_thread(self._direct_resolved, conversation)

    def _direct_resolved(self, conversation: ChatConversation) -> None:
        existing = self.inbox.by_key(conversation.key)
        if existing is None:
            direct = [
                item for item in self.inbox.conversations if item.is_direct
            ]
            groups = [
                item for item in self.inbox.conversations if not item.is_direct
            ]
            direct.append(conversation)
            direct.sort(key=lambda item: (-item.timestamp, item.title.casefold()))
            self.inbox = ConversationInbox(tuple((*direct, *groups)), self.inbox.warnings)
        self._new_direct_mode = False
        composer = self.query_one("#composer", Input)
        composer.value = ""
        composer.placeholder = "Write a message…"
        self._select_conversation(conversation.key)
        self._set_status("DIRECT CHAT READY  Write your message below")

    def _direct_failed(self, detail: str) -> None:
        self._set_status("DIRECT CHAT LOOKUP FAILED  Draft preserved")
        self.notify(detail, title="Unable to start direct chat", severity="error", timeout=7)
        self.query_one("#composer", Input).focus()

    def _cancel_context_mode(self, *, clear_input: bool) -> None:
        self._reply_signature = ""
        self._edit_signature = ""
        self._edit_replied_to = ""
        self._reaction_signature = ""
        self._new_direct_mode = False
        composer = self.query_one("#composer", Input)
        composer.placeholder = "Write a message…"
        if clear_input:
            composer.value = ""

    def on_key(self, event: events.Key) -> None:
        composer = self.query_one("#composer", Input)
        if event.key == "escape" and (
            self._reply_signature
            or self._edit_signature
            or self._reaction_signature
            or self._new_direct_mode
        ):
            self._cancel_context_mode(clear_input=self._new_direct_mode)
            self._set_status("READY")
            event.prevent_default()
            event.stop()
            return

        if composer.has_focus:
            return

        timeline = self.query_one("#timeline", OptionList)
        if timeline.has_focus and event.key in {"1", "2", "3", "4"}:
            {
                "1": self.action_reply,
                "2": self.action_react,
                "3": self.action_edit,
                "4": self.action_copy,
            }[event.key]()
            event.prevent_default()
            event.stop()
            return

        direct_list = self.query_one("#direct-list", OptionList)
        group_list = self.query_one("#group-list", OptionList)
        if (
            (direct_list.has_focus or group_list.has_focus)
            and event.key.isdigit()
            and 1 <= int(event.key) <= 9
        ):
            key = self._room_numbers.get(int(event.key))
            if key:
                self._select_conversation(key)
                event.prevent_default()
                event.stop()
            return

        action = {
            "r": self.action_reply,
            "x": self.action_react,
            "e": self.action_edit,
            "c": self.action_copy,
            "0": self.action_back,
        }.get(event.key)
        if action is not None:
            action()
            event.prevent_default()
            event.stop()

    def action_focus_rooms(self) -> None:
        if self.screen.has_class("narrow"):
            self.screen.add_class("show-sidebar")
        target = (
            self.query_one("#direct-list", OptionList)
            if self.conversation and self.conversation.is_direct
            else self.query_one("#group-list", OptionList)
        )
        target.focus()

    def action_focus_timeline(self) -> None:
        self.screen.remove_class("show-sidebar")
        self.query_one("#timeline", OptionList).focus()

    def action_focus_composer(self) -> None:
        self.screen.remove_class("show-sidebar")
        self.query_one("#composer", Input).focus()

    def action_refresh(self) -> None:
        self._set_status("REFRESHING…")
        self.refresh_inbox()
        self.refresh_messages()

    def action_help(self) -> None:
        if not self.read_state.help_seen:
            self.read_state.help_seen = True
            save_chat_read_state(self.ctx.settings_dir, self.read_state)
        self.push_screen(ChatHelpScreen())

    def action_back(self) -> None:
        save_chat_read_state(self.ctx.settings_dir, self.read_state)
        self.exit("back")


def run_chat_tui(ctx: AppContext) -> str:
    """Load initial chat state under the current-screen transition, then run the TUI."""

    gateway = ChatGateway(ctx)
    read_state = load_chat_read_state(ctx.settings_dir)
    inbox = ConversationInbox(())
    conversation: ChatConversation | None = None
    messages: tuple[dict[str, Any], ...] = ()

    with spinner("Opening chat…"):
        inbox = gateway.list_conversations()
        conversation = _select_initial_conversation(ctx, inbox, read_state)
        if conversation is not None:
            try:
                messages = gateway.load_messages(conversation)
            except Exception:
                messages = ()

    app = ChatWorkspaceApp(
        ctx,
        gateway,
        inbox,
        conversation,
        messages,
        read_state,
    )
    return app.run() or "back"


def can_run_chat_tui() -> bool:
    return bool(
        sys.stdin
        and sys.stdout
        and hasattr(sys.stdin, "isatty")
        and hasattr(sys.stdout, "isatty")
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
