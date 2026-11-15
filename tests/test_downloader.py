import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

from client import DownloaderClient
from module.roblox import AsyncRobloxDownloader


BINARY_ROBLOX = b"<roblox!\x89\xff\r\n\x1a\n\x00\x00test animation bytes"
XML_ROBLOX = b'<?xml version="1.0"?><roblox version="4"></roblox>'


class Response:
    def __init__(self, content, status=200, content_type="application/octet-stream"):
        self.content = content
        self.status = status
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def read(self):
        return self.content


class AssetSession:
    """Simulate only the HTTP boundary; exercise the real download/save pipeline."""

    def __init__(self, asset_type=24, responses=None):
        self.asset_type = asset_type
        self.responses = responses or {"1": [Response(BINARY_ROBLOX)]}
        self.requests = []
        self.closed = False

    def get(self, url, params=None, headers=None):
        self.requests.append((url, headers or {}))
        parsed = urlsplit(url)
        if parsed.hostname == "economy.roblox.com":
            return Response(
                json.dumps({"AssetTypeId": self.asset_type, "Name": "Test Asset"}).encode(),
                content_type="application/json",
            )
        if parsed.hostname != "assetdelivery.roblox.com":
            raise AssertionError("Unexpected request: " + url)
        asset_id = parse_qs(parsed.query)["id"][0]
        responses = self.responses[asset_id]
        return responses.pop(0) if len(responses) > 1 else responses[0]

    async def close(self):
        self.closed = True

    def asset_requests(self):
        return [
            (url, headers)
            for url, headers in self.requests
            if urlsplit(url).hostname == "assetdelivery.roblox.com"
        ]


class PlaceIdTests(unittest.TestCase):
    def test_blank_or_positive_numeric_id(self):
        for value, expected in ((None, None), (" ", None), (123, "123"), (" 00123 ", "123")):
            with self.subTest(value=value):
                self.assertEqual(AsyncRobloxDownloader.normalize_place_id(value), expected)

    def test_invalid_place_id_rejected(self):
        for value in (0, "000", -1, "12.5", "abc", "123\r\nInjected: header", True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Place ID"):
                    AsyncRobloxDownloader.normalize_place_id(value)


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def downloader(self, session, place_id=None):
        downloader = AsyncRobloxDownloader(
            runtime_dir=self.temp.name,
            apply_template_to_images=False,
            place_id=place_id,
        )
        downloader._create_session = AsyncMock(return_value=session)
        return downloader

    async def test_binary_animation_keeps_original_bytes_and_correct_extension(self):
        session = AssetSession()
        paths = await self.downloader(session, place_id="123").download_assets("1")
        self.assertEqual(len(paths), 1)
        self.assertEqual(Path(paths[0]).suffix, ".rbxm")
        self.assertEqual(Path(paths[0]).read_bytes(), BINARY_ROBLOX)
        self.assertTrue(session.closed)
        asset_headers = session.asset_requests()[0][1]
        self.assertEqual(asset_headers["Roblox-Place-Id"], "123")
        self.assertEqual(asset_headers["User-Agent"], "Roblox/WinInet")
        metadata_headers = session.requests[0][1]
        self.assertNotIn("Roblox-Place-Id", metadata_headers)

    async def test_omitted_place_id_keeps_download_working(self):
        session = AssetSession()
        paths = await self.downloader(session).download_assets("1")
        self.assertEqual(len(paths), 1)
        self.assertNotIn("Roblox-Place-Id", session.asset_requests()[0][1])

    async def test_binary_place_is_rbxl_even_with_wrong_content_type(self):
        session = AssetSession(
            asset_type=9,
            responses={"1": [Response(BINARY_ROBLOX, content_type="application/xml")]},
        )
        paths = await self.downloader(session).download_assets("1")
        self.assertEqual(Path(paths[0]).suffix, ".rbxl")
        self.assertEqual(Path(paths[0]).read_bytes(), BINARY_ROBLOX)

    async def test_xml_animation_variants_remain_rbxmx(self):
        for asset_type in (24, 53, 61, 78):
            with self.subTest(asset_type=asset_type):
                session = AssetSession(
                    asset_type=asset_type,
                    responses={"1": [Response(XML_ROBLOX)]},
                )
                paths = await self.downloader(session).download_assets("1")
                self.assertEqual(Path(paths[0]).suffix, ".rbxmx")
                self.assertEqual(Path(paths[0]).read_bytes(), XML_ROBLOX)

    async def test_referenced_texture_receives_place_context(self):
        texture = b"\x89PNG\r\n\x1a\ntest texture bytes"
        session = AssetSession(
            asset_type=11,
            responses={
                "1": [Response(b'<roblox><Content>rbxassetid://2</Content></roblox>')],
                "2": [Response(texture, content_type="image/png")],
            },
        )
        paths = await self.downloader(session, place_id=123).download_assets("1")
        self.assertEqual(len(paths), 1)
        self.assertEqual(Path(paths[0]).read_bytes(), texture)
        self.assertEqual(len(session.asset_requests()), 2)
        for _, headers in session.asset_requests():
            self.assertEqual(headers["Roblox-Place-Id"], "123")

    async def test_auth_errors_are_not_retried_or_saved(self):
        for status, hint in ((401, "authentication"), (403, "Access denied")):
            with self.subTest(status=status):
                session = AssetSession(responses={
                    "1": [Response(b'{"errors":[{"message":"Not authorized"}]}', status)]
                })
                with self.assertLogs("module.roblox", level="WARNING") as logs:
                    paths = await self.downloader(session, place_id=123).download_assets("1")
                self.assertEqual(paths, [])
                self.assertEqual(len(session.asset_requests()), 1)
                self.assertFalse((Path(self.temp.name) / "assets").exists())
                self.assertTrue(any(hint in line for line in logs.output))

    async def test_retry_preserves_place_context_and_saves_only_success(self):
        session = AssetSession(responses={
            "1": [Response(b"Rate limited", 429), Response(BINARY_ROBLOX)]
        })
        with patch("module.roblox.asyncio.sleep", new_callable=AsyncMock):
            paths = await self.downloader(session, place_id=123).download_assets("1")
        self.assertEqual(len(session.asset_requests()), 2)
        self.assertEqual(Path(paths[0]).read_bytes(), BINARY_ROBLOX)
        for _, headers in session.asset_requests():
            self.assertEqual(headers["Roblox-Place-Id"], "123")


class ClientResultTests(unittest.TestCase):
    def test_no_files_does_not_show_success(self):
        client = DownloaderClient.__new__(DownloaderClient)
        client.root = Mock()
        client.event_queue = queue.Queue()
        client.event_queue.put(("done", []))
        client.start_button = Mock()
        client.status = Mock()
        client._append_log = Mock()
        with patch("client.messagebox.showwarning") as warning, patch(
            "client.messagebox.showinfo"
        ) as success:
            client._poll_events()
        warning.assert_called_once()
        success.assert_not_called()
        client.status.set.assert_called_once_with("No files downloaded")


if __name__ == "__main__":
    unittest.main()
