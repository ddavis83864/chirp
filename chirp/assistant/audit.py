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

"""Privacy-conscious diagnostic logging for the Programming Assistant,
through CHIRP's normal `logging` module (no separate log file/sink).

Every function here logs COUNTS and OUTCOMES, never content: no API
keys, no authorization headers, no raw prompts, no precise coordinates,
no full codeplug contents, no existing-memory comments. Provider error
messages are expected to already be sanitized by chirp.assistant.providers
before they ever reach these functions -- see providers.ProviderError's
docstring.
"""

import logging

LOG = logging.getLogger('chirp.assistant')


def dialog_opened():
    LOG.info('Programming Assistant opened')


def provider_selected(kind):
    LOG.info('Assistant provider selected: %s', kind)


def intent_extraction_result(kind, success, error=None):
    if success:
        LOG.info('Assistant intent extraction succeeded (provider=%s)', kind)
    else:
        LOG.warning('Assistant intent extraction failed (provider=%s): %s',
                    kind, error)


def source_query_result(source_name, count, error=None):
    if error:
        LOG.warning('Assistant source %r failed: %s', source_name, error)
    else:
        LOG.info('Assistant source %r returned %i candidate(s)',
                 source_name, count)


def plan_built(candidate_count, validated_count, blocked_count):
    LOG.info('Assistant plan built: %i candidate(s), %i validated, '
             '%i blocked', candidate_count, validated_count, blocked_count)


def apply_result(applied_count, skipped_count, blocked_count,
                 adjusted_count, replaced_count):
    LOG.info('Assistant apply: %i applied, %i skipped, %i blocked, '
             '%i adjusted, %i existing replaced', applied_count,
             skipped_count, blocked_count, adjusted_count, replaced_count)


def apply_failed(error):
    LOG.error('Assistant apply failed: %s', error)


def undo_performed():
    LOG.info('Assistant apply undone')
