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

"""Typed exceptions for the radio-profile domain layer.

Every expected failure mode raises one of these instead of a bare
ValueError/OSError, so callers (CLI, wx dialogs) can present a specific,
actionable message rather than a raw traceback. See module docstring in
chirp/profiles/__init__.py for the overall architecture.
"""


class ProfileError(Exception):
    """Base class for all radio-profile domain errors."""


class ProfileParseError(ProfileError):
    """The profile file is not well-formed JSON."""


class ProfileSchemaVersionError(ProfileError):
    """The profile's schema_version major component is not supported."""


class ProfileValidationError(ProfileError):
    """The profile failed structural or semantic validation.

    :param issues: a list of chirp.profiles.schema.Issue describing every
        problem found (not just the first), each with a field path.
    """

    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__(
            '; '.join(str(i) for i in self.issues) or
            'Profile validation failed')


class ProfileIOError(ProfileError):
    """A profile file could not be read or written."""


class CapabilityUnknownError(ProfileError):
    """A target radio's capability could not be reliably determined.

    Raised by safety-critical checks that must fail closed rather than
    assume a capability is present when the driver does not declare it.
    """


class NoPopulatedMemoriesError(ProfileError):
    """A source image has no populated memories to extract into a
    profile (every enumerable slot is empty or a special channel)."""


class CapacityExceededError(ProfileError):
    """The target radio does not have enough memory slots for the plan."""


class UnsafeOperationError(ProfileError):
    """A proposed change would violate a safety restriction.

    Unsafe items are blocked outright; this is raised only if code
    attempts to apply one directly without going through preview/approval.
    """


class AmbiguousMatchError(ProfileError):
    """A profile channel matches more than one existing memory candidate
    and cannot be resolved without user review."""


class TransactionError(ProfileError):
    """Applying an approved change set failed; the image was rolled back
    (or never modified) and remains in its original state."""
