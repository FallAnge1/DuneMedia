# -*- mode: python ; coding: utf-8 -*-
# Сборка программы-загрузчика.
#   Windows: один файл VideoArchive.exe (с VA_ONEDIR=1 — папка для установщика)
#   macOS:   VideoArchive.app (потом упаковывается в .dmg)
#   Linux:   один файл VideoArchive
# Запуск: pyinstaller build/videoarchive.spec   (перед этим: python build/get_ffmpeg.py и build/make_icon.py)

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
FFMPEG = ROOT / "ffmpeg"
ICON = ROOT / "assets" / "icon.png"

sys.path.insert(0, str(ROOT))
from videoarchive import __version__  # noqa: E402

if not (FFMPEG / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")).exists():
    raise SystemExit("Нет ffmpeg: запустите python build/get_ffmpeg.py")

binaries = [(str(f), "ffmpeg") for f in FFMPEG.iterdir() if f.is_file()]

# Ненужные модули Qt — сильно уменьшают размер.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvgWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "tkinter", "unittest", "pytest", "pytestqt",
]

a = Analysis(
    [str(ROOT / "build" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=[],
    hiddenimports=["videoarchive.ai.chain", "videoarchive.ui.library_tab", "cryptg"],
    excludes=EXCLUDES,
    noarchive=False,
)
# Библиотеки Qt, которые интерфейс на виджетах не использует (программный OpenGL, Quick/QML, PDF и т. п.).
DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard", "qt6webengine", "qt6charts", "qt6multimedia",
        "qt6shadertools", "qt6labs", "qt63d")
before = len(a.binaries)
a.binaries = [b for b in a.binaries if not any(Path(b[0]).name.lower().startswith(p) or p in Path(b[1]).name.lower()
                                                for p in DROP)]
print(f"Исключено библиотек Qt: {before - len(a.binaries)}")

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VideoArchive", console=False,
              icon=str(ICON), target_arch=None, codesign_identity=None, entitlements_file=None)
    coll = COLLECT(exe, a.binaries, a.datas, name="VideoArchive")
    app = BUNDLE(
        coll,
        name="VideoArchive.app",
        icon=str(ICON),
        bundle_identifier="ru.videoarchive.uploader",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "Видеоархив",
            "CFBundleName": "VideoArchive",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDevelopmentRegion": "ru",
        },
    )
elif os.environ.get("VA_ONEDIR"):
    # Папка вместо одного файла — для установщика Windows: запускается быстрее (не распаковывается при каждом старте).
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VideoArchive", console=False, icon=str(ICON), upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="VideoArchive")
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="VideoArchive",
        console=False,
        icon=str(ICON),
        upx=False,
        version=None,
    )
