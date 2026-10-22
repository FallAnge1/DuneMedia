#!/usr/bin/env python3
"""Рисует иконку программы (assets/icon.png, 1024×1024) — та же, что favicon сайта.

PyInstaller сам превращает PNG в .ico (Windows) и .icns (macOS), если установлен Pillow.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "assets" / "icon.png"


def main() -> None:
    _app = QGuiApplication(sys.argv)
    size = 1024
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 32  # координаты как в favicon.svg (32×32)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#e8a33d"))
    p.drawRoundedRect(QRectF(0, 0, size, size), 8 * s, 8 * s)
    p.setBrush(QColor("#1a1205"))
    for x, y, w, h in ((6, 7, 9, 11), (17, 7, 9, 7), (6, 20, 9, 5), (17, 16, 9, 9)):
        p.drawRoundedRect(QRectF(x * s, y * s, w * s, h * s), 2 * s, 2 * s)
    p.end()
    OUT.parent.mkdir(exist_ok=True)
    img.save(str(OUT))
    print(f"Иконка: {OUT}")


if __name__ == "__main__":
    main()
