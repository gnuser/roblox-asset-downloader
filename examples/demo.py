import asyncio
import logging
from module.roblox import AsyncRobloxDownloader

# configure logging (for the whole script)
logging.basicConfig(
    level=logging.INFO,  # change to DEBUG for more detail
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# The template is only applied to image assets. Non-image assets are saved as-is.
downloader = AsyncRobloxDownloader(
    template="./runtime/template.png",
    runtime_dir="./runtime/",
    max_concurrent=10,
)

async def main():
    # Download single or multiple assets. The downloader detects the asset type
    # and saves a suitable extension such as .png, .ogg, .mesh, .rbxm, or .mp4.
    await downloader.download_assets("9924398681")
    await downloader.download_assets(["9884494638", "9884500531"])

    # Save the original clothing XML/model file too, alongside linked textures.
    await downloader.download_assets("9924398681", save_original=True)

    # Also download one level of referenced asset IDs found inside a model/XML.
    # await downloader.download_assets("MODEL_ASSET_ID", download_references=True)


    # Download group catalog items. Use category="Clothing" to limit to clothing,
    # or asset_types=["Shirt", "Pants"] to filter after catalog lookup.
    await downloader.download_group_items(9137704)
    await downloader.download_group_items(9137704, limit=20, category="All")
    await downloader.download_group_items(
        9137704,
        limit=20,
        asset_types=["TShirt", "Shirt", "Pants"],
    )

if __name__ == "__main__":
    asyncio.run(main())
