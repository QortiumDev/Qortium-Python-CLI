"""Conversation-first chat workspace."""

from __future__ import annotations

import datetime
import hashlib
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from qortium_cli.chat_format import (
    build_message_reaction_index,
    build_message_threads,
    decode_chat_message,
    terminal_reaction,
)
from qortium_cli.models import AppContext
from qortium_cli.storage import write_chat_settings
from qortium_cli.ui import (
    ok,
    pause,
    prompt_decimal,
    prompt_int,
    prompt_str,
    read_menu_choice,
    warn,
)
from qortium_cli.ui.menu import MenuOption, render_header, render_options
from qortium_cli.ui.theme import CHAT_USER_HEX, console
from qortium_cli.ui.widgets import error_panel, spinner
from qortium_cli.utils import d8, pretty_exception


@dataclass(frozen=True)
class ChatRoom:
    group_id: int
    name: str

    @property
    def kind(self) -> str:
        return "PUBLIC" if self.group_id == 0 else "GROUP"


@dataclass(frozen=True)
class ChatWorkspaceState:
    room: ChatRoom
    groups: tuple[ChatRoom, ...]
    messages: tuple[dict[str, Any], ...]
    timeline_error: str = ""
    groups_error: str = ""


def _group_room(group: dict[str, Any]) -> ChatRoom | None:
    try:
        group_id = int(group.get("groupId", -1))
    except (TypeError, ValueError):
        return None
    if group_id <= 0:
        return None
    name = str(group.get("groupName", "") or "").strip() or f"Group {group_id}"
    return ChatRoom(group_id, name)


def _member_rooms(groups: Sequence[dict[str, Any]]) -> tuple[ChatRoom, ...]:
    rooms: dict[int, ChatRoom] = {}
    for group in groups:
        room = _group_room(group)
        if room is not None:
            rooms[room.group_id] = room
    return tuple(sorted(rooms.values(), key=lambda room: (room.name.casefold(), room.group_id)))


def _active_room(group_id: int, groups: Sequence[ChatRoom]) -> ChatRoom:
    if group_id == 0:
        return ChatRoom(0, "General Chat")
    return next(
        (group for group in groups if group.group_id == group_id),
        ChatRoom(group_id, f"Group {group_id}"),
    )


def _load_state(ctx: AppContext) -> ChatWorkspaceState:
    from qortium_cli.services import get_member_groups, make_session
    from qortium_cli.tools import _fetch_chat_timeline

    groups: tuple[ChatRoom, ...] = ()
    messages: tuple[dict[str, Any], ...] = ()
    groups_error = ""
    timeline_error = ""

    with spinner("Loading conversation..."):
        try:
            with make_session(ctx, include_api_key=False) as session:
                groups = _member_rooms(
                    get_member_groups(ctx, ctx.account.account_address, session)
                )
        except Exception as exc:
            groups_error = pretty_exception(exc)

        try:
            messages = tuple(_fetch_chat_timeline(ctx))
        except Exception as exc:
            timeline_error = pretty_exception(exc)

    return ChatWorkspaceState(
        room=_active_room(int(ctx.chat.tx_group_id), groups),
        groups=groups,
        messages=messages,
        timeline_error=timeline_error,
        groups_error=groups_error,
    )


def _time_label(timestamp: Any) -> str:
    try:
        value = datetime.datetime.fromtimestamp(int(timestamp) / 1000)
        today = datetime.datetime.now().date()
        return value.strftime("%H:%M") if value.date() == today else value.strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "--:--"


def _sender_label(message: dict[str, Any]) -> str:
    address = str(message.get("sender", "") or "").strip()
    name = str(message.get("senderName", "") or "").strip()
    if name:
        return name
    if len(address) > 18:
        return f"{address[:9]}…{address[-6:]}"
    return address or "Unknown"


def _sender_style(message: dict[str, Any]) -> str:
    identity = str(message.get("sender", "") or _sender_label(message)).casefold()
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return CHAT_USER_HEX[int.from_bytes(digest[:2], "big") % len(CHAT_USER_HEX)]


def _conversation_panel(ctx: AppContext, state: ChatWorkspaceState) -> Panel:
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(style="#8f86a4", no_wrap=True)
    grid.add_column(style="white", overflow="fold")
    grid.add_row("ROOM", f"[bold #5ee7ff]{state.room.name}[/]")
    grid.add_row("TYPE", state.room.kind)
    grid.add_row("GROUP ID", str(state.room.group_id))
    grid.add_row("IDENTITY", ctx.account.name or ctx.account.account_address)
    grid.add_row("FEE", f"{d8(_chat_fee(ctx))} QORT")
    return Panel(
        grid,
        title="[bold #5ee7ff] ACTIVE CONVERSATION [/]",
        box=box.SQUARE,
        border_style="#376c78",
    )


def _quick_guide_panel(state: ChatWorkspaceState) -> Panel:
    guide = Text()
    guide.append("[1] ", style="bold #5ee7ff")
    guide.append("SEND MESSAGE\n", style="bold white")
    guide.append("[2] ", style="bold #5ee7ff")
    guide.append("SWITCH ROOM\n", style="bold white")
    guide.append("[3–5] ", style="bold #c9a7ff")
    guide.append("REPLY • REACT • EDIT\n", style="white")
    guide.append("[6] ", style="bold #c9a7ff")
    guide.append("REFRESH", style="white")
    if state.groups_error:
        guide.append("\n\nGroup list unavailable; manual room selection still works.", style="amber1")
    return Panel(
        guide,
        title="[bold #c9a7ff] QUICK KEYS [/]",
        box=box.SQUARE,
        border_style="#604b82",
    )


def _message_body(
    ctx: AppContext,
    thread: Any,
    reactions: dict[str, tuple[Any, ...]],
) -> Text:
    original = dict(thread.original)
    latest = dict(thread.latest)
    decoded = decode_chat_message(latest)
    body = Text()

    if decoded.replied_to:
        body.append("↳ reply  ", style="dim #b9afd4")
    text = decoded.body.strip() or "[no text payload]"
    body.append(text, style="white")
    if thread.revisions:
        body.append("  EDITED", style="dim #c9a7ff")
    if latest.get("_unconfirmed") or original.get("_unconfirmed"):
        body.append("  PENDING", style="bold amber1")

    signature = str(original.get("signature", "") or "").strip()
    summaries = reactions.get(signature, ())
    if summaries:
        body.append("\n")
        for index, reaction in enumerate(summaries):
            if index:
                body.append("  ")
            style = "bold #5ee7ff" if reaction.reacted_by_self else "#b9afd4"
            body.append(
                f"{terminal_reaction(reaction.content)} {reaction.count}",
                style=style,
            )
    return body


def _timeline_panel(ctx: AppContext, state: ChatWorkspaceState) -> Panel:
    if state.timeline_error:
        return Panel(
            f"[bold red]Conversation unavailable[/]\n[#a9a0bc]{state.timeline_error}[/]",
            title="[bold red] TIMELINE [/]",
            box=box.SQUARE,
            border_style="#7a3e4c",
        )

    threads = build_message_threads(list(state.messages))
    visible_count = max(4, min(14, console.height - 19))
    visible = threads[-visible_count:]
    if not visible:
        return Panel(
            "[#a9a0bc]No messages yet. Start the conversation with option 1.[/]",
            title="[bold #c9a7ff] TIMELINE • 0 MESSAGES [/]",
            box=box.SQUARE,
            border_style="#604b82",
        )

    reactions = build_message_reaction_index(
        list(state.messages),
        self_address=ctx.account.account_address,
    )
    compact = console.width < 76
    table = Table.grid(expand=True, padding=(0, 1))
    if compact:
        table.add_column(overflow="fold")
    else:
        table.add_column(width=20, no_wrap=True)
        table.add_column(ratio=1, overflow="fold")

    for thread in visible:
        original = dict(thread.original)
        meta = Text()
        meta.append(_time_label(original.get("timestamp")), style="dim #8f86a4")
        meta.append("  ")
        meta.append(_sender_label(original), style=f"bold {_sender_style(original)}")
        body = _message_body(ctx, thread, reactions)
        if compact:
            combined = Text.assemble(meta, "\n", body)
            table.add_row(combined)
        else:
            table.add_row(meta, body)

    hidden = len(threads) - len(visible)
    subtitle = f"showing latest {len(visible)}"
    if hidden > 0:
        subtitle += f" • {hidden} older"
    return Panel(
        table,
        title=f"[bold #c9a7ff] TIMELINE • {len(threads)} MESSAGES [/]",
        subtitle=f"[dim]{subtitle}[/]",
        box=box.SQUARE,
        border_style="#604b82",
    )


def render_chat_workspace(
    ctx: AppContext,
    state: ChatWorkspaceState,
    options: tuple[MenuOption, ...] | None = None,
) -> None:
    render_header(ctx, "Chat & Groups", "Home  >  Chat & Groups")
    conversation = _conversation_panel(ctx, state)
    guide = _quick_guide_panel(state)

    if console.width >= 94:
        context_grid = Table.grid(expand=True, padding=(0, 1))
        context_grid.add_column(ratio=3)
        context_grid.add_column(ratio=2)
        context_grid.add_row(conversation, guide)
        console.print(context_grid)
    else:
        console.print(conversation)
        console.print(guide)

    console.print(_timeline_panel(ctx, state))
    console.print("[bold #8d6bff] CONVERSATION ACTIONS [/]\n")
    render_options(options or chat_actions(state.messages, state.groups))


def _chat_fee(ctx: AppContext) -> Decimal:
    try:
        value = Decimal(str(ctx.chat.fee or "0"))
        return value if value >= 0 else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _send(ctx: AppContext) -> None:
    from qortium_cli.tools import _send_chat_message

    message = prompt_str("Message: ", "").strip()
    if not message:
        warn("Message cancelled.")
        pause()
        return
    result = _send_chat_message(ctx, message)
    ok("Chat message submitted.")
    if ctx.debug:
        console.print(f"[dim]Core response: {result}[/]")
    pause()


def _reply(ctx: AppContext, messages: Sequence[dict[str, Any]]) -> None:
    from qortium_cli.tools import _run_chat_reply_command

    result = _run_chat_reply_command(ctx, list(messages))
    if result is not None:
        ok("Chat reply submitted.")
    pause()


def _react(ctx: AppContext, messages: Sequence[dict[str, Any]]) -> None:
    from qortium_cli.tools import _run_chat_reaction_command

    result = _run_chat_reaction_command(ctx, list(messages))
    if result is not None:
        ok("Chat reaction submitted.")
    pause()


def _edit(ctx: AppContext, messages: Sequence[dict[str, Any]]) -> None:
    from qortium_cli.tools import _run_chat_edit_command

    result = _run_chat_edit_command(ctx, list(messages))
    if result is not None:
        ok("Chat edit submitted.")
    pause()


def _switch_room(ctx: AppContext, groups: Sequence[ChatRoom]) -> None:
    render_header(ctx, "Switch Room", "Home  >  Chat & Groups  >  Switch Room")
    rooms = (ChatRoom(0, "General Chat"), *groups)
    options = tuple(
        MenuOption(
            str(index),
            room.name,
            (
                ("Current room • " if room.group_id == int(ctx.chat.tx_group_id) else "")
                + f"{room.kind.title()} conversation • group ID {room.group_id}"
            ),
            lambda _: None,
        )
        for index, room in enumerate(rooms, start=1)
    )
    manual_key = str(len(options) + 1)
    manual = MenuOption(
        manual_key,
        "Enter another group ID",
        "Open a known group that is not in your membership list",
        lambda _: None,
    )
    render_options((*options, manual))

    choice = read_menu_choice("\nChoose room: ").strip()
    if choice == "0":
        return
    if choice == manual_key:
        selected_id = prompt_int(
            "Group ID: ",
            default=int(ctx.chat.tx_group_id),
            minimum=0,
        )
    else:
        try:
            selected_id = rooms[int(choice) - 1].group_id
        except (ValueError, IndexError):
            warn("That room number is not available.")
            pause()
            return

    ctx.chat.tx_group_id = int(selected_id)
    write_chat_settings(ctx.settings_dir, ctx.chat)


def _manage_groups(ctx: AppContext) -> None:
    from qortium_cli.tools import tool_groups

    tool_groups(ctx)


def _change_fee(ctx: AppContext) -> None:
    current = _chat_fee(ctx)
    new_fee = prompt_decimal(f"Chat fee [{d8(current)}]: ", default=current)
    ctx.chat.fee = d8(new_fee)
    write_chat_settings(ctx.settings_dir, ctx.chat)
    ok(f"Chat fee set to {ctx.chat.fee} QORT.")
    pause()


def _refresh(_: AppContext) -> None:
    """Return to the workspace loop, which reloads the conversation."""


def chat_actions(
    messages: Sequence[dict[str, Any]],
    groups: Sequence[ChatRoom],
) -> tuple[MenuOption, ...]:
    """Return the stable, workflow-ordered conversation actions."""

    return (
        MenuOption("1", "Send message", "Write to the active conversation", _send),
        MenuOption(
            "2",
            "Switch room",
            "Choose public chat, a joined group, or enter a group ID",
            lambda ctx: _switch_room(ctx, groups),
        ),
        MenuOption(
            "3",
            "Reply to message",
            "Choose a participant and message to answer",
            lambda ctx: _reply(ctx, messages),
        ),
        MenuOption(
            "4",
            "React to message",
            "Add or remove a terminal-friendly reaction",
            lambda ctx: _react(ctx, messages),
        ),
        MenuOption(
            "5",
            "Edit my message",
            "Publish an updated revision of your message",
            lambda ctx: _edit(ctx, messages),
        ),
        MenuOption("6", "Refresh conversation", "Reload messages from Core", _refresh),
        MenuOption(
            "7",
            "Manage groups",
            "Join, create, accept invites, and review requests",
            _manage_groups,
        ),
        MenuOption("8", "Change chat fee", "Set the fee used for new messages", _change_fee),
    )


def open_chat_workspace(ctx: AppContext) -> None:
    if os.environ.get("QORTIUM_CLI_CHAT_UI", "").strip().casefold() != "legacy":
        try:
            from qortium_cli.features.chat_tui import can_run_chat_tui, run_chat_tui
        except ImportError:
            pass
        else:
            if can_run_chat_tui():
                run_chat_tui(ctx)
                return

    while True:
        state = _load_state(ctx)
        options = chat_actions(state.messages, state.groups)
        option_map = {option.key: option for option in options}
        render_chat_workspace(ctx, state, options)

        choice = read_menu_choice("\nChoose: ").strip()
        if choice == "0":
            return
        option = option_map.get(choice)
        if option is None:
            warn("That number is not available here.")
            pause()
            continue

        try:
            option.action(ctx)
        except KeyboardInterrupt:
            warn("Cancelled.")
            pause()
        except Exception as exc:
            error_panel(
                pretty_exception(exc),
                hint="Check the active account and node connection, then try again.",
            )
            pause()
