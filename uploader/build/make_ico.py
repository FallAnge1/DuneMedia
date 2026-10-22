#!/usr/bin/env python3
"""assets/icon.png → assets/icon.ico (для установщика Inno Setup). Нужен Pillow."""

from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1] / "assets"
Image.open(root / "icon.png").save(root / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets/icon.ico готов")
