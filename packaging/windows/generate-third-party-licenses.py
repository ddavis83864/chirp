#!/usr/bin/env python3
"""Generates THIRD_PARTY_LICENSES.txt for the Windows CHIRP distribution.

Uses importlib.metadata to look up license information for packages
actually installed in the build virtual environment (the authoritative
source: this runs inside the same venv build-windows.ps1 built and
installed CHIRP's runtime dependencies into, so "installed" here means
"actually shipped"). Where a package's metadata doesn't reliably carry
license text or a clear license identifier, this falls back to a
checked-in, reviewed description below (STATIC_NOTICES) rather than
guessing or inventing text.

Run from an activated build venv:
    python packaging/windows/generate-third-party-licenses.py --output THIRD_PARTY_LICENSES.txt
"""
import argparse
import logging
import sys
import textwrap

logging.basicConfig(level=logging.INFO, format='%(message)s')
LOG = logging.getLogger(__name__)

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover - Python < 3.8 not supported here
    import importlib_metadata  # type: ignore


# Runtime dependencies actually bundled into the PyInstaller CHIRP.exe
# distribution, per requirements.txt and packaging/windows/chirp.spec's
# hiddenimports. Kept as an explicit list (rather than "whatever happens
# to be installed") so this script fails loudly if a dependency it
# expects to attribute is missing, instead of silently omitting it.
EXPECTED_PACKAGES = [
    'wxPython',
    'pyserial',
    'requests',
    'yattag',
    'suds',
    'lark',
    'pywin32',
    'pyinstaller',
    'pyinstaller-hooks-contrib',
]

# Reviewed, checked-in attribution for components that either aren't
# installed as a discoverable Python package (the CPython runtime itself,
# PyInstaller's compiled bootloader) or whose installed metadata doesn't
# reliably carry a usable license identifier/text. Text here is a factual
# summary of the license each project publishes, not an invented license.
STATIC_NOTICES = [
    (
        'Python',
        'https://www.python.org/',
        'Python Software Foundation License (PSF License), a permissive, '
        'BSD-style license. See https://docs.python.org/3/license.html '
        'for the full text. The CPython interpreter and standard library '
        'are bundled by PyInstaller into this distribution.',
    ),
    (
        'PyInstaller bootloader',
        'https://pyinstaller.org/',
        "PyInstaller's compiled bootloader executables (the small native "
        'stub that unpacks and launches CHIRP.exe) are distributed under '
        'the GPLv2 with a linking exception, so bootloader-linked '
        'applications are not required to be GPL-licensed themselves. '
        'See https://pyinstaller.org/en/stable/license.html for the '
        'full text. The PyInstaller Python package itself (used only at '
        'build time, not redistributed as source here) is GPLv2+.',
    ),
    (
        'wxWidgets (native library underlying wxPython)',
        'https://www.wxwidgets.org/',
        'wxWindows Library Licence, a permissive LGPL-based license with '
        'an exception permitting static linking and binary distribution '
        'without disclosing your own source. See '
        'https://github.com/wxWidgets/wxWidgets/blob/master/docs/licence.txt '
        'for the full text. wxWidgets is bundled as compiled DLLs inside '
        'wxPython, which this application links against.',
    ),
]


def collect_installed_licenses():
    found = []
    missing = []
    for name in EXPECTED_PACKAGES:
        try:
            dist = importlib_metadata.distribution(name)
        except importlib_metadata.PackageNotFoundError:
            missing.append(name)
            continue
        meta = dist.metadata
        license_field = meta.get('License') or ''
        classifiers = [
            c for c in meta.get_all('Classifier', [])
            if c.startswith('License ::')
        ]
        home_page = meta.get('Home-page') or meta.get('Project-URL') or ''
        found.append({
            'name': dist.metadata['Name'] or name,
            'version': dist.version,
            'license_field': license_field.strip(),
            'classifiers': classifiers,
            'home_page': home_page,
        })
    return found, missing


def render(found, missing):
    lines = []
    lines.append('THIRD-PARTY LICENSES')
    lines.append('=====================')
    lines.append('')
    lines.append(
        'This document lists material third-party runtime components '
        'bundled into the CHIRP Windows Community Edition distribution '
        '(the portable ZIP and the installer both contain the same '
        'PyInstaller application bundle). CHIRP itself is licensed '
        'under the GNU General Public License v3 or later -- see '
        'LICENSE in this distribution. Listing a component here does '
        "not change CHIRP's own license.")
    lines.append('')

    lines.append('Installed package metadata (from the build environment)')
    lines.append('---------------------------------------------------------')
    lines.append('')
    for pkg in found:
        lines.append(f"{pkg['name']} {pkg['version']}")
        if pkg['license_field']:
            lines.append(f"  License: {pkg['license_field']}")
        for c in pkg['classifiers']:
            lines.append(f"  {c}")
        if pkg['home_page']:
            lines.append(f"  Project: {pkg['home_page']}")
        lines.append('')

    if missing:
        lines.append(
            '## WARNING: the following expected runtime dependencies '
            'were not found in the build environment metadata and could '
            'not be attributed automatically:')
        for name in missing:
            lines.append(f"  - {name}")
        lines.append(
            '  This is a packaging defect if any of these are actually '
            'bundled into CHIRP.exe -- verify requirements.txt and this '
            "script's EXPECTED_PACKAGES list agree before shipping.")
        lines.append('')

    lines.append('Reviewed attribution for non-package components')
    lines.append('---------------------------------------------------------')
    lines.append('')
    for name, url, text in STATIC_NOTICES:
        lines.append(name)
        lines.append(f"  Project: {url}")
        for wrapped in textwrap.wrap(text, width=78):
            lines.append(f"  {wrapped}")
        lines.append('')

    return '\n'.join(lines).rstrip() + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument(
        '--allow-missing', action='store_true',
        help='Do not fail if an expected package is missing from the '
             'build environment (only for local iteration; CI should not '
             'set this).')
    args = p.parse_args(argv)

    found, missing = collect_installed_licenses()
    text = render(found, missing)

    with open(args.output, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    LOG.info("%s", text)

    if missing and not args.allow_missing:
        LOG.error(
            "error: %d expected package(s) missing from build "
            "environment metadata; re-run with --allow-missing only "
            "for local iteration, not in CI.", len(missing))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
