"""GitHub Release & Auto-Updater Checker for Campus-Bibliothek.
Polls GitHub Releases API for Florian306/Campus-Bibliothek to detect new versions.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

GITHUB_REPO = "Florian306/Campus-Bibliothek"
CURRENT_VERSION = "1.0.6"


def check_for_updates() -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Checks if a newer release is available on GitHub.
    Returns: (update_available, latest_version, download_url, release_notes)
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Campus-Bibliothek-Updater",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag_name = data.get("tag_name", "").lstrip("v").strip()
            if not tag_name:
                return False, None, None, None

            # Compare semantic versions
            if _is_version_greater(tag_name, CURRENT_VERSION):
                # Look for installer Setup.exe first, fallback to Buchsortierer.exe
                download_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")
                assets = data.get("assets", [])
                # First pass: find setup installer
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if "setup" in name and name.endswith(".exe"):
                        download_url = asset.get("browser_download_url", download_url)
                        break
                else:
                    # Second pass: any executable
                    for asset in assets:
                        name = asset.get("name", "").lower()
                        if name.endswith(".exe") or name.endswith(".zip"):
                            download_url = asset.get("browser_download_url", download_url)
                            break
                notes = data.get("body", "Keine Versionshinweise vorhanden.")
                return True, tag_name, download_url, notes
            return False, tag_name, None, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Repository or release not published yet
            return False, None, None, None
        return False, None, None, f"HTTP Fehler {e.code}"
    except Exception as e:
        return False, None, None, str(e)


def _is_version_greater(remote: str, current: str) -> bool:
    """Compares two semver version strings."""
    try:
        def parse_parts(v: str):
            return [int(x) for x in v.split(".") if x.isdigit()]
        r_parts = parse_parts(remote)
        c_parts = parse_parts(current)
        return r_parts > c_parts
    except Exception:
        return remote != current
