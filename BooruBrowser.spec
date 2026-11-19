# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('boorus')
hiddenimports += collect_submodules('cloudflare_bypasser')
hiddenimports += collect_submodules('updater')
hiddenimports += collect_submodules('ui')
hiddenimports += collect_submodules('displayers')
hiddenimports += collect_submodules('download_images')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('boorus', 'boorus'), ('adapters', 'adapters'), ('ui/assets', 'ui/assets'), ('appico.png', '.'), ('updater', 'updater')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'test_comments',
        'test_dialog',
        'replace_print',
        'generate_boorus',
        'cloudflare_bypasser._debug_test',
        'tests',               # exclude all test scripts
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BooruBrowser',
    icon='appico.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
