# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = []
binaries = []
hiddenimports = []

def is_test_module(name):
    parts = name.split('.')
    return (
        'tests' in parts
        or name.endswith('.conftest')
        or '.tests.' in name
        or name == 'conftest'
    )

def is_test_data(item):
    src, dest = item
    normalized = f"{src}/{dest}".replace('\\', '/')
    return (
        '/tests/' in normalized
        or normalized.endswith('/tests')
        or '/test/' in normalized
        or normalized.endswith('/test')
    )

for pkg in [
    'pandas',
    'numpy',
    'scipy',
    'sklearn',
    'statsmodels',
    'pyarrow',
    'duckdb',
    'polars',
    'akshare',
    'loguru',
    'tqdm',
    'requests',
    'dotenv',
]:
    d, b, h = collect_all(pkg)
    datas += [item for item in d if not is_test_data(item)]
    binaries += b
    hiddenimports += [name for name in h if not is_test_module(name)]

hiddenimports += collect_submodules('scripts')
hiddenimports += collect_submodules('trading')
hiddenimports += collect_submodules('research')
hiddenimports += collect_submodules('common')

a = Analysis(
    ['quant_worker.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        '*.tests',
        '*.tests.*',
        'conftest',
        'hypothesis',
        'matplotlib',
        'tkinter',
        'PyQt5',
        'PyQt6',
        'wx',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='quant_worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='quant_worker',
)
