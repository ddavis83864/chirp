"""PyInstaller entry point for CHIRP-driver-check.exe.

A tiny, separate console helper bundled alongside CHIRP.exe (same
PyInstaller Analysis/COLLECT output, so it runs with the exact same
frozen interpreter and frozen chirp package as the real GUI) whose only
job is to import chirp.drivers and report how many radio drivers the
frozen bundle actually registered.

This exists so CI can validate radio-driver discovery *inside the
packaged environment* rather than only in the build venv before
freezing -- PyInstaller's static analysis can silently miss a
dynamically-imported driver, and that class of bug would otherwise only
surface when a user tries to use a specific radio.

Exit code 0 and a "DRIVER_COUNT=<n>" line on success; nonzero and a
message on stderr on failure. Not a documented or supported CHIRP
command-line tool -- packaging validation only.
"""
import sys


def main():
    try:
        from chirp import directory
        # Importing chirp.drivers triggers each driver module's
        # @directory.register decorator to run, populating the registry --
        # mirrors what chirp.wxui does on startup before showing the
        # Download/Upload radio dialogs.
        import chirp.drivers  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - report any import failure
        print(f"error: failed to import chirp.drivers: {exc!r}",
              file=sys.stderr)
        return 1

    try:
        count = len(directory.DRV_TO_RADIO)
    except AttributeError:
        print("error: chirp.directory has no DRV_TO_RADIO registry -- "
              "chirp's driver-registry API may have changed.",
              file=sys.stderr)
        return 1

    print(f"DRIVER_COUNT={count}")
    if count <= 0:
        print("error: zero radio drivers registered in the frozen bundle",
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
