import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from client import DownloaderClient
from module.cookie_store import CookieStore, CookieStoreError, default_cookie_path
from module.roblox import AsyncRobloxDownloader


TEST_COOKIE = "test-cookie-for-local-tests-only"


class MemoryValue:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class CookieStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings" / "cookie.dat"
        self.store = CookieStore(self.path)

    def test_cookie_survives_new_store_instance_and_can_be_replaced(self):
        self.store.save("  " + TEST_COOKIE + "  ")
        self.assertEqual(CookieStore(self.path).load(), TEST_COOKIE)
        self.store.save("replacement-test-cookie")
        self.assertEqual(CookieStore(self.path).load(), "replacement-test-cookie")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    @unittest.skipUnless(sys.platform == "win32", "Windows encryption")
    def test_windows_cookie_is_not_stored_as_plaintext(self):
        self.store.save(TEST_COOKIE)
        self.assertNotIn(TEST_COOKIE.encode(), self.path.read_bytes())
        self.assertEqual(CookieStore(self.path).load(), TEST_COOKIE)

    def test_clear_and_blank_save_remove_the_saved_cookie(self):
        self.store.clear()
        self.assertEqual(self.store.load(), "")
        self.store.save(TEST_COOKIE)
        self.store.clear()
        self.assertEqual(CookieStore(self.path).load(), "")
        self.assertFalse(self.path.exists())
        self.store.save(TEST_COOKIE)
        self.store.save(" ")
        self.assertFalse(self.path.exists())

    def test_failed_write_preserves_previous_cookie(self):
        self.store.save(TEST_COOKIE)
        with patch("module.cookie_store.os.replace", side_effect=PermissionError("test failure")):
            with self.assertRaises(CookieStoreError):
                self.store.save("new-cookie")
        self.assertEqual(CookieStore(self.path).load(), TEST_COOKIE)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    @unittest.skipUnless(sys.platform == "win32", "Windows encryption")
    def test_encryption_failure_does_not_fall_back_to_plaintext(self):
        with patch("module.cookie_store._windows_crypt", side_effect=CookieStoreError("test failure")):
            with self.assertRaises(CookieStoreError):
                self.store.save(TEST_COOKIE)
        self.assertFalse(self.path.exists())

    def test_unreadable_record_is_reported_and_preserved(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"unreadable-cookie-record")
        with self.assertRaises(CookieStoreError):
            self.store.load()
        self.assertEqual(self.path.read_bytes(), b"unreadable-cookie-record")

    @unittest.skipUnless(sys.platform == "win32", "Windows configuration path")
    def test_storage_location_does_not_follow_download_folder(self):
        with patch.dict("os.environ", {"LOCALAPPDATA": self.temp.name}):
            self.assertEqual(
                default_cookie_path(),
                Path(self.temp.name) / "RobloxAssetDownloader" / "cookie.dat",
            )

    def test_legacy_cookie_file_can_be_disabled_for_the_gui(self):
        (Path(self.temp.name) / "roblox_cookie.txt").write_text(TEST_COOKIE, encoding="utf-8")
        downloader = AsyncRobloxDownloader(runtime_dir=self.temp.name, load_cookie_file=False)
        self.assertIsNone(downloader.cookie)
        legacy = AsyncRobloxDownloader(runtime_dir=self.temp.name)
        self.assertEqual(legacy.cookie, TEST_COOKIE)


class ClientCookieTests(unittest.TestCase):
    def client(self, store=None, value=TEST_COOKIE):
        client = DownloaderClient.__new__(DownloaderClient)
        client.cookie_store = store if store is not None else Mock()
        client._cookie_load_failed = False
        client.cookie = MemoryValue(value)
        client._append_log = Mock()
        client.root = Mock()
        return client

    def test_launch_loads_saved_cookie_without_logging_it(self):
        client = self.client(value="")
        client.cookie_store.load.return_value = TEST_COOKIE
        client._load_saved_cookie()
        self.assertEqual(client.cookie.get(), TEST_COOKIE)
        self.assertNotIn(TEST_COOKIE, str(client._append_log.call_args_list))

    def test_save_and_normal_close_persist_current_value(self):
        client = self.client()
        self.assertTrue(client._save_cookie())
        client.cookie_store.save.assert_called_once_with(TEST_COOKIE)
        client.cookie_store.reset_mock()
        client.cookie.set("replacement-test-cookie")
        client._on_close()
        client.cookie_store.save.assert_called_once_with("replacement-test-cookie")
        client.root.destroy.assert_called_once()
        self.assertNotIn(TEST_COOKIE, str(client._append_log.call_args_list))

    def test_download_automatically_saves_cookie(self):
        client = self.client()
        client.worker = None
        client._collect_config = Mock(return_value={"cookie": TEST_COOKIE})
        client._clear_log = Mock()
        client.status = Mock()
        client.start_button = Mock()
        with patch("client.threading.Thread") as thread:
            client._start_download()
        client.cookie_store.save.assert_called_once_with(TEST_COOKIE)
        thread.return_value.start.assert_called_once()

    def test_clear_removes_saved_value_and_empties_input(self):
        client = self.client()
        client._clear_saved_cookie()
        client.cookie_store.clear.assert_called_once()
        self.assertEqual(client.cookie.get(), "")

    def test_failed_clear_keeps_current_input(self):
        client = self.client()
        client.cookie_store.clear.side_effect = CookieStoreError("Cannot clear")
        with patch("client.messagebox.showerror") as error:
            client._clear_saved_cookie()
        self.assertEqual(client.cookie.get(), TEST_COOKIE)
        error.assert_called_once()

    def test_failed_load_does_not_delete_saved_record_on_close(self):
        client = self.client(value="")
        client.cookie_store.load.side_effect = CookieStoreError("Cannot unlock")
        client._load_saved_cookie()
        client._on_close()
        client.cookie_store.save.assert_not_called()
        client.cookie_store.clear.assert_not_called()
        client.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
