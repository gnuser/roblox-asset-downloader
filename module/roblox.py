import aiohttp
import asyncio
import re
from PIL import Image
import os
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger(__name__)

ASSET_TYPE_MAP = {
    11: "Shirt",
    12: "Pants",
}

class AsyncRobloxDownloader:
    def __init__(self, template=None, max_concurrent=10, runtime_dir="./runtime/"):
        self.runtime_dir = runtime_dir
        os.makedirs(self.runtime_dir, exist_ok=True)
        logger.debug("Using runtime directory: %s", self.runtime_dir)

        self.template_path = template or os.path.join(self.runtime_dir, "template.png")
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.asset_type_lookup = {}

        if template and not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template file '{self.template_path}' not found.")
        
        self.cookie = None
        cookie_path = os.path.join(self.runtime_dir, "roblox_cookie.txt")
        try:
            with open(cookie_path, "r") as f:
                self.cookie = f.read().strip()
        except FileNotFoundError:
            logger.debug("No cookie file found at %s", cookie_path)
    
    async def _create_session(self):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        cookies = {}
        if self.cookie:
            cookies['.ROBLOSECURITY'] = self.cookie
            
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=20)
        session = aiohttp.ClientSession(
            headers=headers, 
            cookies=cookies,
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return session
    
    async def _get_texture_id(self, session, asset_id):
        try:
            async with self.semaphore:
                url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}"
                async with session.get(url) as response:
                    content = await response.text()
                    
                    patterns = [
                        r'<url>https?://www\.roblox\.com/asset/\?id=(\d+)</url>',
                        r'https?://www\.roblox\.com/asset/\?id=(\d+)',
                        r'rbxassetid://(\d+)'
                    ]
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, content)
                        if matches:
                            return matches[0]
        except Exception as e:
            logger.error("Failed to get texture ID for asset %s: %s", asset_id, e)
        return None
    
    def _process_image(self, image_data, asset_id, asset_type_name):
        try:
            assets_dir = os.path.join(self.runtime_dir, "assets")
            os.makedirs(assets_dir, exist_ok=True)

            filename = f"{asset_id}_{asset_type_name}.png"
            filepath = os.path.abspath(os.path.join(assets_dir, filename))
            with open(filepath, 'wb') as f:
                f.write(image_data)

            if os.path.exists(self.template_path):
                base_img = Image.open(filepath)
                template_img = Image.open(self.template_path)

                if base_img.size != template_img.size:
                    template_img = template_img.resize(base_img.size, Image.Resampling.LANCZOS)

                base_img = base_img.convert('RGBA')
                template_img = template_img.convert('RGBA')
                result = Image.alpha_composite(base_img, template_img)
                result.save(filepath)

            logger.info("Processed asset %s (%s) → %s", asset_id, asset_type_name, filepath)
            return filepath
        except Exception as e:
            logger.error("Failed to process image for asset %s: %s", asset_id, e)
            return None
    
    async def _download_and_process(self, session, texture_id, asset_id, asset_type_name, executor):
        try:
            async with self.semaphore:
                url = f"https://assetdelivery.roblox.com/v1/asset/?id={texture_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        loop = asyncio.get_event_loop()
                        filepath = await loop.run_in_executor(
                            executor, self._process_image, image_data, asset_id, asset_type_name
                        )
                        return filepath
        except Exception as e:
            logger.error("Failed to download texture %s for asset %s: %s", texture_id, asset_id, e)
        return None
        
    async def download_assets(self, asset_ids):
        if isinstance(asset_ids, str):
            asset_ids = [asset_ids]

        session = await self._create_session()
        executor = ThreadPoolExecutor(max_workers=5)
        try:
            logger.info("Fetching texture IDs for %d assets", len(asset_ids))
            texture_tasks = [
                self._get_texture_id(session, asset_id) 
                for asset_id in asset_ids
            ]
            texture_ids = await asyncio.gather(*texture_tasks, return_exceptions=True)

            valid_pairs = [
                (texture_id, asset_id)
                for texture_id, asset_id in zip(texture_ids, asset_ids)
                if texture_id and not isinstance(texture_id, Exception)
            ]

            if not valid_pairs:
                logger.warning("No valid texture IDs found for requested assets")
                return []

            logger.info("Downloading %d assets", len(valid_pairs))
            download_tasks = [
                self._download_and_process(
                    session,
                    texture_id,
                    asset_id,
                    self.asset_type_lookup.get(asset_id, "Unknown"),
                    executor
                )
                for texture_id, asset_id in valid_pairs
            ]
            results = await asyncio.gather(*download_tasks, return_exceptions=True)
            successful = [r for r in results if r and not isinstance(r, Exception)]
            logger.info("Successfully downloaded %d assets", len(successful))
            return successful

        finally:
            await session.close()
            executor.shutdown(wait=True)

    async def download_group_items(self, group_id, sort_type="Updated", limit=10):
        session = await self._create_session()
        try:
            url = "https://catalog.roblox.com/v1/search/items/details"
            params = {
                'Category': 'Clothing',
                'CreatorType': 'Group',
                'CreatorTargetId': group_id,
                'SortType': sort_type,
                'limit': 30
            }
            asset_ids = []
            next_cursor = None

            while len(asset_ids) < limit:
                if next_cursor:
                    params['cursor'] = next_cursor
                async with session.get(url, params=params) as response:
                    data = await response.json()
                    items = data.get('data', [])
                    for item in items:
                        asset_id = str(item.get('id'))
                        asset_type_id = item.get('assetType') or item.get('assetTypeId')
                        asset_type_name = ASSET_TYPE_MAP.get(asset_type_id, f"Type{asset_type_id}")
                        self.asset_type_lookup[asset_id] = asset_type_name
                        asset_ids.append(asset_id)
                        if len(asset_ids) >= limit:
                            break
                    next_cursor = data.get('nextPageCursor')
                    if not next_cursor:
                        break

        finally:
            await session.close()

        if asset_ids:
            return await self.download_assets(asset_ids)
        return []
