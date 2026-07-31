"""PyInstaller entry point for the CHIRP.app macOS bundle.

Mirrors appimage/AppImageBuilder.yml's chirp-appimage-launcher: CHIRP's
default config dir (~/.chirp) is shared with any other CHIRP install on the
host (native package, source checkout, etc.), so isolate this bundled build
into its own config dir unless the user explicitly overrides it.
"""
import os
import sys

if '--config-dir' not in sys.argv:
    default_config_dir = os.path.join(
        os.path.expanduser('~'), '.chirp-macos')
    sys.argv += ['--config-dir', default_config_dir]

from chirp.wxui import chirpmain  # noqa: E402

sys.exit(chirpmain())
