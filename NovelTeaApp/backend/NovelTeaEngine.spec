# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the NovelTea Engine server (a single .exe that serves the UI and the API).
# Build (from NovelTeaApp/backend, after copying renderer/dist to backend/webui):
#     python -m PyInstaller NovelTeaEngine.spec --noconfirm --clean
from PyInstaller.utils.hooks import collect_submodules

hidden = ['uvicorn', 'fastapi', 'starlette', 'pydantic', 'anyio', 'click', 'h11', 'multipart']
# every router and service is imported lazily by name, so list them all
for pkg in ('routers', 'services'):
    hidden += collect_submodules(pkg)
# optional engines: bundled only when installed
for opt in ('qoder_agent_sdk', 'mcp', 'riva', 'grpc', 'google.protobuf', 'kokoro_onnx', 'pywebpush'):
    try:
        __import__(opt.split('.')[0])
        hidden.append(opt)
    except ImportError:
        pass

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('webui', 'webui'), ('prompts', 'prompts')],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NovelTeaEngine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
