import asyncio
import json
import logging
import mimetypes
import os
import re
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import aiohttp
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

ASSET_TYPE_MAP = {
    1: "Image",
    2: "TShirt",
    3: "Audio",
    4: "Mesh",
    5: "Lua",
    8: "Hat",
    9: "Place",
    10: "Model",
    11: "Shirt",
    12: "Pants",
    13: "Decal",
    17: "Head",
    18: "Face",
    19: "Gear",
    21: "Badge",
    24: "Animation",
    27: "Torso",
    28: "RightArm",
    29: "LeftArm",
    30: "LeftLeg",
    31: "RightLeg",
    32: "Package",
    34: "GamePass",
    38: "Plugin",
    40: "MeshPart",
    41: "HairAccessory",
    42: "FaceAccessory",
    43: "NeckAccessory",
    44: "ShoulderAccessory",
    45: "FrontAccessory",
    46: "BackAccessory",
    47: "WaistAccessory",
    48: "ClimbAnimation",
    49: "DeathAnimation",
    50: "FallAnimation",
    51: "IdleAnimation",
    52: "JumpAnimation",
    53: "RunAnimation",
    54: "SwimAnimation",
    55: "WalkAnimation",
    56: "PoseAnimation",
    57: "EarAccessory",
    58: "EyeAccessory",
    61: "EmoteAnimation",
    62: "Video",
    64: "TShirtAccessory",
    65: "ShirtAccessory",
    66: "PantsAccessory",
    67: "JacketAccessory",
    68: "SweaterAccessory",
    69: "ShortsAccessory",
    70: "LeftShoeAccessory",
    71: "RightShoeAccessory",
    72: "DressSkirtAccessory",
    73: "FontFamily",
    76: "EyebrowAccessory",
    77: "EyelashAccessory",
    78: "MoodAnimation",
    79: "DynamicHead",
    88: "FaceMakeup",
    89: "LipMakeup",
    90: "EyeMakeup",
    91: "VoxelFragment",
}

CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/json": ".json",
}

DEFAULT_ASSET_EXTENSIONS = {
    "Image": ".png",
    "TShirt": ".png",
    "Shirt": ".png",
    "Pants": ".png",
    "Decal": ".png",
    "Face": ".png",
    "Audio": ".ogg",
    "Mesh": ".mesh",
    "Lua": ".lua",
    "Place": ".rbxl",
    "Model": ".rbxm",
    "Hat": ".rbxm",
    "Gear": ".rbxm",
    "Animation": ".rbxm",
    "Package": ".rbxm",
    "Plugin": ".rbxm",
    "MeshPart": ".rbxm",
    "Video": ".mp4",
    "FontFamily": ".json",
}

LINKED_IMAGE_ASSET_TYPES = {
    "Image",
    "TShirt",
    "Shirt",
    "Pants",
    "Decal",
    "Face",
}


class AsyncRobloxDownloader:
    def __init__(
        self,
        template=None,
        max_concurrent=10,
        runtime_dir="./runtime/",
        apply_template_to_images=True,
        cookie=None,
    ):
        self.runtime_dir = runtime_dir
        os.makedirs(self.runtime_dir, exist_ok=True)
        logger.debug("Using runtime directory: %s", self.runtime_dir)

        self.template_path = template or os.path.join(self.runtime_dir, "template.png")
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.apply_template_to_images = apply_template_to_images
        self.asset_type_lookup = {}
        self.asset_name_lookup = {}

        if template and not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template file '{self.template_path}' not found.")

        self.cookie = cookie
        cookie_path = os.path.join(self.runtime_dir, "roblox_cookie.txt")
        if not self.cookie:
            try:
                with open(cookie_path, "r", encoding="utf-8") as f:
                    self.cookie = f.read().strip()
            except FileNotFoundError:
                logger.debug("No cookie file found at %s", cookie_path)

    async def _create_session(self):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )
        }

        cookies = {}
        if self.cookie:
            cookies[".ROBLOSECURITY"] = self.cookie

        connector = aiohttp.TCPConnector(limit=50, limit_per_host=20)
        session = aiohttp.ClientSession(
            headers=headers,
            cookies=cookies,
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30),
        )
        return session

    async def _get_with_retries(self, session, url, params=None, attempts=3):
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                async with self.semaphore:
                    async with session.get(url, params=params) as response:
                        content = await response.read()
                        content_type = response.headers.get("Content-Type", "")
                        content_type = content_type.split(";", 1)[0].strip().lower()
                        result = {
                            "status": response.status,
                            "content": content,
                            "content_type": content_type,
                            "headers": dict(response.headers),
                        }

                if result["status"] == 429 or result["status"] >= 500:
                    if attempt < attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue

                return result
            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionResetError) as e:
                last_error = e
                if attempt < attempts:
                    logger.debug(
                        "GET retry %d/%d for %s after error: %s",
                        attempt,
                        attempts,
                        url,
                        e,
                    )
                    await asyncio.sleep(0.5 * attempt)
                    continue
                raise

        raise last_error

    async def _get_asset_details(self, session, asset_id):
        asset_id = self._normalize_asset_id(asset_id)
        url = f"https://economy.roblox.com/v2/assets/{asset_id}/details"

        try:
            response = await self._get_with_retries(session, url)
            if response["status"] != 200:
                logger.debug(
                    "Asset details lookup failed for %s: HTTP %s",
                    asset_id,
                    response["status"],
                )
                return self._fallback_asset_details(asset_id)

            data = json.loads(response["content"])
        except Exception as e:
            logger.debug("Asset details lookup failed for %s: %s", asset_id, e)
            return self._fallback_asset_details(asset_id)

        asset_type_id = data.get("AssetTypeId") or data.get("assetType")
        asset_type_name = ASSET_TYPE_MAP.get(asset_type_id, f"Type{asset_type_id}")
        name = data.get("Name") or self.asset_name_lookup.get(asset_id)

        self.asset_type_lookup[asset_id] = asset_type_name
        if name:
            self.asset_name_lookup[asset_id] = name

        return {
            "asset_id": asset_id,
            "asset_type_id": asset_type_id,
            "asset_type_name": asset_type_name,
            "name": name,
        }

    def _fallback_asset_details(self, asset_id):
        asset_id = self._normalize_asset_id(asset_id)
        asset_type_name = self.asset_type_lookup.get(str(asset_id), "Unknown")
        return {
            "asset_id": str(asset_id),
            "asset_type_id": None,
            "asset_type_name": asset_type_name,
            "name": self.asset_name_lookup.get(str(asset_id)),
        }

    def _normalize_asset_id(self, asset_id):
        value = unquote(str(asset_id).strip())
        patterns = [
            r"^rbxassetid://(\d+)$",
            r"roblox\.com/asset/\?id=(\d+)",
            r"assetdelivery\.roblox\.com/v1/asset/\?id=(\d+)",
            r"^(\d+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return match.group(1)

        return value

    async def _fetch_asset_content(self, session, asset_id):
        asset_id = self._normalize_asset_id(asset_id)
        url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}"

        try:
            response = await self._get_with_retries(session, url)

            if response["status"] != 200:
                body = response["content"][:300].decode("utf-8", errors="replace")
                logger.warning(
                    "Failed to download asset %s: HTTP %s %s",
                    asset_id,
                    response["status"],
                    body,
                )
                return None

            return {
                "asset_id": asset_id,
                "content": response["content"],
                "content_type": response["content_type"],
            }
        except Exception as e:
            logger.error("Failed to download asset %s: %s", asset_id, e)
            return None

    def _extract_referenced_asset_ids(self, content, source_asset_id):
        text = unquote(content[:2_000_000].decode("utf-8", errors="ignore"))
        patterns = [
            r"rbxassetid://(\d+)",
            r"https?://(?:www\.)?roblox\.com/asset/\?id=(\d+)",
            r"https?://assetdelivery\.roblox\.com/v1/asset/\?id=(\d+)",
        ]

        referenced_ids = []
        seen = {str(source_asset_id)}
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                if match not in seen:
                    seen.add(match)
                    referenced_ids.append(match)

        return referenced_ids

    def _should_follow_references(self, asset_type_name, content, content_type):
        if self._is_image_content(content, content_type):
            return False
        return asset_type_name in LINKED_IMAGE_ASSET_TYPES

    def _guess_extension(self, content, content_type, asset_type_name):
        magic_extension = self._extension_from_magic(content)
        if magic_extension:
            return magic_extension

        stripped = content.lstrip()
        if stripped.startswith(b"<roblox") or stripped.startswith(b"<?xml"):
            if asset_type_name == "Place":
                return ".rbxlx"
            if asset_type_name in {"Model", "Plugin", "Package", "Animation"}:
                return ".rbxmx"
            return ".xml"

        if content_type in CONTENT_TYPE_EXTENSIONS:
            return CONTENT_TYPE_EXTENSIONS[content_type]

        if asset_type_name in DEFAULT_ASSET_EXTENSIONS:
            return DEFAULT_ASSET_EXTENSIONS[asset_type_name]

        if content_type:
            guessed = mimetypes.guess_extension(content_type)
            if guessed:
                return guessed

        return ".asset"

    def _extension_from_magic(self, content):
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if content.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if content.startswith(b"OggS"):
            return ".ogg"
        if content.startswith(b"ID3"):
            return ".mp3"
        if len(content) > 12 and content[4:8] == b"ftyp":
            return ".mp4"
        if content.startswith(b"RIFF") and content[8:12] == b"WAVE":
            return ".wav"
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return ".webp"
        if content.startswith(b"\x1a\x45\xdf\xa3"):
            return ".webm"
        return None

    def _is_image_content(self, content, content_type=""):
        if content_type.startswith("image/"):
            return True

        try:
            image = Image.open(BytesIO(content))
            image.verify()
            return True
        except (UnidentifiedImageError, OSError, ValueError):
            return False

    def _safe_filename_part(self, value, fallback="asset"):
        value = str(value or fallback).strip()
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
        value = value.strip("._-")
        return value[:80] or fallback

    def _process_and_save_content(
        self,
        content,
        asset_id,
        asset_type_name,
        content_type,
        asset_name=None,
        referenced_asset_id=None,
    ):
        assets_dir = Path(self.runtime_dir) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        asset_type_part = self._safe_filename_part(asset_type_name, "Unknown")
        name_part = self._safe_filename_part(asset_name, "")
        if referenced_asset_id:
            stem = f"{asset_id}_{asset_type_part}_ref_{referenced_asset_id}"
        elif name_part:
            stem = f"{asset_id}_{name_part}_{asset_type_part}"
        else:
            stem = f"{asset_id}_{asset_type_part}"

        extension = self._guess_extension(content, content_type, asset_type_name)
        should_apply_template = (
            self.apply_template_to_images
            and os.path.exists(self.template_path)
            and self._is_image_content(content, content_type)
        )

        if should_apply_template:
            filepath = assets_dir / f"{stem}.png"
            try:
                base_img = Image.open(BytesIO(content)).convert("RGBA")
                template_img = Image.open(self.template_path).convert("RGBA")

                if base_img.size != template_img.size:
                    template_img = template_img.resize(
                        base_img.size,
                        Image.Resampling.LANCZOS,
                    )

                result = Image.alpha_composite(base_img, template_img)
                result.save(filepath)
            except Exception as e:
                logger.warning(
                    "Template overlay failed for asset %s, saving original: %s",
                    asset_id,
                    e,
                )
                filepath = assets_dir / f"{stem}{extension}"
                filepath.write_bytes(content)
        else:
            filepath = assets_dir / f"{stem}{extension}"
            filepath.write_bytes(content)

        filepath = filepath.resolve()
        logger.info("Saved asset %s (%s) -> %s", asset_id, asset_type_name, filepath)
        return str(filepath)

    async def _save_content_async(
        self,
        executor,
        content,
        asset_id,
        asset_type_name,
        content_type,
        asset_name=None,
        referenced_asset_id=None,
    ):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            executor,
            self._process_and_save_content,
            content,
            asset_id,
            asset_type_name,
            content_type,
            asset_name,
            referenced_asset_id,
        )

    async def _download_one_asset(
        self,
        session,
        asset_id,
        details,
        executor,
        resolve_references=True,
        save_original=False,
        download_references=False,
    ):
        payload = await self._fetch_asset_content(session, asset_id)
        if not payload:
            return []

        content = payload["content"]
        content_type = payload["content_type"]
        asset_type_name = details.get("asset_type_name") or "Unknown"
        asset_name = details.get("name")
        saved_paths = []

        referenced_ids = self._extract_referenced_asset_ids(content, asset_id)
        should_follow = (
            resolve_references
            and referenced_ids
            and (
                download_references
                or self._should_follow_references(asset_type_name, content, content_type)
            )
        )

        if save_original or not should_follow:
            saved_path = await self._save_content_async(
                executor,
                content,
                asset_id,
                asset_type_name,
                content_type,
                asset_name,
            )
            saved_paths.append(saved_path)

        if should_follow:
            logger.info(
                "Asset %s (%s) references %d linked asset(s)",
                asset_id,
                asset_type_name,
                len(referenced_ids),
            )
            reference_payloads = await asyncio.gather(
                *[
                    self._fetch_asset_content(session, referenced_id)
                    for referenced_id in referenced_ids
                ],
                return_exceptions=True,
            )

            for referenced_id, reference_payload in zip(
                referenced_ids,
                reference_payloads,
            ):
                if isinstance(reference_payload, Exception) or not reference_payload:
                    logger.warning(
                        "Failed to download referenced asset %s from %s",
                        referenced_id,
                        asset_id,
                    )
                    continue

                saved_path = await self._save_content_async(
                    executor,
                    reference_payload["content"],
                    asset_id,
                    asset_type_name,
                    reference_payload["content_type"],
                    asset_name,
                    referenced_asset_id=referenced_id,
                )
                saved_paths.append(saved_path)

        return saved_paths

    async def download_assets(
        self,
        asset_ids,
        resolve_references=True,
        save_original=False,
        download_references=False,
    ):
        if isinstance(asset_ids, (str, int)):
            asset_ids = [asset_ids]

        asset_ids = [self._normalize_asset_id(asset_id) for asset_id in asset_ids]
        session = await self._create_session()
        executor = ThreadPoolExecutor(max_workers=5)

        try:
            logger.info("Fetching metadata for %d assets", len(asset_ids))
            detail_tasks = [
                self._get_asset_details(session, asset_id)
                for asset_id in asset_ids
            ]
            details = await asyncio.gather(*detail_tasks, return_exceptions=True)
            normalized_details = []

            for asset_id, detail in zip(asset_ids, details):
                if isinstance(detail, Exception) or not detail:
                    normalized_details.append(self._fallback_asset_details(asset_id))
                else:
                    normalized_details.append(detail)

            logger.info("Downloading %d assets", len(asset_ids))
            download_tasks = [
                self._download_one_asset(
                    session,
                    asset_id,
                    detail,
                    executor,
                    resolve_references=resolve_references,
                    save_original=save_original,
                    download_references=download_references,
                )
                for asset_id, detail in zip(asset_ids, normalized_details)
            ]
            results = await asyncio.gather(*download_tasks, return_exceptions=True)

            successful = []
            for result in results:
                if isinstance(result, Exception):
                    logger.error("Asset download task failed: %s", result)
                    continue
                successful.extend(result)

            logger.info("Successfully saved %d files", len(successful))
            return successful

        finally:
            await session.close()
            executor.shutdown(wait=True)

    async def download_group_items(
        self,
        group_id,
        sort_type="Updated",
        limit=10,
        category="All",
        asset_types=None,
        resolve_references=True,
        save_original=False,
        download_references=False,
    ):
        session = await self._create_session()
        try:
            url = "https://catalog.roblox.com/v1/search/items/details"
            params = {
                "Category": category,
                "CreatorType": "Group",
                "CreatorTargetId": group_id,
                "SortType": sort_type,
                "limit": 30,
            }
            asset_ids = []
            next_cursor = None
            allowed_types = None

            if asset_types:
                if isinstance(asset_types, (str, int)):
                    asset_types = [asset_types]
                allowed_types = {str(asset_type).lower() for asset_type in asset_types}

            while len(asset_ids) < limit:
                if next_cursor:
                    params["cursor"] = next_cursor

                try:
                    response = await self._get_with_retries(session, url, params=params)
                    data = json.loads(response["content"])
                except Exception as e:
                    logger.warning("Group item lookup failed: %s", e)
                    break

                if response["status"] != 200:
                    logger.warning(
                        "Group item lookup failed: HTTP %s %s",
                        response["status"],
                        data,
                    )
                    break

                items = data.get("data", [])
                for item in items:
                    asset_id = str(item.get("id"))
                    asset_type_id = item.get("assetType") or item.get("assetTypeId")
                    asset_type_name = ASSET_TYPE_MAP.get(
                        asset_type_id,
                        f"Type{asset_type_id}",
                    )

                    if allowed_types:
                        type_keys = {
                            str(asset_type_id).lower(),
                            asset_type_name.lower(),
                        }
                        if not type_keys & allowed_types:
                            continue

                    self.asset_type_lookup[asset_id] = asset_type_name
                    if item.get("name"):
                        self.asset_name_lookup[asset_id] = item["name"]
                    asset_ids.append(asset_id)

                    if len(asset_ids) >= limit:
                        break

                next_cursor = data.get("nextPageCursor")
                if not next_cursor:
                    break

        finally:
            await session.close()

        if asset_ids:
            return await self.download_assets(
                asset_ids,
                resolve_references=resolve_references,
                save_original=save_original,
                download_references=download_references,
            )
        return []
