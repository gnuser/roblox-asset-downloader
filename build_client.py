import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__


ROOT = Path(__file__).resolve().parent
APP_NAME = "RobloxAssetDownloader"


def clean():
    for name in ("build", "dist"):
        path = ROOT / name
        if path.exists():
            shutil.rmtree(path)

    spec = ROOT / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()


def main():
    clean()

    add_data = f"{ROOT / 'runtime' / 'template.png'}{os.pathsep}runtime"
    args = [
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
        "--add-data",
        add_data,
        "--collect-submodules",
        "aiohttp",
        "--collect-submodules",
        "PIL",
        str(ROOT / "client.py"),
    ]

    if sys.platform == "win32":
        args.insert(4, "--windowed")
        args.insert(5, "--onefile")
    elif sys.platform == "darwin":
        args.insert(4, "--windowed")
    else:
        args.insert(4, "--onefile")

    PyInstaller.__main__.run(args)

    print(f"Built {APP_NAME} in {ROOT / 'dist'}")


if __name__ == "__main__":
    main()
