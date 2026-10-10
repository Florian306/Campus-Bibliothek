"""Configuration manager for Buchsortierer AI application.
Persists API keys, last used paths, and user options to a local JSON file.
Includes typed AppConfig dataclass with dictionary fallback compatibility.
"""

from dataclasses import asdict, dataclass, field
import json
import os
import sys
from typing import Any, Dict


CONFIG_FILE_NAME = "buchsortierer_config.json"


@dataclass
class AppConfig:
    """Typed application configuration model."""
    provider: str = "ollama"
    ollama_model: str = "qwen2.5vl:latest"
    api_key: str = ""
    last_directory: str = ""
    auto_rename: bool = True
    prefer_existing_dirs: bool = False
    dry_run: bool = False
    dark_mode: bool = True
    max_search_results: int = 50
    enable_cache: bool = True
    use_internal_reader: bool = True
    github_token: str = ""
    github_gist_id: str = ""
    github_auto_sync: bool = False
    app_version: str = "1.0.0"
    search_engines: list = field(default_factory=lambda: ["bing", "duckduckgo", "openalex", "wikipedia", "crossref"])

    def to_dict(self) -> Dict[str, Any]:
        """Converts dataclass to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Instantiates AppConfig from dict, filtering unknown keys safely."""
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


def get_app_dir() -> str:
    """Returns the persistent application directory, ensuring DB and configs survive PyInstaller execution."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        parent_dir = os.path.dirname(exe_dir)
        if os.path.exists(os.path.join(parent_dir, "library.db")):
            return parent_dir
        return exe_dir
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_user_data_dir() -> str:
    """Returns persistent application directory in %APPDATA%/Buchsortierer."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(base, "Buchsortierer")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_database_path() -> str:
    """Returns persistent SQLite path in %APPDATA%, migrating legacy DB on first launch."""
    user_db = os.path.join(get_user_data_dir(), "library.db")
    if os.path.isfile(user_db):
        return user_db

    # Check for existing DB in workspace or app dir
    legacy_db = os.path.join(get_app_dir(), "library.db")
    if os.path.isfile(legacy_db):
        try:
            import shutil
            shutil.copy2(legacy_db, user_db)
            return user_db
        except Exception:
            return legacy_db
    return user_db


def _get_legacy_config_path() -> str:
    return os.path.join(get_app_dir(), CONFIG_FILE_NAME)


def get_config_path() -> str:
    """Returns persistent config path in %APPDATA% (survives EXE rebuilds/moves)."""
    cfg_dir = get_user_data_dir()
    target = os.path.join(cfg_dir, CONFIG_FILE_NAME)
    if os.path.isfile(target):
        return target
    try:
        legacy = _get_legacy_config_path()
        if os.path.isfile(legacy):
            import shutil
            shutil.copy2(legacy, target)
        return target
    except Exception:
        return _get_legacy_config_path()


def load_app_config() -> AppConfig:
    """Loads configuration as a typed AppConfig object."""
    config_dict = load_config()
    return AppConfig.from_dict(config_dict)


def save_app_config(cfg: AppConfig) -> bool:
    """Saves typed AppConfig object to disk."""
    return save_config(cfg.to_dict())


def load_config() -> Dict[str, Any]:
    """Loads configuration dictionary from disk or returns defaults (100% backwards compatible)."""
    default_config: Dict[str, Any] = AppConfig().to_dict()

    config_path = get_config_path()
    if not os.path.isfile(config_path):
        return default_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                default_config.update(data)
    except Exception:
        pass

    return default_config


def save_config(config_data: Dict[str, Any]) -> bool:
    """Saves configuration dictionary to disk (atomic write)."""
    config_path = get_config_path()
    tmp_path = config_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, config_path)
        return True
    except Exception:
        return False


def get_books_storage_dir() -> str:
    """Detects and returns the active storage directory of books.
    Checks user configuration, existing books database paths, or default paths.
    """
    cfg = load_config()
    last_dir = cfg.get("last_directory", "").strip()
    if last_dir and os.path.isdir(last_dir):
        return last_dir

    # Fallback to database books paths
    try:
        import sqlite3
        db_path = os.path.join(get_app_dir(), "library.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT file_path FROM books WHERE file_path IS NOT NULL AND file_path != '' LIMIT 50;")
            paths = [r[0] for r in cur.fetchall()]
            conn.close()

            for p in paths:
                parent = os.path.dirname(p)
                if os.path.isdir(parent):
                    # Check for 'Bücher' in path
                    parts = parent.split(os.sep)
                    for i in range(len(parts), 0, -1):
                        cand = os.sep.join(parts[:i])
                        if os.path.basename(cand).lower() in ("bücher", "buecher", "books") and os.path.isdir(cand):
                            return cand
                    return parent
    except Exception:
        pass

    fallback = r"G:\Meine Ablage\Bücher"
    if os.path.isdir(fallback):
        return fallback

    return get_app_dir()


def get_inbox_directory() -> str:
    """Returns the dedicated Inbox staging directory (e.g. G:\\Meine Ablage\\Bücher\\_Inbox).
    Creates the directory automatically if it does not yet exist.
    """
    storage_dir = get_books_storage_dir()
    inbox_dir = os.path.join(storage_dir, "_Inbox")
    try:
        os.makedirs(inbox_dir, exist_ok=True)
    except Exception:
        # If write permission failed in storage_dir, fallback to user data dir
        fallback = os.path.join(get_user_data_dir(), "Inbox")
        os.makedirs(fallback, exist_ok=True)
        return fallback
    return inbox_dir
