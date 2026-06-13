from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from typing import Any, Iterable

import requests

from qortium_cli.constants import APP_VERSION, C_TEXT, DIM, RESET
from qortium_cli.ui import pause, print_option, print_section, warn

GITHUB_RELEASES_URL = "https://api.github.com/repos/QortiumDev/Qortium-Python-CLI/releases"
GITHUB_REPO_URL = "https://github.com/QortiumDev/Qortium-Python-CLI"
UPDATE_STATE_FILENAME = "update_state.json"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_CHECK_TIMEOUT_SECONDS = 3

_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[-_]?([A-Za-z][A-Za-z0-9]*)(?:[._-]?(\d+))?)?$"
)
_PRERELEASE_RANK = {
    "dev": 0,
    "alpha": 1,
    "a": 1,
    "beta": 2,
    "b": 2,
    "preview": 3,
    "pre": 3,
    "rc": 4,
}


@total_ordering
@dataclass(frozen=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease_label: str = ""
    prerelease_number: int = 0

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ParsedVersion):
            return NotImplemented

        base = (self.major, self.minor, self.patch)
        other_base = (other.major, other.minor, other.patch)
        if base != other_base:
            return base < other_base

        if self.is_prerelease != other.is_prerelease:
            return self.is_prerelease

        return self._prerelease_key() < other._prerelease_key()

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease_label)

    def _prerelease_key(self) -> tuple[int, str, int]:
        label = self.prerelease_label.lower()
        return (
            _PRERELEASE_RANK.get(label, 99),
            label,
            self.prerelease_number,
        )


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    version: ParsedVersion
    prerelease: bool
    name: str = ""
    html_url: str = ""
    published_at: str = ""

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease or self.version.is_prerelease

    @property
    def label(self) -> str:
        kind = "prerelease" if self.is_prerelease else "stable"
        return f"{self.tag_name} ({kind})"


def parse_version_tag(tag_name: str) -> ParsedVersion | None:
    match = _VERSION_RE.match(tag_name.strip())
    if not match:
        return None

    prerelease_label = (match.group(4) or "").lower()
    prerelease_number = int(match.group(5) or "0")
    return ParsedVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease_label=prerelease_label,
        prerelease_number=prerelease_number,
    )


def release_from_github_payload(payload: dict[str, Any]) -> ReleaseInfo | None:
    if payload.get("draft"):
        return None

    tag_name = str(payload.get("tag_name") or "").strip()
    version = parse_version_tag(tag_name)
    if version is None:
        return None

    return ReleaseInfo(
        tag_name=tag_name,
        version=version,
        prerelease=bool(payload.get("prerelease")) or version.is_prerelease,
        name=str(payload.get("name") or tag_name),
        html_url=str(payload.get("html_url") or f"{GITHUB_REPO_URL}/releases/tag/{tag_name}"),
        published_at=str(payload.get("published_at") or ""),
    )


def releases_from_github_payload(payloads: Iterable[dict[str, Any]]) -> list[ReleaseInfo]:
    releases: list[ReleaseInfo] = []
    for payload in payloads:
        release = release_from_github_payload(payload)
        if release is not None:
            releases.append(release)
    return releases


def fetch_github_releases(timeout_seconds: int = UPDATE_CHECK_TIMEOUT_SECONDS) -> list[ReleaseInfo]:
    response = requests.get(
        GITHUB_RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "qortium-cli-update-checker",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return releases_from_github_payload(
        item for item in payload if isinstance(item, dict)
    )


def select_update_offers(
    current_version: str,
    releases: Iterable[ReleaseInfo],
) -> list[ReleaseInfo]:
    current = parse_version_tag(current_version)
    if current is None:
        return []

    release_list = list(releases)
    stable_releases = [release for release in release_list if not release.is_prerelease]
    prereleases = [release for release in release_list if release.is_prerelease]

    newest_stable = max(stable_releases, key=lambda release: release.version, default=None)
    newest_eligible_prerelease = max(
        (
            release
            for release in prereleases
            if release.version > current
            and (newest_stable is None or release.version > newest_stable.version)
        ),
        key=lambda release: release.version,
        default=None,
    )

    offers: list[ReleaseInfo] = []
    if newest_eligible_prerelease is not None:
        offers.append(newest_eligible_prerelease)
    if newest_stable is not None and newest_stable.version > current:
        offers.append(newest_stable)
    return offers


def _state_path(settings_dir: Path) -> Path:
    return settings_dir / UPDATE_STATE_FILENAME


def _read_update_state(settings_dir: Path) -> dict[str, Any]:
    try:
        raw = _state_path(settings_dir).read_text(encoding="utf-8")
        state = json.loads(raw)
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_update_state(settings_dir: Path, state: dict[str, Any]) -> None:
    try:
        settings_dir.mkdir(parents=True, exist_ok=True)
        _state_path(settings_dir).write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def should_check_for_updates(settings_dir: Path, now: float | None = None) -> bool:
    state = _read_update_state(settings_dir)
    last_checked_at = state.get("last_checked_at")
    try:
        last_checked = float(last_checked_at)
    except (TypeError, ValueError):
        return True

    now = time.time() if now is None else now
    return now - last_checked >= UPDATE_CHECK_INTERVAL_SECONDS


def record_update_check(settings_dir: Path, status: str, now: float | None = None) -> None:
    _write_update_state(
        settings_dir,
        {
            "last_checked_at": time.time() if now is None else now,
            "status": status,
        },
    )


def update_checks_enabled() -> bool:
    disabled = str(os.environ.get("QORTIUM_CLI_NO_UPDATE_CHECK", "") or "").strip()
    if disabled == "1":
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _print_update_notice(offers: list[ReleaseInfo]) -> None:
    print()
    print_section("Updates")
    warn("A newer Qortium CLI release is available.")
    for index, release in enumerate(offers, start=1):
        print_option(str(index), release.label)
        print(C_TEXT + f"   {release.html_url}" + RESET)
        print(
            C_TEXT
            + f'   pipx install --force "git+{GITHUB_REPO_URL}.git@{release.tag_name}"'
            + RESET
        )
    print(DIM + "Restart qortium-cli after updating." + RESET)


def maybe_notify_available_updates(settings_dir: Path) -> None:
    if not update_checks_enabled():
        return
    if not should_check_for_updates(settings_dir):
        return

    try:
        releases = fetch_github_releases()
    except requests.RequestException:
        record_update_check(settings_dir, "failed")
        return

    offers = select_update_offers(APP_VERSION, releases)
    record_update_check(settings_dir, "ok" if offers else "current")
    if not offers:
        return

    _print_update_notice(offers)
    pause()
