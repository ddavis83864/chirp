# Copyright 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Single source of truth for deriving CHIRP's version from git.

setup.py (to set the installed package's metadata at build/install
time -- read by chirp/__init__.py at runtime via importlib.metadata,
as a fallback for an environment with no .git present, e.g. inside a
built AppImage) and chirp/__init__.py itself (as the preferred,
always-live source when running from a git checkout, e.g. the normal
dev workflow) both call derive_version_from_git() below, so there is
exactly one implementation of "how do we turn `git describe` output
into a version string" anywhere in this codebase.

This module intentionally has no imports from the rest of the `chirp`
package (or any third-party dependency): setup.py reads it by
exec()'ing its source directly, before `chirp` is installed and
without importing the `chirp` package itself, since setup.py must not
depend on the package it is in the middle of building. It can also be
run directly (`python3 chirp/_version.py`) to print the derived
version, e.g. from appimage/build.sh's own shell context.
"""

import os
import re
import subprocess

_DIRTY_SUFFIX_RE = re.compile(r'^(?P<rest>.+)-dirty$')
_TAG_PLUS_COMMITS_RE = re.compile(
    r'^(?P<tag>.+)-(?P<count>\d+)-g(?P<sha>[0-9a-f]+)$')
_BARE_SHA_RE = re.compile(r'^[0-9a-f]+$')

# This repo's git tags for AppImage releases (see "Adopt semantic
# versioning for AppImage releases") are named "appimage-vX.Y.Z" --
# the prefix is a release-channel marker, not part of the semantic
# version itself, so it's stripped for CHIRP_VERSION's purposes here.
# appimage/build.sh's own separate `git describe` call, used for the
# AppImage's distributable filename, is intentionally left alone: that
# is an established, different, external-facing naming convention
# (the filename already includes "appimage-v" on purpose), not the
# thing this module fixes.
_APPIMAGE_TAG_PREFIX = 'appimage-v'


def _strip_known_prefix(tag):
    if tag.startswith(_APPIMAGE_TAG_PREFIX):
        return tag[len(_APPIMAGE_TAG_PREFIX):]
    return tag


def derive_version_from_git(repo_root=None):
    """Return a version string derived from `git describe`, or None if
    git is unavailable or this isn't a git checkout at all (e.g. a
    source tarball with no .git directory) -- callers should fall back
    to a static placeholder in that case.

    `git describe --tags --always --dirty` output is normalized into a
    PEP 440-compatible string (setup.py passes this straight through
    as the package version, which setuptools validates):

    - Exactly on a tag, clean tree: the tag itself, e.g. "1.12.0".
    - Exactly on a tag, dirty tree: "1.12.0+dirty".
    - N commits past a tag: "1.12.0+3.gabcdef1" (dirty adds ".dirty").
    - No tag reachable at all: "0+gabcdef1" (dirty adds ".dirty"),
      since `--always` falls back to a bare abbreviated commit hash,
      which by itself isn't a valid version.

    Every case other than "exactly on a tag, clean tree" contains a
    "+" -- see is_dev_version() below, which relies on exactly that.
    """
    if repo_root is None:
        repo_root = os.path.dirname(os.path.abspath(__file__))
    try:
        described = subprocess.check_output(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            cwd=repo_root, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None
    if not described:
        return None

    dirty = False
    m = _DIRTY_SUFFIX_RE.match(described)
    if m:
        dirty = True
        described = m.group('rest')

    m = _TAG_PLUS_COMMITS_RE.match(described)
    if m:
        tag = _strip_known_prefix(m.group('tag'))
        version = '%s+%s.g%s' % (tag, m.group('count'), m.group('sha'))
    elif _BARE_SHA_RE.match(described):
        version = '0+g%s' % described
    else:
        # Exactly on a tag.
        version = _strip_known_prefix(described)
        if dirty:
            version += '+dirty'
            dirty = False

    if dirty:
        version += '.dirty'
    return version


def is_dev_version(version):
    """True unless @version is exactly a clean, tagged release version
    (e.g. "1.12.0") -- see derive_version_from_git()'s docstring: every
    other shape it can produce contains a "+", and the final static
    placeholder ("0+unknown", used when git and installed package
    metadata are both unavailable) is deliberately shaped the same way
    for exactly this reason, rather than being a special case here.
    """
    return '+' in version


if __name__ == '__main__':
    import sys
    sys.stdout.write((derive_version_from_git() or '0+unknown') + '\n')
