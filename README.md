# roblox asset downloader

an **asynchronous python tool** for downloading and processing roblox clothing assets (shirts, pants) in bulk.
automatically applies a user-provided template overlay to each asset, so you don’t have to manually edit hundreds of images.

---

## ✨ key features

* **bulk asset downloads** — fetch single assets, multiple ids, or entire group stores
* **automatic template overlay** — your provided image is composited onto every downloaded asset
* async and concurrent downloads powered by `aiohttp`
* supports shirts and pants (extendable to other asset types)
* saves assets locally under `runtime/assets/`
* works with authenticated roblox cookies if required

---

## 📂 project structure

```
roblox-downloader/
├── module/               # core AsyncRobloxDownloader class
├── examples/             # example usage scripts
├── runtime/assets/       # downloaded assets with template applied
├── template.png          # optional overlay template
├── requirements.txt      # python dependencies
└── README.md             # project documentation
```

---

## ⚡ installation

clone the repo and install dependencies:

```bash
git clone https://github.com/dorochadev/roblox-asset-downloader.git
cd roblox-asset-downloader
pip install -r requirements.txt
```

---

## 🔑 authentication

to download assets that require authentication, place your roblox cookie in:

```
runtime/roblox_cookie.txt
```

⚠️ **never share your cookie publicly!**

---

## 🚀 usage

### download individual or multiple assets with automatic template overlay

```python
from module.roblox import AsyncRobloxDownloader
import asyncio

# optional template.png will be applied to every asset
downloader = AsyncRobloxDownloader(template="template.png", max_concurrent=10)

async def main():
    # single asset
    await downloader.download_assets("11946489838")

    # multiple assets
    await downloader.download_assets(["11946489838", "119464898452"])

asyncio.run(main())
```

### download all items from a group store

```python
# automatically applies template overlay to every downloaded asset
await downloader.download_group_items(33054845, limit=50)
```

all assets are saved in `runtime/assets/` with your template applied automatically — no manual photoshop work needed.

---

## ⚠️ disclaimer

this tool is provided **for educational purposes only**.
downloading or redistributing roblox assets you do not own may violate roblox’s terms of service.
use responsibly.