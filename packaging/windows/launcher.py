"""PyInstaller entry point for the CHIRP.exe Windows bundle.

Unlike packaging/macos/launcher.py, this does not override --config-dir:
there is no other native Windows CHIRP distribution from this fork to
collide with, so the normal ~\\.chirp config directory (via
os.path.expanduser('~')) is what users, bug reports, and existing
documentation already expect.
"""
import sys

from chirp.wxui import chirpmain  # noqa: E402

sys.exit(chirpmain())
