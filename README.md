# roblox asset downloader

An asynchronous Python tool for downloading Roblox assets by ID or from a
group catalog. It detects asset metadata, downloads the raw asset content, and
saves files with practical extensions such as `.png`, `.ogg`, `.mesh`, `.rbxm`,
`.rbxlx`, `.json`, or `.mp4`.

For classic clothing assets such as shirts, pants, t-shirts, decals, and faces,
the downloader follows linked texture IDs and saves the actual image. If a
template image exists, it can be composited onto downloaded images.

---

## Key features

* Bulk asset downloads from a single ID, a list of IDs, or group catalog items
* Metadata lookup using Roblox asset details
* Type-aware saving for images, audio, meshes, models, places, animations,
  videos, plugins, font families, and avatar/catalog assets
* Linked image resolution for classic clothing and decals
* Optional image template overlay
* Async and concurrent downloads powered by `aiohttp`
* Authenticated requests through a local Roblox cookie file when required

---

## Project structure

```text
roblox-asset-downloader/
├── module/               # core AsyncRobloxDownloader class
├── examples/             # example usage scripts
├── runtime/assets/       # downloaded assets
├── runtime/template.png  # optional overlay template for images
├── requirements.txt      # python dependencies
└── README.md             # project documentation
```

---

## Installation

```bash
git clone https://github.com/dorochadev/roblox-asset-downloader.git
cd roblox-asset-downloader

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

---

## Authentication

Roblox Asset Delivery commonly requires authentication. To use authenticated
requests, place your own Roblox cookie in:

```text
runtime/roblox_cookie.txt
```

The file should contain only the `.ROBLOSECURITY` value. Never commit this file
or share it with anyone.

---

## Usage

### Desktop client

Run the GUI client directly:

```bash
python client.py
```

The desktop client keeps the common workflow simple: asset IDs, group ID, output
folder, cookie, download button, and log output.

Build a Windows or macOS executable on the matching platform:

```bash
pip install -r requirements.txt
pip install -r requirements-build.txt
python build_client.py
```

PyInstaller is not a cross-compiler, so build Windows on Windows and macOS on
macOS. The included GitHub Actions workflow can build both.

### Python API

```python
import asyncio
from module.roblox import AsyncRobloxDownloader

downloader = AsyncRobloxDownloader(
    template="./runtime/template.png",
    runtime_dir="./runtime/",
    max_concurrent=10,
)

async def main():
    # Single asset
    await downloader.download_assets("9924398681")
    await downloader.download_assets("rbxassetid://5603258258")

    # Multiple assets
    await downloader.download_assets(["9884494638", "9884500531"])

    # Save the original file too when a clothing/decal asset points to a texture
    await downloader.download_assets("9924398681", save_original=True)

    # Also download one level of referenced asset IDs found inside a model/XML
    await downloader.download_assets("MODEL_ASSET_ID", download_references=True)

    # Group catalog items, all categories
    await downloader.download_group_items(9137704, limit=20, category="All")

    # Group catalog items filtered by asset type name or asset type ID
    await downloader.download_group_items(
        9137704,
        limit=20,
        asset_types=["TShirt", "Shirt", "Pants"],
    )

if __name__ == "__main__":
    asyncio.run(main())
```

Downloaded files are saved in:

```text
runtime/assets/
```

---

## Supported asset types

The downloader includes Roblox `AssetType` mappings for common and current asset
types, including:

* Image, TShirt, Shirt, Pants, Decal, Face
* Audio, Video
* Mesh, MeshPart
* Model, Place, Package, Plugin
* Animation and specific animation types
* Hat, Gear, accessories, layered clothing, dynamic heads, makeup assets
* FontFamily and other newer asset types when metadata is available

Some Roblox assets are protected, moderated, private, off-sale, or only
available to their owner/group. The tool will save what the authenticated
account is allowed to access; it does not bypass Roblox permissions.

---

## Notes

* Image assets are saved directly or as linked textures when the public asset is
  a classic clothing/decal wrapper.
* Non-image assets are saved as raw content from Roblox Asset Delivery.
* `download_references=True` saves one extra level of referenced asset IDs found
  inside the downloaded asset content.
* File extensions are inferred from content signatures, content type headers,
  and asset metadata.
* Template overlay is only applied to images.

---

## Disclaimer

This tool is provided for educational and legitimate asset-management purposes
only. Downloading or redistributing Roblox assets you do not own may violate
Roblox's terms or creator rights. Use responsibly.
