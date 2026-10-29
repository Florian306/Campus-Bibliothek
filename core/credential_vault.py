"""Windows Data Protection API (DPAPI) credential vault for Buchsortierer.
Encrypts and decrypts sensitive configuration secrets (passwords, private calendar URLs, API tokens)
using the native Windows CryptProtectData / CryptUnprotectData API bound to the active Windows user account.
"""

import base64
import ctypes
import ctypes.wintypes
import re
from typing import Any, Dict, Tuple

DPAPI_PREFIX = "dpapi:"
CRYPTPROTECT_UI_FORBIDDEN = 0x01

SENSITIVE_CONFIG_KEYS = (
    "mail_password",
    "cal_url",
    "github_token",
    "api_key",
    "deepl_api_key",
)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def is_protected_secret(value: Any) -> bool:
    """Returns True if the given value is already encrypted with DPAPI."""
    return isinstance(value, str) and value.startswith(DPAPI_PREFIX)


def protect_secret(plaintext: str) -> str:
    """Encrypts a plaintext string using Windows DPAPI and returns 'dpapi:<base64>'.
    Returns empty string if input is empty, or returns input unchanged if already encrypted.
    """
    if not plaintext:
        return ""
    if is_protected_secret(plaintext):
        return plaintext

    try:
        raw_bytes = plaintext.encode("utf-8")
        buf = ctypes.create_string_buffer(raw_bytes, len(raw_bytes))
        blob_in = _DATA_BLOB(len(raw_bytes), buf)
        blob_out = _DATA_BLOB()

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        res = crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "BuchsortiererCredentialVault",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not res:
            return plaintext

        try:
            encrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

        encoded = base64.b64encode(encrypted_bytes).decode("ascii")
        return f"{DPAPI_PREFIX}{encoded}"
    except Exception:
        return plaintext


def unprotect_secret(value: str) -> str:
    """Decrypts a 'dpapi:<base64>' string using Windows DPAPI.
    If the value does not start with 'dpapi:', returns it as-is for seamless migration.
    """
    if not value or not isinstance(value, str):
        return ""
    if not is_protected_secret(value):
        return value

    b64_payload = value[len(DPAPI_PREFIX):].strip()
    if not b64_payload:
        return ""

    try:
        encrypted_bytes = base64.b64decode(b64_payload)
        buf = ctypes.create_string_buffer(encrypted_bytes, len(encrypted_bytes))
        blob_in = _DATA_BLOB(len(encrypted_bytes), buf)
        blob_out = _DATA_BLOB()

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        res = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not res:
            return ""

        try:
            decrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

        return decrypted_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def encrypt_config_dict(config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Returns a shallow copy of config_data with all sensitive keys DPAPI-encrypted for disk storage."""
    out = dict(config_data)
    for key in SENSITIVE_CONFIG_KEYS:
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = protect_secret(val.strip())
    return out


def decrypt_config_dict(config_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Decrypts all sensitive keys in-place and returns (decrypted_dict, had_plaintext_secrets)."""
    out = dict(config_data)
    had_plaintext = False
    for key in SENSITIVE_CONFIG_KEYS:
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            if is_protected_secret(val):
                out[key] = unprotect_secret(val)
            else:
                had_plaintext = True
    return out, had_plaintext


def mask_secret_url(url: str) -> str:
    """Masks private tokens and user identifiers in iCal/WebCal URLs for safe UI display and error logs."""
    if not url or not isinstance(url, str):
        return ""
    masked = url.strip()
    # Mask Google Calendar private token: /private-abcdef123456/ -> /private-********
    masked = re.sub(r"(/private-)[a-zA-Z0-9_\-]+", r"\1********", masked)
    # Mask long hex/token segments (16+ hex/alphanumeric chars in path)
    masked = re.sub(r"/[a-fA-F0-9]{16,}(?=/|$)", "/********", masked)
    # Mask query string parameters like ?token=... or ?key=...
    masked = re.sub(r"([?&](?:token|key|auth|pass|secret|pwd)=)[^&]+", r"\1********", masked, flags=re.IGNORECASE)
    return masked
