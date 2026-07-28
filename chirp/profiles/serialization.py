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

"""JSON (de)serialization for radio profiles.

Uses only json.loads/json.dumps -- no pickle, no yaml.load, no eval, no
arbitrary object deserialization of any kind, so a malicious or corrupt
profile file cannot execute code. Saving uses a temp-file-plus-
os.replace atomic write so a failure partway through can never corrupt
an existing profile on disk.
"""

import json
import os
import tempfile

from chirp.profiles import errors
from chirp.profiles import model
from chirp.profiles import schema
from chirp.profiles import validation


def to_dict(profile):
    return profile.to_dict()


def to_json(profile):
    """Deterministically-ordered, human-readable JSON text."""
    return json.dumps(profile.to_dict(), indent=2, sort_keys=True) + '\n'


def from_dict(data, validate=True):
    """Build a Profile from a plain dict, e.g. json.loads() output.

    Always checks schema_version and the presence of required top-level
    fields (these are structural gates, not optional). @validate=False
    skips the deeper semantic pass (validate_profile) for callers that
    need a best-effort in-memory object for a work-in-progress editor
    buffer; it never skips the schema-version/required-field checks.
    """
    if not isinstance(data, dict):
        raise errors.ProfileValidationError(
            [schema.Issue('$', 'Profile document must be a JSON object')])

    validation.check_schema_version(data)
    issues = validation.check_required_root_fields(data)
    profile = model.Profile.from_dict(data)
    if validate:
        issues = issues + validation.validate_profile(profile)
    if issues:
        raise errors.ProfileValidationError(issues)
    return profile


def from_json(text, validate=True):
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
        raise errors.ProfileParseError('Malformed JSON: %s' % e)
    return from_dict(data, validate=validate)


def save(profile, path, validate=True):
    """Atomically write @profile to @path.

    The profile is validated *before* anything on disk is touched. The
    write itself goes to a temp file in the same directory (so
    os.replace is an atomic rename on the same filesystem) and only
    replaces @path once the write and fsync succeed -- a failure midway
    leaves the original file, if any, untouched.
    """
    if validate:
        validation.validate_profile_or_raise(profile)
    text = to_json(profile)
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix='.profile-', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError as e:
        raise errors.ProfileIOError(
            'Failed to save profile to %s: %s' % (path, e))
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def load(path, validate=True):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        raise errors.ProfileIOError(
            'Failed to read profile from %s: %s' % (path, e))
    return from_json(text, validate=validate)
