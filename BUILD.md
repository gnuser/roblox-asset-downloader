# Desktop client build

This project includes a Tkinter desktop client in `client.py` and a PyInstaller
build script in `build_client.py`.

## Local build

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-build.txt

python build_client.py
```

The output is written to `dist/`.

## Platform notes

PyInstaller is not a cross-compiler:

* Build the Windows `.exe` on Windows.
* Build the macOS executable/app on macOS.

Use the included GitHub Actions workflow if you want both platforms from CI.

## Windows legacy build

If a user sees an ordinal/dynamic-link-library error on an older Windows
machine, build the legacy package instead. It uses Python 3.8.10 and older
runtime dependencies:

```bash
pip install -r requirements-legacy.txt
python build_client.py
```

The `Build Windows legacy client` GitHub Actions workflow produces
`RobloxAssetDownloader-windows-legacy-X64.zip`.

## Cookie safety

The client lets users paste a `.ROBLOSECURITY` cookie for the current session.
The GUI passes it directly to the downloader and does not save it to disk.
