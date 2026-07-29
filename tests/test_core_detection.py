from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qortium_cli.core_detection import detect_local_core_api_key


def write_fake_core_process(
    proc_root: Path,
    pid: int,
    cwd: Path,
    *,
    api_key: str,
    api_port: int,
) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "qortium.jar").write_text("placeholder", encoding="utf-8")
    (cwd / "settings.json").write_text(
        f'{{"apiPort": {api_port}, "apiKeyPath": "."}}\n',
        encoding="utf-8",
    )
    (cwd / "apikey.txt").write_text(api_key + "\n", encoding="utf-8")

    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True)
    proc_dir.joinpath("cmdline").write_bytes(b"java\0-jar\0qortium.jar\0settings.json\0")
    cwd_entry = proc_dir / "cwd"
    try:
        cwd_entry.symlink_to(cwd, target_is_directory=True)
    except OSError:
        cwd_entry.write_text(str(cwd), encoding="utf-8")


class CoreDetectionTests(TestCase):
    def test_detects_managed_windows_runtime_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            appdata = Path(tmp)
            managed_root = appdata / "qortium-core"
            runtime = managed_root / "runtime"
            install = managed_root / "install"
            runtime.mkdir(parents=True)
            install.mkdir(parents=True)
            settings_path = runtime / "settings-preview-local.json"
            settings_path.write_text(
                '{"apiPort": 24891, "apiKeyPath": "."}\n',
                encoding="utf-8",
            )
            (runtime / "apikey.txt").write_text(
                "managed-runtime-key\n",
                encoding="utf-8",
            )
            (managed_root / "current.json").write_text(
                (
                    '{"runtimePath": '
                    f'"{runtime.as_posix()}", '
                    '"jarPath": '
                    f'"{(install / "qortium.jar").as_posix()}"'
                    "}\n"
                ),
                encoding="utf-8",
            )

            with (
                patch.dict("os.environ", {"APPDATA": str(appdata)}, clear=False),
                patch("qortium_cli.core_detection._iter_proc_dirs", return_value=[]),
            ):
                result = detect_local_core_api_key("http://127.0.0.1:24891")

        self.assertIsNotNone(result)
        self.assertEqual(result.api_key, "managed-runtime-key")
        self.assertEqual(result.settings_path, settings_path.resolve())

    def test_detects_api_key_for_matching_local_core_port(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc_root = root / "proc"
            write_fake_core_process(
                proc_root,
                101,
                root / "core",
                api_key="detected-api-key",
                api_port=24891,
            )

            result = detect_local_core_api_key("http://127.0.0.1:24891", proc_root=proc_root)

            self.assertIsNotNone(result)
            self.assertEqual(result.api_key, "detected-api-key")
            self.assertEqual(result.pid, 101)
            self.assertEqual(result.api_key_path, (root / "core" / "apikey.txt").resolve())

    def test_prefers_process_matching_selected_endpoint_port(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc_root = root / "proc"
            write_fake_core_process(
                proc_root,
                101,
                root / "mainnet-core",
                api_key="mainnet-api-key",
                api_port=14891,
            )
            write_fake_core_process(
                proc_root,
                202,
                root / "preview-core",
                api_key="preview-api-key",
                api_port=24891,
            )

            result = detect_local_core_api_key("http://localhost:24891", proc_root=proc_root)

            self.assertIsNotNone(result)
            self.assertEqual(result.api_key, "preview-api-key")
            self.assertEqual(result.pid, 202)

    def test_rejects_ambiguous_matching_processes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc_root = root / "proc"
            write_fake_core_process(
                proc_root,
                101,
                root / "preview-core-a",
                api_key="preview-api-key-a",
                api_port=24891,
            )
            write_fake_core_process(
                proc_root,
                202,
                root / "preview-core-b",
                api_key="preview-api-key-b",
                api_port=24891,
            )

            result = detect_local_core_api_key("http://localhost:24891", proc_root=proc_root)

            self.assertIsNone(result)

    def test_ignores_known_non_matching_core_port(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc_root = root / "proc"
            write_fake_core_process(
                proc_root,
                101,
                root / "mainnet-core",
                api_key="mainnet-api-key",
                api_port=14891,
            )

            result = detect_local_core_api_key("http://localhost:24891", proc_root=proc_root)

            self.assertIsNone(result)

    def test_ignores_non_local_endpoint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc_root = root / "proc"
            write_fake_core_process(
                proc_root,
                101,
                root / "core",
                api_key="detected-api-key",
                api_port=24891,
            )

            result = detect_local_core_api_key("http://node.example.com:24891", proc_root=proc_root)

            self.assertIsNone(result)
