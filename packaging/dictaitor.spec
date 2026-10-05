# PyInstaller spec: two executables sharing one folder.
#   dictAItor.exe      - tray app, no console window
#   dictaitor-cli.exe  - command line (record, eval, prepare, listen)
# Build: pyinstaller packaging/dictaitor.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "av", "sounddevice", "dictaitor"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
try:  # PortAudio DLL shipped by the sounddevice wheel on Windows
    d, b, h = collect_all("_sounddevice_data")
    datas += d
    binaries += b
except Exception:
    pass
hiddenimports += collect_submodules("keyring.backends") + ["win32ctypes.core"]

common = dict(
    pathex=[os.path.join(SPECPATH, "..", "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "torch", "IPython", "pytest"],
)
app = Analysis(["app_entry.py"], **common)
cli = Analysis(["cli_entry.py"], **common)

# UTF-8 mode: Polish text must print even to a cp1250/cp1252 console or a redirected file.
UTF8 = [("X utf8_mode=1", None, "OPTION")]
app_exe = EXE(
    PYZ(app.pure), app.scripts, UTF8, exclude_binaries=True,
    name="dictAItor", console=False, icon=os.path.join(SPECPATH, "dictaitor.ico"),
)
cli_exe = EXE(
    PYZ(cli.pure), cli.scripts, UTF8, exclude_binaries=True,
    name="dictaitor-cli", console=True, icon=os.path.join(SPECPATH, "dictaitor.ico"),
)
COLLECT(
    app_exe, app.binaries, app.datas,
    cli_exe, cli.binaries, cli.datas,
    name="dictAItor",
)
