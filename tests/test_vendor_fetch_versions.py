"""Static checks for the Windows vendor and release build pipeline."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-installer.yml"
FETCHER = ROOT / "packaging" / "fetch_vendor_windows.ps1"


def test_release_workflow_runs_the_vendor_fetcher() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "packaging/fetch_vendor_windows.ps1" in workflow
    assert "contents: write" in workflow
    assert "Publish latest GitHub Release" in workflow


def test_vlc_is_resolved_from_videolan_latest_stable_index() -> None:
    script = FETCHER.read_text(encoding="utf-8")
    assert 'vlc/last/win64/' in script
    assert "Resolve-LatestVlcRelease" in script
    assert 'VlcVersion = "3.0.21"' not in script
    assert re.search(r"vlc-.*win64\\\\?\.7z", script) or "win64\\.7z" in script


def test_vlc_archive_is_verified_against_upstream_sha256() -> None:
    script = FETCHER.read_text(encoding="utf-8")
    assert "${VlcUrl}.sha256" in script
    assert "Assert-Sha256 $VlcArchive $VlcChecksum" in script
    assert "Get-FileHash" in script


def test_webview2_remains_on_unversioned_evergreen_endpoints() -> None:
    script = FETCHER.read_text(encoding="utf-8")
    assert "api/v2/package/Microsoft.Web.WebView2" in script
    assert "LinkId=2124703" in script
    assert 'WebView2Version = ' in script


def test_successful_main_build_publishes_the_latest_release() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "tag_name: ${{ steps.release.outputs.tag }}" in workflow
    assert "make_latest: true" in workflow
    assert "SHA256SUMS.txt" in workflow


def test_release_version_is_consistent_across_build_tools() -> None:
    version = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)',
        (ROOT / "core/version.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    ).group(1)
    iss_version = re.search(
        r'^#define MyAppVersion\s+["\']([^"\']+)',
        (ROOT / "packaging/installer/Halcyon.iss").read_text(encoding="utf-8"),
        re.MULTILINE,
    ).group(1)
    fallback = re.search(
        r'^_FALLBACK_VERSION\s*=\s*["\']([^"\']+)',
        (ROOT / "tools/build_nuitka.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    ).group(1)
    assert version == iss_version == fallback == "1.3.3"


def test_local_panel_follows_the_filtered_current_row() -> None:
    panel = (ROOT / "modes/local/LocalPanel.qml").read_text(encoding="utf-8")
    assert "model: root.viewModel" in panel
    assert "required property int sourceIndex" in panel
    assert "Actions.playIndex(sourceIndex)" in panel
    assert "positionViewAtIndex(viewModel.currentIndex" in panel
