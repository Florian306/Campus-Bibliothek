"""Crash Recovery & Auto-Rollback Guard for Campus-Bibliothek.
Tracks startup health, logs fatal boot exceptions, and triggers automatic rollback to previous release.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

GITHUB_REPO = "Florian306/Campus-Bibliothek"


def get_recovery_dir() -> str:
    """Returns local app data path dedicated to crash telemetry and rollback states."""
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(local_app_data, "CampusBibliothek", "recovery")
    os.makedirs(path, exist_ok=True)
    return path


def get_boot_state_file() -> str:
    return os.path.join(get_recovery_dir(), "boot_state.json")


def load_boot_state() -> Dict[str, Any]:
    state_file = get_boot_state_file()
    if os.path.isfile(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "current_version": "",
        "previous_version": "",
        "boot_success": True,
        "consecutive_crashes": 0,
        "last_error": "",
    }


def save_boot_state(state: Dict[str, Any]) -> None:
    try:
        with open(get_boot_state_file(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def mark_boot_started(version: str) -> None:
    """Marks that application startup has begun."""
    state = load_boot_state()
    if state.get("current_version") != version:
        state["previous_version"] = state.get("current_version") or ""
        state["current_version"] = version
        state["consecutive_crashes"] = 0

    state["boot_success"] = False
    state["consecutive_crashes"] = int(state.get("consecutive_crashes", 0)) + 1
    save_boot_state(state)


def mark_boot_success() -> None:
    """Marks that UI successfully initialized and rendered without fatal boot crash."""
    state = load_boot_state()
    state["boot_success"] = True
    state["consecutive_crashes"] = 0
    state["last_error"] = ""
    save_boot_state(state)


def fetch_previous_stable_release(current_ver: str) -> Optional[Tuple[str, str]]:
    """Finds the most recent previous stable release version and download URL from GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Campus-Bibliothek-CrashGuard",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
            for rel in releases:
                if rel.get("draft") or rel.get("prerelease"):
                    continue
                tag = rel.get("tag_name", "").lstrip("v").strip()
                if tag and tag != current_ver:
                    assets = rel.get("assets", [])
                    patch_url = None
                    setup_url = None
                    fallback_url = None
                    for a in assets:
                        aname = a.get("name", "").lower()
                        burl = a.get("browser_download_url")
                        if "patch" in aname and aname.endswith(".zip"):
                            patch_url = burl
                        elif "setup" in aname and aname.endswith(".exe"):
                            setup_url = burl
                        elif aname.endswith(".exe") or aname.endswith(".zip"):
                            fallback_url = burl
                    target_url = patch_url or setup_url or fallback_url
                    if target_url:
                        return tag, target_url
    except Exception:
        pass
    return None


def execute_rollback(download_url: str, version_tag: str) -> bool:
    """Downloads the previous release payload and executes installation."""
    temp_dir = tempfile.gettempdir()
    ext = ".zip" if download_url.lower().endswith(".zip") else ".exe"
    target_path = os.path.join(temp_dir, f"Campus-Bibliothek-Rollback-v{version_tag}{ext}")

    try:
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Campus-Bibliothek-RollbackGuard"},
        )
        with urllib.request.urlopen(req, timeout=45) as resp, open(target_path, "wb") as out_file:
            while True:
                chunk = resp.read(128 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)

        app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        exe_path = os.path.join(app_dir, "Buchsortierer.exe")

        if target_path.lower().endswith(".zip"):
            ps_script = (
                f"Start-Sleep -Milliseconds 1200; "
                f"Expand-Archive -Path '{target_path}' -DestinationPath '{app_dir}' -Force; "
                f"Start-Process -FilePath '{exe_path}'; "
                f"Remove-Item -Path '{target_path}' -Force -ErrorAction SilentlyContinue"
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        else:
            cmd = [target_path, "/VERYSILENT", "/SP-", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS"]
            subprocess.Popen(cmd)
        return True
    except Exception:
        return False
