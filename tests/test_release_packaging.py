from pathlib import Path
from unittest import TestCase
from xml.etree import ElementTree

from qortium_cli.constants import APP_VERSION


ROOT = Path(__file__).resolve().parent.parent


class ReleasePackagingTests(TestCase):
    def test_release_workflow_uses_native_single_download_formats(self) -> None:
        workflow = (ROOT / ".github/workflows/build-artifacts.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("qortium-cli-windows-x86_64.exe", workflow)
        self.assertIn("qortium-cli-linux-x86_64.AppImage", workflow)
        self.assertIn("qortium-cli-macos-arm64.dmg", workflow)
        self.assertNotIn(".tar.gz", workflow)
        self.assertNotIn("Compress-Archive", workflow)
        self.assertIn("generate_release_notes: false", workflow)

    def test_appimage_definition_opens_in_a_terminal(self) -> None:
        desktop = (ROOT / "packaging/linux/qortium-cli.desktop").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "scripts/package_linux_appimage.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("Terminal=true", desktop)
        self.assertIn('ln -s "usr/bin/qortium-cli-linux" "${APPDIR}/AppRun"', script)
        self.assertIn("APPIMAGETOOL_SHA256=", script)
        self.assertIn('"${OUTPUT_PATH}" --self-check', script)

    def test_macos_bundle_metadata_and_mounted_image_are_verified(self) -> None:
        template = (ROOT / "packaging/macos/Info.plist.in").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "scripts/package_macos_dmg.sh").read_text(encoding="utf-8")
        plist = ElementTree.fromstring(template.replace("@VERSION@", APP_VERSION))

        values = list(plist.iter("string"))
        self.assertTrue(any(value.text == "dev.qortium.cli" for value in values))
        self.assertTrue(any(value.text == APP_VERSION for value in values))
        self.assertIn("hdiutil verify", script)
        self.assertIn("hdiutil attach", script)
        self.assertIn("Contents/Resources/qortium-cli-macos", script)
        self.assertIn("--self-check", script)
