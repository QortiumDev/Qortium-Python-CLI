from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from qortium_cli.update_checker import (
    ReleaseInfo,
    parse_version_tag,
    record_update_check,
    release_from_github_payload,
    select_update_offers,
    should_check_for_updates,
)


def release(tag_name: str, prerelease: bool = False) -> ReleaseInfo:
    parsed = parse_version_tag(tag_name)
    assert parsed is not None
    return ReleaseInfo(
        tag_name=tag_name,
        version=parsed,
        prerelease=prerelease,
        html_url=f"https://example.test/{tag_name}",
    )


class UpdateCheckerTests(TestCase):
    def test_stable_version_is_newer_than_same_base_prerelease(self) -> None:
        prerelease = parse_version_tag("v0.4.0-preview.2")
        stable = parse_version_tag("v0.4.0")

        self.assertIsNotNone(prerelease)
        self.assertIsNotNone(stable)
        self.assertLess(prerelease, stable)

    def test_select_update_offers_prerelease_first_when_it_is_ahead(self) -> None:
        offers = select_update_offers(
            "0.3.0",
            [
                release("v0.3.1"),
                release("v0.4.0-preview.1", prerelease=True),
            ],
        )

        self.assertEqual(
            [offer.tag_name for offer in offers],
            ["v0.4.0-preview.1", "v0.3.1"],
        )

    def test_select_update_ignores_prerelease_when_stable_is_newer(self) -> None:
        offers = select_update_offers(
            "0.3.0",
            [
                release("v0.4.0"),
                release("v0.4.0-preview.2", prerelease=True),
            ],
        )

        self.assertEqual([offer.tag_name for offer in offers], ["v0.4.0"])

    def test_select_update_offers_stable_when_no_prerelease_is_ahead(self) -> None:
        offers = select_update_offers(
            "0.3.0",
            [
                release("v0.3.1"),
                release("v0.3.1-preview.1", prerelease=True),
            ],
        )

        self.assertEqual([offer.tag_name for offer in offers], ["v0.3.1"])

    def test_select_update_treats_prerelease_tag_as_prerelease(self) -> None:
        offers = select_update_offers(
            "0.3.0",
            [
                release("v0.4.0"),
                release("v0.4.0-preview.1"),
            ],
        )

        self.assertEqual([offer.tag_name for offer in offers], ["v0.4.0"])

    def test_select_update_can_offer_prerelease_when_no_stable_release_exists(self) -> None:
        offers = select_update_offers(
            "0.3.0",
            [release("v0.3.1-preview.1", prerelease=True)],
        )

        self.assertEqual([offer.tag_name for offer in offers], ["v0.3.1-preview.1"])

    def test_release_from_github_payload_skips_drafts_and_unknown_tags(self) -> None:
        self.assertIsNone(
            release_from_github_payload({"tag_name": "not-a-version", "draft": False})
        )
        self.assertIsNone(
            release_from_github_payload({"tag_name": "v0.3.1", "draft": True})
        )

        release_info = release_from_github_payload(
            {
                "tag_name": "v0.3.1",
                "prerelease": False,
                "html_url": "https://example.test/release",
            }
        )

        self.assertIsNotNone(release_info)
        self.assertEqual(release_info.tag_name, "v0.3.1")

    def test_should_check_for_updates_respects_daily_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)

            self.assertTrue(should_check_for_updates(settings_dir, now=1_000))
            record_update_check(settings_dir, "ok", now=1_000)
            self.assertFalse(should_check_for_updates(settings_dir, now=1_000 + 60))
            self.assertTrue(
                should_check_for_updates(settings_dir, now=1_000 + (24 * 60 * 60))
            )
