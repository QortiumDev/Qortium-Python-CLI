from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import (
    get_admin_group_join_requests,
    get_group_info,
    get_group_invites,
)
from qortium_cli.tools import (
    _format_invite_expiry,
    _submit_group_join_request_approval,
    build_tool_plugins,
    tx_group_accept_invite,
    tx_group_review_join_requests,
)


def make_context() -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(
            name="tester",
            account_address="QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            public_key="public-key",
            private_key="private-key",
            api_key="api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


class GroupServiceTests(TestCase):
    def test_group_helpers_parse_expected_shapes(self) -> None:
        ctx = make_context()
        session = MagicMock()
        invites_response = MagicMock()
        invites_response.json.return_value = [
            {"groupId": 7, "inviter": "Qinviter"},
            "not-an-invite",
        ]
        group_response = MagicMock()
        group_response.json.return_value = {"groupId": 7, "groupName": "Builders"}
        session.get.side_effect = [invites_response, group_response]

        invites = get_group_invites(ctx, ctx.account.account_address, session)
        group = get_group_info(ctx, 7, session)

        self.assertEqual(invites, [{"groupId": 7, "inviter": "Qinviter"}])
        self.assertEqual(group["groupName"], "Builders")
        invites_response.raise_for_status.assert_called_once_with()
        group_response.raise_for_status.assert_called_once_with()

    def test_admin_join_requests_uses_aggregate_endpoint(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = [
            {
                "group": {"groupId": 7, "groupName": "Builders"},
                "joinRequests": [
                    {"groupId": 7, "joiner": "Qjoiner-one"},
                    {"groupId": 7, "joiner": "Qjoiner-two"},
                ],
            },
            {
                "group": {"groupId": 8, "groupName": "Empty"},
                "joinRequests": [],
            },
        ]
        session = MagicMock()
        session.get.return_value = response

        requests = get_admin_group_join_requests(
            ctx,
            ctx.account.account_address,
            session,
        )

        self.assertEqual(
            requests,
            [
                {
                    "groupId": 7,
                    "groupName": "Builders",
                    "joiner": "Qjoiner-one",
                },
                {
                    "groupId": 7,
                    "groupName": "Builders",
                    "joiner": "Qjoiner-two",
                },
            ],
        )
        session.get.assert_called_once_with(
            "http://127.0.0.1:24891/groups/joinrequests/admin/"
            "QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            timeout=15,
        )

    def test_admin_join_requests_falls_back_and_verifies_admin(self) -> None:
        ctx = make_context()
        missing_response = MagicMock()
        missing_response.status_code = 404
        groups_response = MagicMock()
        groups_response.json.return_value = [
            {
                "groupId": 7,
                "groupName": "Builders",
                "owner": "Qowner",
            },
            {
                "groupId": 8,
                "groupName": "Members Only",
                "owner": "Qowner",
            },
        ]
        admins_response = MagicMock()
        admins_response.json.return_value = {
            "groupMembers": [
                {"member": ctx.account.account_address, "isAdmin": True}
            ]
        }
        non_admins_response = MagicMock()
        non_admins_response.json.return_value = {
            "groupMembers": [{"member": "Qother-admin", "isAdmin": True}]
        }
        requests_response = MagicMock()
        requests_response.json.return_value = [
            {"groupId": 7, "joiner": "Qjoiner"}
        ]
        session = MagicMock()
        session.get.side_effect = [
            missing_response,
            groups_response,
            admins_response,
            requests_response,
            non_admins_response,
        ]

        requests = get_admin_group_join_requests(
            ctx,
            ctx.account.account_address,
            session,
        )

        self.assertEqual(
            requests,
            [{"groupId": 7, "groupName": "Builders", "joiner": "Qjoiner"}],
        )
        self.assertEqual(session.get.call_count, 5)


class GroupWorkflowTests(TestCase):
    def test_permanent_invite_has_no_expiry(self) -> None:
        self.assertEqual(_format_invite_expiry(None), "Never")
        self.assertEqual(_format_invite_expiry(0), "Never")

    def test_main_menu_uses_requested_numbering(self) -> None:
        tools = build_tool_plugins()

        self.assertEqual([tool.key for tool in tools], ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(
            [tool.label for tool in tools],
            ["Node", "Chat", "Groups", "Register Name", "Wallet", "QDN Resources"],
        )

    def test_accept_invite_submits_join_for_selected_group(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        invites = [
            {"groupId": "7", "inviter": "Qfirst", "expiry": 0},
            {"groupId": 42, "inviter": "Qsecond", "expiry": 1_800_000_000_000},
        ]

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch("qortium_cli.tools.get_group_invites", return_value=invites),
            patch(
                "qortium_cli.tools.get_group_info",
                side_effect=[
                    {"groupId": 7, "groupName": "First Group"},
                    {"groupId": 42, "groupName": "Second Group"},
                ],
            ),
            patch("qortium_cli.tools.read_menu_choice", return_value="2"),
            patch("qortium_cli.tools.prompt_yes_no", return_value=True),
            patch("qortium_cli.tools._submit_group_join") as submit_group_join,
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.print_stat"),
            patch("qortium_cli.tools.print_option"),
            patch("qortium_cli.tools.pause"),
        ):
            tx_group_accept_invite(ctx)

        submit_group_join.assert_called_once_with(ctx, 42)

    def test_review_join_request_submits_selected_approval(self) -> None:
        ctx = make_context()
        join_requests = [
            {"groupId": 7, "groupName": "First Group", "joiner": "Qfirst"},
            {"groupId": 42, "groupName": "Second Group", "joiner": "Qsecond"},
        ]

        with (
            patch(
                "qortium_cli.tools.get_admin_group_join_requests",
                return_value=join_requests,
            ),
            patch("qortium_cli.tools.make_session") as make_session,
            patch("qortium_cli.tools.read_menu_choice", return_value="2"),
            patch("qortium_cli.tools.prompt_yes_no", return_value=True),
            patch(
                "qortium_cli.tools._submit_group_join_request_approval"
            ) as submit_approval,
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.print_stat"),
            patch("qortium_cli.tools.print_option"),
            patch("qortium_cli.tools.pause"),
        ):
            make_session.return_value.__enter__.return_value = MagicMock()
            tx_group_review_join_requests(ctx)

        submit_approval.assert_called_once_with(ctx, 42, "Qsecond")

    def test_join_request_approval_builds_group_invite(self) -> None:
        ctx = make_context()
        session_context = MagicMock()
        session_context.__enter__.return_value = MagicMock()

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch(
                "qortium_cli.tools.get_admin_group_join_requests",
                return_value=[
                    {
                        "groupId": 42,
                        "groupName": "Second Group",
                        "joiner": "Qsecond",
                    }
                ],
            ),
            patch("qortium_cli.tools.prompt_decimal", return_value=Decimal("0")),
            patch("qortium_cli.tools.prompt_int", return_value=42),
            patch(
                "qortium_cli.tools.to_base58_pubkey",
                return_value="admin-public-key",
            ),
            patch("qortium_cli.tools._submit_builder_transaction") as submit_tx,
        ):
            _submit_group_join_request_approval(ctx, 42, "Qsecond")

        submit_tx.assert_called_once_with(
            ctx,
            "/groups/invite",
            "GROUP_INVITE join approval",
            {
                "adminPublicKey": "admin-public-key",
                "groupId": 42,
                "invitee": "Qsecond",
                "timeToLive": 0,
            },
            "0.00000000",
            42,
        )
