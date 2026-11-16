from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas = [("static", "static"), ("config", "config"), ("README_FA.md", "."), ("docs", "docs")]
binaries = []
hiddenimports = []
# Bundle static Windows FFmpeg binaries when supplied by the build workflow.
for tool in ("ffmpeg.exe", "ffprobe.exe"):
    candidate = Path("vendor") / "ffmpeg" / "bin" / tool
    if candidate.is_file():
        binaries.append((str(candidate), "ffmpeg"))
for package in ("uvicorn", "fastapi", "PIL", "faster_whisper", "ctranslate2", "av", "webview", "clr_loader", "pythonnet", "arabic_reshaper", "bidi"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="NewsStudioAI",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=True, disable_windowed_traceback=False
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="NewsStudioAI")
