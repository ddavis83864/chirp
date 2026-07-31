# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the CHIRP.app macOS bundle.
#
# Run via ./packaging/macos/build_app.sh from the repo root; do not invoke
# pyinstaller on this file directly outside that script, since build_app.sh
# compiles chirp/locale/*.po -> *.mo first (PyInstaller only picks up files
# that already exist on disk) and exports the CHIRP_APP_VERSION /
# CHIRP_BUNDLE_ID environment variables this spec reads.
import os

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(SPEC)), '..', '..'))

APP_VERSION = os.environ.get('CHIRP_APP_VERSION', '1.12.0')
BUNDLE_ID = os.environ.get('CHIRP_BUNDLE_ID', 'com.ddavis83864.chirp')
MIN_MACOS = os.environ.get('CHIRP_MIN_MACOS', '11.0')
# 'x86_64', 'arm64', 'universal2', or unset for PyInstaller's default
# (native arch of the interpreter running the build).
TARGET_ARCH = os.environ.get('CHIRP_TARGET_ARCH') or None

hiddenimports = (
    collect_submodules('chirp.drivers')
    + collect_submodules('chirp.wxui')
    + collect_submodules('chirp.cli')
    + collect_submodules('chirp.sources')
    + collect_submodules('chirp.memcolors')
    + collect_submodules('chirp.profiles')
    + collect_submodules('chirp.assistant')
    + ['yattag', 'suds', 'lark', 'pyserial']
)

# Resource data carried inside the bundle. Mirrors MANIFEST.in's package_data
# set (png/svg/ico/1/desktop/metainfo + stock_configs + compiled locale),
# plus the macOS-only .icns icon that MANIFEST.in has no reason to include
# for the sdist. Excludes the *.xcf GIMP source files: multi-megabyte
# editable sources for the welcome-screen art that are never read at
# runtime (only the exported .png files are).
datas = [
    (os.path.join(REPO_ROOT, 'chirp', 'share', pattern), 'chirp/share')
    for pattern in (
        '*.png', '*.svg', '*.ico', '*.icns', '*.1',
        '*.desktop', '*.metainfo.xml', '*.yaml',
    )
] + [
    (os.path.join(REPO_ROOT, 'chirp', 'stock_configs', '*.csv'),
     'chirp/stock_configs'),
    (os.path.join(REPO_ROOT, 'chirp', 'locale', '*', 'LC_MESSAGES', '*.mo'),
     'chirp/locale'),
]

block_cipher = None

a = Analysis(
    [os.path.join(REPO_ROOT, 'packaging', 'macos', 'launcher.py')],
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
    name='chirp',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=TARGET_ARCH,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='chirp',
)

app = BUNDLE(
    coll,
    name='CHIRP.app',
    icon=os.path.join(REPO_ROOT, 'chirp', 'share', 'chirp.icns'),
    bundle_identifier=BUNDLE_ID,
    version=APP_VERSION,
    info_plist={
        'CFBundleName': 'CHIRP',
        'CFBundleDisplayName': 'CHIRP',
        'CFBundleExecutable': 'chirp',
        'CFBundleIdentifier': BUNDLE_ID,
        'CFBundleShortVersionString': APP_VERSION,
        'CFBundleVersion': APP_VERSION,
        'CFBundlePackageType': 'APPL',
        'CFBundleIconFile': 'chirp.icns',
        'LSMinimumSystemVersion': MIN_MACOS,
        'LSApplicationCategoryType': 'public.app-category.utilities',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': (
            'GNU General Public License v3 or later'),
        'NSRequiresAquaSystemAppearance': False,
    },
)
