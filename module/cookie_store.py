"""Persist the desktop client's cookie independently of the output directory."""
import ctypes
import os
import sys
import tempfile
from pathlib import Path


DPAPI_HEADER = b"RobloxAssetDownloader-DPAPI-1\n"
TEXT_HEADER = b"RobloxAssetDownloader-TEXT-1\n"


class CookieStoreError(Exception):
    pass


def default_cookie_path():
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "RobloxAssetDownloader" / "cookie.dat"


def _windows_crypt(data, decrypt=False):
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = DataBlob()
    # Current-user scope; never prompt or fall back to plaintext on Windows.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise CookieStoreError("Windows could not protect or unlock the saved cookie.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(result.data)


class CookieStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_cookie_path()

    def load(self):
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise CookieStoreError("Could not read the saved cookie.") from exc
        try:
            if data.startswith(DPAPI_HEADER) and sys.platform == "win32":
                return _windows_crypt(data[len(DPAPI_HEADER):], decrypt=True).decode("utf-8")
            if data.startswith(TEXT_HEADER) and sys.platform != "win32":
                return data[len(TEXT_HEADER):].decode("utf-8")
        except UnicodeError as exc:
            raise CookieStoreError("The saved cookie could not be decoded. Save it again.") from exc
        raise CookieStoreError("The saved cookie format is unreadable. Save it again.")

    def save(self, cookie):
        cookie = cookie.strip()
        if not cookie:
            self.clear()
            return
        raw = cookie.encode("utf-8")
        if sys.platform == "win32":
            data = DPAPI_HEADER + _windows_crypt(raw)
        else:
            data = TEXT_HEADER + raw
        temporary_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # NamedTemporaryFile restricts access to the owner on POSIX.
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(data)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise CookieStoreError("Could not save the cookie. Check the configuration folder permissions.") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def clear(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise CookieStoreError("Could not clear the saved cookie.") from exc
