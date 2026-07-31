#!/usr/bin/env python3
"""Validates a built CHIRP Windows PyInstaller one-directory bundle.

This is a static, filesystem-level check (no process is launched here --
see smoke-test.ps1 for the launch smoke test). It is meant to run
immediately after `pyinstaller packaging/windows/chirp.spec` and before
the bundle is zipped or handed to Inno Setup, so packaging defects are
caught at the earliest possible stage.

Usage:
    python packaging/windows/validate-package.py --bundle-dir dist/CHIRP
"""
import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(message)s')
LOG = logging.getLogger(__name__)


def fail(errors, message):
    errors.append(message)
    LOG.error("FAIL: %s", message)


def ok(message):
    LOG.info("OK:   %s", message)


def check_executable(bundle_dir, errors):
    exe = os.path.join(bundle_dir, 'CHIRP.exe')
    if not os.path.isfile(exe):
        fail(errors, f"CHIRP.exe not found at {exe}")
        return
    size = os.path.getsize(exe)
    if size <= 0:
        fail(errors, f"CHIRP.exe at {exe} has non-positive size ({size})")
    else:
        ok(f"CHIRP.exe present, {size:,} bytes")


def check_dir_has_files(bundle_dir, relpath, min_count, errors, label=None):
    label = label or relpath
    full = os.path.join(bundle_dir, relpath)
    if not os.path.isdir(full):
        fail(errors, f"{label} directory not found: {full}")
        return 0
    count = sum(len(files) for _, _, files in os.walk(full))
    if count < min_count:
        fail(errors,
             f"{label} directory {full} has only {count} file(s), "
             f"expected at least {min_count}")
    else:
        ok(f"{label}: {count} file(s) under {full}")
    return count


def find_glob_any(bundle_dir, patterns, errors, label):
    import fnmatch
    matches = []
    for root, _dirs, files in os.walk(bundle_dir):
        for f in files:
            if any(fnmatch.fnmatch(f, p) for p in patterns):
                matches.append(os.path.join(root, f))
    if not matches:
        fail(errors,
             f"{label}: no file matching {patterns} found under "
             f"{bundle_dir}")
    else:
        ok(f"{label}: found {len(matches)} matching file(s), "
           f"e.g. {os.path.relpath(matches[0], bundle_dir)}")
    return matches


def check_wx_runtime(bundle_dir, errors):
    find_glob_any(
        bundle_dir, ['_core.pyd', '_core*.pyd'], errors,
        'wxPython core extension module')
    find_glob_any(
        bundle_dir, ['wxbase*.dll', 'wxmsw*.dll'], errors,
        'wxWidgets native DLL')


def check_python_runtime(bundle_dir, errors):
    find_glob_any(
        bundle_dir, ['python3*.dll'], errors, 'Python runtime DLL')


def check_drivers(bundle_dir, errors):
    # Driver modules are collected into the PyInstaller archive
    # (base_library.zip / the PYZ) rather than left as loose .py files,
    # so we can't just look for chirp/drivers/*.py on disk. Instead,
    # confirm the compiled driver package's presence signal: either a
    # PYZ-*.pyz archive (older PyInstaller) or the frozen module listing
    # embedded via the internal _pyi archive, both of which live next to
    # CHIRP.exe. As a second, stronger signal, chirp/drivers ships loose
    # non-.py data (none currently), so the authoritative check is left
    # to the in-process driver-registry probe in smoke-test.ps1, which
    # actually imports chirp.drivers and enumerates the registry inside
    # the packaged interpreter. This function only confirms the PyInstaller
    # archive itself exists and isn't empty, as a sanity floor.
    candidates = []
    for root, _dirs, files in os.walk(bundle_dir):
        for f in files:
            if f == 'base_library.zip' or f.endswith('.pyz'):
                candidates.append(os.path.join(root, f))
    if not candidates:
        fail(errors,
             "no PyInstaller base_library.zip/.pyz archive found -- "
             "the bundle does not look like a real PyInstaller output")
    else:
        for c in candidates:
            size = os.path.getsize(c)
            if size <= 0:
                fail(errors, f"{c} is empty")
            else:
                ok(f"PyInstaller archive present: "
                   f"{os.path.relpath(c, bundle_dir)} ({size:,} bytes)")
    LOG.info(
        "NOTE: full radio-driver-registry enumeration is validated by "
        "smoke-test.ps1, which runs CHIRP-driver-check.exe inside the "
        "packaged interpreter and confirms a non-empty registry -- this "
        "script only checks static bundle layout.")


def check_locales(bundle_dir, errors):
    check_dir_has_files(
        bundle_dir, os.path.join('_internal', 'chirp', 'locale'),
        1, errors, label='locale (.mo)') \
        or check_dir_has_files(
            bundle_dir, os.path.join('chirp', 'locale'),
            1, errors, label='locale (.mo)')


def check_icon_and_resources(bundle_dir, errors):
    find_glob_any(bundle_dir, ['chirp.ico'], errors, 'application icon')
    find_glob_any(bundle_dir, ['*.csv'], errors, 'stock configuration data')


def check_no_build_machine_paths(bundle_dir, errors, build_machine_markers):
    """Best-effort scan for absolute build-machine paths leaking into any
    checked *text* config/data file we ship (not into the compiled
    PyInstaller archives, which routinely contain build paths in debug
    info and are not something this project can or needs to scrub)."""
    suspect_exts = ('.csv', '.txt', '.json', '.yaml', '.cfg', '.ini')
    hits = []
    for root, _dirs, files in os.walk(bundle_dir):
        for f in files:
            if not f.lower().endswith(suspect_exts):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
            except OSError:
                continue
            for marker in build_machine_markers:
                if marker and marker in content:
                    hits.append((path, marker))
    if hits:
        for path, marker in hits:
            fail(errors,
                 f"{path} appears to contain a build-machine path "
                 f"marker: {marker!r}")
    else:
        ok("no build-machine path markers found in shipped text/data files")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle-dir', required=True,
                    help='Path to the PyInstaller COLLECT output '
                         '(e.g. dist/CHIRP)')
    p.add_argument('--build-machine-marker', action='append', default=[],
                    help='Repeatable. A string (e.g. the runner\'s home '
                         'directory) that must not appear in shipped '
                         'text/data files.')
    p.add_argument('--report', help='Optional path to write a JSON '
                                     'validation report to')
    args = p.parse_args(argv)

    bundle_dir = args.bundle_dir
    if not os.path.isdir(bundle_dir):
        LOG.error("error: bundle dir %s does not exist", bundle_dir)
        return 1

    errors = []
    check_executable(bundle_dir, errors)
    check_python_runtime(bundle_dir, errors)
    check_wx_runtime(bundle_dir, errors)
    check_drivers(bundle_dir, errors)
    check_locales(bundle_dir, errors)
    check_icon_and_resources(bundle_dir, errors)
    check_no_build_machine_paths(bundle_dir, errors, args.build_machine_marker)

    passed = not errors
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump({'passed': passed, 'errors': errors}, f, indent=2)

    if passed:
        LOG.info("Package validation PASSED.")
        return 0
    else:
        LOG.error(
            "Package validation FAILED (%d error(s)).", len(errors))
        return 1


if __name__ == '__main__':
    sys.exit(main())
