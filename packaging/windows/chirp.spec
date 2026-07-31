# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the CHIRP.exe Windows one-directory bundle.
#
# Run via .\packaging\windows\build-windows.ps1 from the repo root; do not
# invoke pyinstaller on this file directly outside that script, since
# build-windows.ps1 compiles chirp/locale/*.po -> *.mo first (PyInstaller
# only picks up files that already exist on disk) and generates the
# version-info resource file this spec references.
#
# Mirrors packaging/macos/chirpwx.spec's hiddenimports/datas approach --
# see that file's comments for why each piece is needed. This spec builds
# a COLLECT-only one-directory bundle (no macOS BUNDLE step, no one-file
# EXE) per this project's Windows packaging requirements.
import glob
import os

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(SPEC)), '..', '..'))

# Populated by build-windows.ps1 from a generated version-info file;
# falls back to a dev placeholder if invoked outside that script.
VERSION_FILE = os.environ.get('CHIRP_WINDOWS_VERSION_FILE')
if not VERSION_FILE or not os.path.exists(VERSION_FILE):
    VERSION_FILE = None

hiddenimports = (
    collect_submodules('chirp.drivers')
    + collect_submodules('chirp.wxui')
    + collect_submodules('chirp.cli')
    + collect_submodules('chirp.sources')
    + collect_submodules('chirp.memcolors')
    + collect_submodules('chirp.profiles')
    + collect_submodules('chirp.assistant')
    # wx.richtext (and other wx submodules) reach for compiled extension
    # submodules like wx._xml at import time in a way PyInstaller's static
    # analysis doesn't always follow -- collect the whole wx package
    # explicitly rather than rely on hook coverage (same issue hit and
    # fixed for the macOS build; see packaging/macos/chirpwx.spec).
    + collect_submodules('wx')
    + ['yattag', 'suds', 'lark', 'pyserial', 'win32com', 'win32con',
       'win32api']
)

# Resource data carried inside the bundle. Mirrors MANIFEST.in's
# package_data set (png/svg/ico/1/desktop/metainfo + stock_configs +
# compiled locale). Excludes the *.xcf GIMP source files: multi-megabyte
# editable sources for the welcome-screen art that are never read at
# runtime (only the exported .png files are), and excludes the macOS-only
# .icns icon (chirp.ico is the Windows-relevant one).
datas = [
    (os.path.join(REPO_ROOT, 'chirp', 'share', pattern), 'chirp/share')
    for pattern in (
        '*.png', '*.svg', '*.ico', '*.1',
        '*.desktop', '*.metainfo.xml', '*.yaml',
    )
] + [
    (os.path.join(REPO_ROOT, 'chirp', 'stock_configs', '*.csv'),
     'chirp/stock_configs'),
]

# PyInstaller's datas glob support copies every file matched by one tuple's
# source pattern into that tuple's single destination directory, discarding
# any subdirectory structure in the match -- fine for chirp/share and
# stock_configs above (flat directories), but locale needs one destination
# per language (chirp/locale/<lang>/LC_MESSAGES/), so each .mo file gets its
# own (src, dest) tuple instead of sharing one.
for mo_path in glob.glob(os.path.join(
        REPO_ROOT, 'chirp', 'locale', '*', 'LC_MESSAGES', '*.mo')):
    lang = os.path.basename(os.path.dirname(os.path.dirname(mo_path)))
    datas.append((mo_path, os.path.join('chirp', 'locale', lang, 'LC_MESSAGES')))

block_cipher = None

a = Analysis(
    [os.path.join(REPO_ROOT, 'packaging', 'windows', 'launcher.py')],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CHIRP',
    debug=False,
    strip=False,
    upx=False,
    # No console window for the normal GUI launch -- CHIRP still logs to
    # its usual debug log location (see chirp.logger / Help > Open debug
    # log inside the app), this only suppresses the extra terminal window.
    console=False,
    icon=os.path.join(REPO_ROOT, 'chirp', 'share', 'chirp.ico'),
    version=VERSION_FILE,
)

# A second, tiny console entry point sharing this same Analysis's frozen
# modules -- see driver_check.py's docstring for why this exists (CI-only
# validation that radio-driver discovery works inside the actual frozen
# bundle, not just in the pre-freeze build venv). Not a user-facing tool;
# not documented anywhere outside packaging.
a_driver_check = Analysis(
    [os.path.join(REPO_ROOT, 'packaging', 'windows', 'driver_check.py')],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules('chirp.drivers'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz_driver_check = PYZ(a_driver_check.pure, a_driver_check.zipped_data,
                        cipher=block_cipher)
exe_driver_check = EXE(
    pyz_driver_check,
    a_driver_check.scripts,
    [],
    exclude_binaries=True,
    name='CHIRP-driver-check',
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    exe_driver_check,
    a_driver_check.binaries,
    a_driver_check.zipfiles,
    a_driver_check.datas,
    strip=False,
    upx=False,
    name='CHIRP',
)
