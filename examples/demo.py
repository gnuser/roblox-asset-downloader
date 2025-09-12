import asyncio
import logging
from module.roblox import AsyncRobloxDownloader

# configure logging (for the whole script)
logging.basicConfig(
    level=logging.INFO,  # change to DEBUG for more detail
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# template dir and runtime dir are different, i'm just using the same folder for simplicity
downloader = AsyncRobloxDownloader(template="./runtime/template.png", runtime_dir="./runtime/", max_concurrent=10)

async def main():
    # download single or multiple assets
    await downloader.download_assets("9924398681")
    await downloader.download_assets(["9884494638", "9884500531"])

    # download group items (default 10, or specify limit)
    await downloader.download_group_items(9137704)
    await downloader.download_group_items(9137704, limit=20)

if __name__ == "__main__":
    asyncio.run(main())
