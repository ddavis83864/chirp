# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import importlib.metadata

from chirp._version import derive_version_from_git
from chirp._version import is_dev_version


def _get_version():
    # Prefer a live `git describe` over installed package metadata:
    # metadata is only as fresh as the last `pip install`, which for
    # the normal dev workflow (run-chirp.sh/run-chirp.ps1) only runs
    # once, on first setup -- it would otherwise go stale on every
    # later commit without a matching reinstall. A built distribution
    # (e.g. inside an AppImage) has no .git directory at all, so this
    # falls through to the metadata setup.py recorded at build time.
    version = derive_version_from_git()
    if version:
        return version
    try:
        return importlib.metadata.version('chirp')
    except importlib.metadata.PackageNotFoundError:
        return '0+unknown'


CHIRP_VERSION = _get_version()
#: True unless CHIRP_VERSION is exactly a clean, tagged release
#: version -- see chirp/_version.py's is_dev_version() docstring.
CHIRP_VERSION_IS_DEV = is_dev_version(CHIRP_VERSION)
