from decimal import Decimal
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, patch
import zipfile

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import (
    build_arbitrary_delete,
    build_arbitrary_from_path,
    delete_local_arbitrary_resource,
    get_account_names,
    get_hosted_arbitrary_resources,
    search_arbitrary_resources,
)
from qortium_cli.tools import (
    _qdn_resource_tuple,
    _submit_arbitrary_delete_transaction,
    _submit_arbitrary_publish_transaction,
    browse_qdn_resources,
    select_qdn_resource,
    tool_register_name,
    tx_name_register,
    tx_name_update,
)


def make_context() -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(
            name="My Name",
            account_address="QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            public_key="public-key",
            private_key="private-key",
            api_key="api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


class QdnServiceTests(TestCase):
    def test_account_names_returns_owned_name_strings(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.json.return_value = [
            {"name": "First Name"},
            {"name": "Second Name"},
            {"owner": ctx.account.account_address},
        ]
        session = MagicMock()
        session.get.return_value = response

        names = get_account_names(ctx, ctx.account.account_address, session)

        self.assertEqual(names, ["First Name", "Second Name"])
        session.get.assert_called_once_with(
            "http://127.0.0.1:24891/names/address/"
            "QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            params={"limit": 100, "offset": 0, "reverse": "false"},
            timeout=15,
        )

    def test_search_resources_filters_to_exact_owned_names(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.json.return_value = [
            {"service": "APP", "name": "My Name", "identifier": "main"}
        ]
        session = MagicMock()
        session.get.return_value = response

        rows = search_arbitrary_resources(
            ctx,
            session,
            query="main",
            service="APP",
            names=["My Name", "Other Name"],
            limit=10,
            offset=20,
        )

        self.assertEqual(len(rows), 1)
        session.get.assert_called_once_with(
            "http://127.0.0.1:24891/arbitrary/resources/search",
            params={
                "mode": "LATEST",
                "includestatus": "true",
                "includemetadata": "true",
                "excludeblocked": "false",
                "limit": 10,
                "offset": 20,
                "reverse": "true",
                "query": "main",
                "service": "APP",
                "name": ["My Name", "Other Name"],
                "exactmatchnames": "true",
            },
            timeout=15,
        )

    def test_hosted_resource_lookup_uses_api_key_endpoint(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.json.return_value = [
            {"service": "WEBSITE", "name": "My Name", "identifier": None}
        ]
        session = MagicMock()
        session.get.return_value = response

        rows = get_hosted_arbitrary_resources(
            ctx,
            session,
            query="my",
            limit=50,
            offset=5,
        )

        self.assertEqual(len(rows), 1)
        session.get.assert_called_once_with(
            "http://127.0.0.1:24891/arbitrary/hosted/resources",
            params={"limit": 50, "offset": 5, "query": "my"},
            timeout=15,
        )

    def test_build_default_delete_uses_qortium_default_endpoint(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.text = "unsigned-transaction"
        session = MagicMock()
        session.post.return_value = response

        result = build_arbitrary_delete(
            ctx,
            "APP",
            "My Name",
            None,
            123,
            session,
        )

        self.assertEqual(result, "unsigned-transaction")
        session.post.assert_called_once_with(
            "http://127.0.0.1:24891/arbitrary/resource/APP/My%20Name/delete",
            params={"fee": 123},
            timeout=15,
        )
        response.raise_for_status.assert_called_once_with()

    def test_build_named_delete_encodes_identifier(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.text = "unsigned-transaction"
        session = MagicMock()
        session.post.return_value = response

        build_arbitrary_delete(
            ctx,
            "JSON",
            "My Name",
            "profile/main",
            0,
            session,
        )

        session.post.assert_called_once_with(
            "http://127.0.0.1:24891/arbitrary/resource/JSON/"
            "My%20Name/profile%2Fmain/delete",
            params={"fee": 0},
            timeout=15,
        )

    def test_local_delete_uses_delete_method(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.json.return_value = True
        session = MagicMock()
        session.delete.return_value = response

        deleted = delete_local_arbitrary_resource(
            ctx,
            "WEBSITE",
            "My Name",
            "default",
            session,
        )

        self.assertTrue(deleted)
        session.delete.assert_called_once_with(
            "http://127.0.0.1:24891/arbitrary/resource/"
            "WEBSITE/My%20Name/default",
            timeout=15,
        )

    def test_build_app_publish_from_folder(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.text = "unsigned-transaction"
        session = MagicMock()
        session.post.return_value = response

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            (app_dir / "index.html").write_text("<h1>APP</h1>", encoding="utf-8")

            result = build_arbitrary_from_path(
                ctx,
                session,
                service="APP",
                name="My Name",
                identifier="default",
                local_path=str(app_dir),
                title="My App",
                description="Description",
                tags=["qortal", "app"],
                category="software",
                fee_atomic=123,
                preview=True,
            )

        self.assertEqual(result, "unsigned-transaction")
        session.post.assert_called_once_with(
            "http://127.0.0.1:24891/arbitrary/APP/My%20Name/default",
            params={
                "title": "My App",
                "description": "Description",
                "tags": ["qortal", "app"],
                "category": "SOFTWARE",
                "fee": 123,
                "preview": "true",
            },
            data=str(app_dir.resolve()),
            headers={"Content-Type": "text/plain"},
            timeout=15,
        )
        response.raise_for_status.assert_called_once_with()

    def test_build_app_publish_unpacks_single_root_zip(self) -> None:
        ctx = make_context()
        response = MagicMock()
        response.text = "unsigned-transaction"
        observed_publish_path: list[Path] = []

        def post_side_effect(*args, **kwargs):
            publish_path = Path(kwargs["data"])
            observed_publish_path.append(publish_path)
            self.assertTrue((publish_path / "index.html").is_file())
            self.assertTrue((publish_path / "assets" / "app.js").is_file())
            return response

        session = MagicMock()
        session.post.side_effect = post_side_effect

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "app.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("my-app/index.html", "<h1>APP</h1>")
                archive.writestr("my-app/assets/app.js", "console.log('app')")

            build_arbitrary_from_path(
                ctx,
                session,
                service="APP",
                name="My Name",
                identifier="default",
                local_path=str(zip_path),
            )

        self.assertEqual(len(observed_publish_path), 1)
        self.assertFalse(observed_publish_path[0].exists())

    def test_build_app_publish_rejects_zip_path_traversal(self) -> None:
        ctx = make_context()
        session = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "unsafe.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../escape.txt", "unsafe")
                archive.writestr("index.html", "<h1>APP</h1>")

            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                build_arbitrary_from_path(
                    ctx,
                    session,
                    service="APP",
                    name="My Name",
                    identifier="default",
                    local_path=str(zip_path),
                )

        session.post.assert_not_called()

    def test_build_app_publish_requires_root_index(self) -> None:
        ctx = make_context()
        session = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "home.html").write_text("missing index", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "requires index.html"):
                build_arbitrary_from_path(
                    ctx,
                    session,
                    service="APP",
                    name="My Name",
                    identifier="default",
                    local_path=temp_dir,
                )

        session.post.assert_not_called()

    def test_build_app_publish_enforces_metadata_byte_limit(self) -> None:
        ctx = make_context()
        session = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "index.html").write_text("<h1>APP</h1>", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "80 UTF-8 bytes"):
                build_arbitrary_from_path(
                    ctx,
                    session,
                    service="APP",
                    name="My Name",
                    identifier="default",
                    local_path=temp_dir,
                    title="é" * 41,
                )

        session.post.assert_not_called()


class QdnWorkflowTests(TestCase):
    def test_register_name_menu_registers_directly_without_owned_names(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch("qortium_cli.tools.get_account_names", return_value=[]) as get_names,
            patch("qortium_cli.tools.tx_name_register") as register_name,
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.print_stat"),
            patch("qortium_cli.tools.pause") as pause,
        ):
            tool_register_name(ctx)

        get_names.assert_called_once_with(
            ctx,
            ctx.account.account_address,
            session,
            limit=500,
        )
        register_name.assert_called_once_with(ctx)
        pause.assert_called_once()

    def test_register_name_menu_updates_existing_name(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        owned_names = ["First Name", "Second Name"]

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch("qortium_cli.tools.get_account_names", return_value=owned_names),
            patch("qortium_cli.tools.read_menu_choice", return_value="1"),
            patch("qortium_cli.tools.tx_name_update") as update_name,
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.print_section"),
            patch("qortium_cli.tools.print_stat"),
            patch("qortium_cli.tools.print_option"),
            patch("qortium_cli.tools.pause") as pause,
        ):
            tool_register_name(ctx)

        update_name.assert_called_once_with(ctx, owned_names)
        pause.assert_called_once()

    def test_register_name_menu_can_start_new_name_when_owned_names_exist(self) -> None:
        ctx = make_context()
        session_context = MagicMock()
        session_context.__enter__.return_value = MagicMock()

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch("qortium_cli.tools.get_account_names", return_value=["My Name"]),
            patch("qortium_cli.tools.read_menu_choice", return_value="2"),
            patch("qortium_cli.tools.tx_name_register") as register_name,
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.print_section"),
            patch("qortium_cli.tools.print_stat"),
            patch("qortium_cli.tools.print_option"),
            patch("qortium_cli.tools.pause") as pause,
        ):
            tool_register_name(ctx)

        register_name.assert_called_once_with(ctx)
        pause.assert_called_once()

    def test_name_register_can_cancel_with_blank_name(self) -> None:
        ctx = make_context()

        with (
            patch("qortium_cli.tools.prompt_str", return_value=""),
            patch("qortium_cli.tools._submit_builder_transaction") as submit_tx,
            patch("qortium_cli.tools.warn"),
        ):
            tx_name_register(ctx)

        submit_tx.assert_not_called()

    def test_name_update_builds_update_name_transaction(self) -> None:
        ctx = make_context()

        with (
            patch("qortium_cli.tools.read_menu_choice", return_value="2"),
            patch(
                "qortium_cli.tools.prompt_str",
                side_effect=["Renamed Name", "{\"bio\":\"updated\"}"],
            ),
            patch("qortium_cli.tools.prompt_decimal", return_value=Decimal("0")),
            patch("qortium_cli.tools.prompt_int", return_value=0),
            patch(
                "qortium_cli.tools.to_base58_pubkey",
                return_value="owner-public-key",
            ),
            patch("qortium_cli.tools._submit_builder_transaction") as submit_tx,
            patch("qortium_cli.tools.print_section"),
            patch("qortium_cli.tools.print_option"),
        ):
            tx_name_update(ctx, ["First Name", "Second Name"])

        submit_tx.assert_called_once_with(
            ctx,
            "/names/update",
            "UPDATE_NAME",
            {
                "ownerPublicKey": "owner-public-key",
                "name": "Second Name",
                "newName": "Renamed Name",
                "newData": "{\"bio\":\"updated\"}",
            },
            "0.00000000",
            0,
        )

    def test_name_update_can_cancel_name_selection_with_zero(self) -> None:
        ctx = make_context()

        with (
            patch("qortium_cli.tools.read_menu_choice", return_value="0"),
            patch("qortium_cli.tools._submit_builder_transaction") as submit_tx,
            patch("qortium_cli.tools.print_section"),
            patch("qortium_cli.tools.print_option"),
            patch("qortium_cli.tools.warn"),
        ):
            tx_name_update(ctx, ["My Name"])

        submit_tx.assert_not_called()

    def test_resource_tuple_normalizes_missing_identifier(self) -> None:
        self.assertEqual(
            _qdn_resource_tuple(
                {"service": "website", "name": "My Name", "identifier": None}
            ),
            ("WEBSITE", "My Name", "default"),
        )

    def test_select_owned_resource_returns_exact_tuple(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with (
            patch("qortium_cli.tools.prompt_str", side_effect=["profile", "APP"]),
            patch(
                "qortium_cli.tools.get_account_names",
                return_value=["My Name"],
            ),
            patch(
                "qortium_cli.tools.search_arbitrary_resources",
                return_value=[
                    {
                        "service": "APP",
                        "name": "My Name",
                        "identifier": "profile-main",
                        "status": {"title": "Published"},
                        "metadata": {"title": "Profile"},
                    }
                ],
            ) as search_resources,
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch("qortium_cli.tools.read_menu_choice", return_value="1"),
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.print_stat"),
            patch("qortium_cli.tools.print_option"),
        ):
            selected = select_qdn_resource(ctx, hosted_only=False)

        self.assertEqual(selected, ("APP", "My Name", "profile-main"))
        search_resources.assert_called_once_with(
            ctx,
            session,
            query="profile",
            service="APP",
            names=["My Name"],
            limit=10,
            offset=0,
        )

    def test_lookup_owned_resource_continues_to_on_chain_delete(self) -> None:
        ctx = make_context()
        selected = ("APP", "My Name", "profile-main")

        with (
            patch("qortium_cli.tools.read_menu_choice", return_value="1"),
            patch("qortium_cli.tools.select_qdn_resource", return_value=selected),
            patch(
                "qortium_cli.tools._delete_selected_qdn_resource_on_chain"
            ) as delete_selected,
            patch("qortium_cli.tools.print_option"),
        ):
            browse_qdn_resources(ctx)

        delete_selected.assert_called_once_with(ctx, selected)

    def test_lookup_hosted_resource_continues_to_local_delete(self) -> None:
        ctx = make_context()
        selected = ("WEBSITE", "My Name", "default")

        with (
            patch("qortium_cli.tools.read_menu_choice", return_value="2"),
            patch("qortium_cli.tools.ensure_api_key") as ensure_key,
            patch("qortium_cli.tools.select_qdn_resource", return_value=selected),
            patch(
                "qortium_cli.tools._delete_selected_qdn_resource_locally"
            ) as delete_selected,
            patch("qortium_cli.tools.print_option"),
        ):
            browse_qdn_resources(ctx)

        ensure_key.assert_called_once_with(ctx)
        delete_selected.assert_called_once_with(ctx, selected)

    def test_on_chain_delete_checks_owner_and_submits(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch(
                "qortium_cli.tools.get_name_info",
                return_value={"name": "My Name", "owner": ctx.account.account_address},
            ),
            patch(
                "qortium_cli.tools.build_arbitrary_delete",
                return_value="unsigned-transaction",
            ) as build_delete,
            patch("qortium_cli.tools.sign_tx", return_value="signed-transaction"),
            patch(
                "qortium_cli.tools.process_tx",
                return_value={"signature": "delete-signature"},
            ),
        ):
            _submit_arbitrary_delete_transaction(
                ctx,
                "APP",
                "My Name",
                "default",
                Decimal("0.00000123"),
            )

        build_delete.assert_called_once_with(
            ctx,
            "APP",
            "My Name",
            None,
            123,
            session,
        )

    def test_on_chain_delete_rejects_non_owner(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with (
            patch("qortium_cli.tools.make_session", return_value=session_context),
            patch(
                "qortium_cli.tools.get_name_info",
                return_value={"name": "My Name", "owner": "Qother-owner"},
            ),
            patch("qortium_cli.tools.build_arbitrary_delete") as build_delete,
        ):
            with self.assertRaisesRegex(RuntimeError, "not the configured wallet"):
                _submit_arbitrary_delete_transaction(
                    ctx,
                    "APP",
                    "My Name",
                    "default",
                    Decimal("0"),
                )

        build_delete.assert_not_called()

    def test_app_publish_checks_owner_and_submits(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            (app_dir / "index.html").write_text("<h1>APP</h1>", encoding="utf-8")

            with (
                patch("qortium_cli.tools.make_session", return_value=session_context),
                patch(
                    "qortium_cli.tools.get_name_info",
                    return_value={"name": "My Name", "owner": ctx.account.account_address},
                ),
                patch(
                    "qortium_cli.tools.build_arbitrary_from_path",
                    return_value="unsigned-transaction",
                ) as build_publish,
                patch("qortium_cli.tools.sign_tx", return_value="signed-transaction"),
                patch(
                    "qortium_cli.tools.process_tx",
                    return_value={"signature": "publish-signature"},
                ),
            ):
                _submit_arbitrary_publish_transaction(
                    ctx,
                    service="APP",
                    name="My Name",
                    identifier="default",
                    local_path=str(app_dir),
                    title="My App",
                    description="Description",
                    tags=["app"],
                    category="SOFTWARE",
                    fee=Decimal("0"),
                )

        build_publish.assert_called_once_with(
            ctx,
            session,
            service="APP",
            name="My Name",
            identifier="default",
            local_path=str(app_dir.resolve()),
            title="My App",
            description="Description",
            tags=["app"],
            category="SOFTWARE",
            fee_atomic=None,
            preview=False,
        )

    def test_app_publish_rejects_non_owner(self) -> None:
        ctx = make_context()
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            (app_dir / "index.html").write_text("<h1>APP</h1>", encoding="utf-8")

            with (
                patch("qortium_cli.tools.make_session", return_value=session_context),
                patch(
                    "qortium_cli.tools.get_name_info",
                    return_value={"name": "My Name", "owner": "Qother-owner"},
                ),
                patch("qortium_cli.tools.build_arbitrary_from_path") as build_publish,
            ):
                with self.assertRaisesRegex(RuntimeError, "not the configured wallet"):
                    _submit_arbitrary_publish_transaction(
                        ctx,
                        service="APP",
                        name="My Name",
                        identifier="default",
                        local_path=str(app_dir),
                        title="",
                        description="",
                        tags=[],
                        category="UNCATEGORIZED",
                        fee=Decimal("0"),
                    )

        build_publish.assert_not_called()
