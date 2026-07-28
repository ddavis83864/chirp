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

"""Data-source adapters. Every candidate this module produces carries
real provenance -- which source, when, how old the record is -- and
none of it comes from an AI provider (see providers.py's docstring for
why that boundary matters).

Categories and what backs them in this release:

  - Amateur repeaters/GMRS: chirp.sources.repeaterbook.RepeaterBook
    (existing, reused as-is -- covers both via its `service` param).
  - Amateur satellites: chirp.sources.amsats.RadioAmateurSatellites
    (existing, reused as-is).
  - Amateur calling/simplex frequencies: a small curated static table,
    reusing chirp.memcolors.frequency_data (already curated for the
    memory color-coding feature) rather than duplicating it.
  - NOAA weather: a small curated static table (no existing adapter).
  - Aviation: guard/emergency frequencies only (121.5/243.0 MHz), from
    a small curated static table -- there is no airport/CTAF/tower
    frequency database available in this codebase or release, so
    airport-specific aviation programming is explicitly NOT supported
    (see docs/programming_assistant.md's known limitations).
  - Marine, public safety, business, railroad: NO source is
    implemented in this release. Requesting them returns an empty
    result with a "source unavailable" plan warning rather than
    fabricating data -- per this feature's own policy, AI memory is
    never used as a substitute frequency database.

Every fetch function is synchronous (network I/O happens in-thread);
the wx UI layer is responsible for running it off the UI thread -- see
chirp.wxui.programming_assistant.
"""

import logging
import time

import requests

from chirp import chirp_common
from chirp.assistant import converter
from chirp.assistant import models
from chirp.assistant import provenance as provenance_mod
from chirp.memcolors import frequency_data
from chirp.sources import amsats
from chirp.sources import base as sources_base
from chirp.sources import fips
from chirp.sources import repeaterbook

LOG = logging.getLogger(__name__)


def _describe_fetch_failure(exc):
    """Turn a raw fetch exception into a short, categorized reason a
    user can act on, instead of an arbitrary str(exception) -- a
    connection timeout, a DNS/connection failure, and some other
    internal error all read very differently to a non-technical user,
    even though today's underlying adapters don't consistently
    distinguish them at the point where they signal failure."""
    if isinstance(exc, requests.exceptions.Timeout):
        return 'the request timed out'
    if isinstance(exc, requests.exceptions.ConnectionError):
        return 'could not connect (network unreachable or offline)'
    if isinstance(exc, requests.exceptions.HTTPError):
        return 'the server returned an error (%s)' % exc
    return str(exc)


class _CollectingStatus(sources_base.QueryStatus):
    """A headless base.QueryStatus that just remembers what happened,
    for use by both tests and any caller that doesn't have a UI status
    callback to forward to."""

    def __init__(self):
        self.messages = []
        self.failed = None
        self.ended = False

    def send_status(self, status, percent):
        self.messages.append((status, percent))

    def send_end(self):
        self.ended = True

    def send_fail(self, reason):
        self.failed = reason


def memory_to_candidate(memory, source_name, service, source_id='',
                        record_age_days=None,
                        confidence=models.CONFIDENCE_HIGH):
    """Convert a chirp_common.Memory (as produced by an existing
    chirp.sources.* adapter) into a ChannelCandidate. The inverse of
    converter.candidate_to_source_memory().

    Known limitation: chirp_common.Memory has no field for the source
    coordinates a fetched item was found at (RepeaterBook's own
    item_to_memory() doesn't preserve Lat/Long onto the Memory it
    returns), so per-candidate distance isn't available here even
    though the source itself sorted/filtered by distance -- see
    docs/programming_assistant.md.
    """
    tx_freq = converter.tx_freq_from_memory(memory)

    prov = provenance_mod.from_source(
        source_name, source_record_id=source_id, fetched_at=time.time(),
        record_age_days=record_age_days,
        fields=('freq', 'tx_freq', 'mode', 'tmode', 'rtone', 'ctone',
                'dtcs', 'rx_dtcs', 'dtcs_polarity'))

    return models.ChannelCandidate(
        source=source_name,
        source_record_id=source_id,
        service=service,
        group='',
        label=memory.name or memory.comment or chirp_common.format_freq(
            memory.freq),
        freq=memory.freq,
        tx_freq=tx_freq,
        mode=memory.mode,
        tmode=memory.tmode,
        rtone=memory.rtone,
        ctone=memory.ctone,
        dtcs=memory.dtcs,
        rx_dtcs=memory.rx_dtcs,
        dtcs_polarity=memory.dtcs_polarity,
        confidence=confidence,
        provenance=prov,
    )


def _resolve_us_state(name):
    if not name:
        return None
    name = name.strip()
    for state in fips.FIPS_STATES:
        if state.lower() == name.lower():
            return state
    return None


def fetch_repeaterbook(request, service, status=None):
    """@service: '' for amateur, 'gmrs' for GMRS -- RepeaterBook covers
    both through the same adapter. Returns (candidates, error_or_None).
    """
    status = status or _CollectingStatus()
    state = _resolve_us_state(_state_hint(request))
    if not state:
        return [], ('RepeaterBook requires a resolvable US state; '
                    '%r could not be matched to one. Enter the state '
                    'name explicitly, or coordinates only cover '
                    'distance sorting, not the initial data set.' %
                    (request.location_text,))

    radio = repeaterbook.RepeaterBook()
    params = dict(
        lat=request.latitude or 0, lon=request.longitude or 0,
        dist=request.radius_miles, filter='', bands=[], modes=[],
        fmconv=True, openonly=True, cached=True, country='United States',
        state=state, service=service,
        service_display='GMRS' if service == 'gmrs' else 'Amateur')
    try:
        radio.do_fetch(status, dict(params))
    except Exception as e:
        LOG.exception('RepeaterBook fetch failed: %s', e)
        return [], _describe_fetch_failure(e)

    if status.failed:
        return [], status.failed

    service_kind = models.SERVICE_GMRS if service == 'gmrs' else \
        models.SERVICE_HAM
    candidates = []
    for i in range(len(radio._memories)):
        memory = radio.get_memory(i)
        if memory.empty:
            continue
        candidates.append(memory_to_candidate(
            memory, 'RepeaterBook', service_kind,
            source_id=str(memory.number)))
    return candidates, None


def _state_hint(request):
    """Best-effort state name from the request, without geocoding --
    either the caller already resolved and stored it in notes-adjacent
    fields, or location_text itself names a state directly."""
    return _resolve_us_state(request.location_text) or request.location_text


def fetch_satellites(request, status=None):
    status = status or _CollectingStatus()
    radio = amsats.RadioAmateurSatellites()
    try:
        radio.do_fetch(status, {})
    except Exception as e:
        LOG.exception('Satellite fetch failed: %s', e)
        return [], _describe_fetch_failure(e)
    if status.failed:
        return [], status.failed
    candidates = []
    for i in range(len(radio._memories)):
        memory = radio.get_memory(i)
        if memory.empty:
            continue
        candidates.append(memory_to_candidate(
            memory, 'Radio Amateur Satellites', models.SERVICE_SATELLITE,
            source_id=str(memory.number),
            confidence=models.CONFIDENCE_MEDIUM))
    return candidates, None


def static_weather_candidates(request):
    """All 7 NOAA Weather Radio channels. Not geo-specific by content
    (there's no per-transmitter lookup here) -- programming all 7 onto
    a receive-only radio is the standard, safe, universally-useful
    approach; the user scans for whichever comes in locally."""
    candidates = []
    for i, freq in enumerate(sorted(frequency_data.WEATHER_FREQS_HZ)):
        candidates.append(models.ChannelCandidate(
            source='static_weather', source_record_id='wx%i' % i,
            service=models.SERVICE_WEATHER, group='Weather',
            label='NOAA Weather %i' % (i + 1), freq=freq, mode='FM',
            confidence=models.CONFIDENCE_HIGH,
            provenance=provenance_mod.from_source(
                'Static table (NOAA channel plan)',
                fields=('freq', 'mode'))))
    return candidates


def static_aviation_candidates(request):
    """Aviation guard/emergency frequencies only -- see this module's
    docstring for why airport-specific frequencies aren't supported."""
    labels = {121500000: 'Aviation Guard/Emergency (Civil)',
              243000000: 'Aviation Guard/Emergency (Military)'}
    candidates = []
    for freq in sorted(frequency_data.AVIATION_EMERGENCY_FREQS_HZ):
        candidates.append(models.ChannelCandidate(
            source='static_aviation',
            source_record_id=str(freq),
            service=models.SERVICE_AVIATION, group='Aviation (Receive Only)',
            label=labels.get(freq, 'Aviation Guard/Emergency'),
            freq=freq, mode='AM',
            confidence=models.CONFIDENCE_HIGH,
            reason='Airport-specific tower/CTAF frequencies are not '
                   'available in this release; only the international '
                   'guard/emergency frequencies are included.',
            provenance=provenance_mod.from_source(
                'Static table (aviation guard/emergency)',
                fields=('freq', 'mode'))))
    return candidates


def static_calling_candidates(request):
    """Well-known amateur calling frequencies, reusing the table
    already curated for the memory color-coding feature rather than
    duplicating it."""
    candidates = []
    for freq in sorted(frequency_data.HAM_CALLING_FREQS_HZ):
        candidates.append(models.ChannelCandidate(
            source='static_ham_calling', source_record_id=str(freq),
            service=models.SERVICE_HAM, group='Amateur Simplex',
            label='Calling %s' % chirp_common.format_freq(freq),
            freq=freq, mode='FM',
            confidence=models.CONFIDENCE_MEDIUM,
            reason='Well-known calling frequency (operational aid, not '
                   'an exclusive or regulatory reservation).',
            provenance=provenance_mod.from_source(
                'Static table (amateur calling frequencies)',
                fields=('freq', 'mode'))))
    return candidates


def build_candidates(request, network_allowed=True):
    """Dispatch to the right source(s) for every service in
    request.requested_services. Returns (candidates, plan_warnings,
    skipped_sources) -- never raises; a failing/unavailable source
    produces a warning and an empty contribution, not a crash."""
    candidates = []
    warnings = []
    skipped = []

    services = set(request.requested_services)

    if models.SERVICE_HAM in services:
        if network_allowed:
            found, err = fetch_repeaterbook(request, '')
            if err:
                warnings.append(models.PlanWarning(
                    severity='warning',
                    message='RepeaterBook (amateur) unavailable: %s' % err))
                skipped.append('RepeaterBook (amateur)')
            else:
                candidates.extend(found)
            candidates.extend(static_calling_candidates(request))
        else:
            candidates.extend(static_calling_candidates(request))
            warnings.append(models.PlanWarning(
                severity='info',
                message='Network sources disabled: only static amateur '
                        'calling frequencies were included, not local '
                        'repeaters.'))

    if models.SERVICE_GMRS in services:
        if network_allowed:
            found, err = fetch_repeaterbook(request, 'gmrs')
            if err:
                warnings.append(models.PlanWarning(
                    severity='warning',
                    message='RepeaterBook (GMRS) unavailable: %s' % err))
                skipped.append('RepeaterBook (GMRS)')
            else:
                candidates.extend(found)
        else:
            warnings.append(models.PlanWarning(
                severity='info',
                message='Network sources disabled: no GMRS repeaters '
                        'could be looked up.'))
            skipped.append('RepeaterBook (GMRS)')

    if models.SERVICE_SATELLITE in services:
        if network_allowed:
            found, err = fetch_satellites(request)
            if err:
                warnings.append(models.PlanWarning(
                    severity='warning',
                    message='Satellite source unavailable: %s' % err))
                skipped.append('Radio Amateur Satellites')
            else:
                candidates.extend(found)
        else:
            skipped.append('Radio Amateur Satellites')

    if models.SERVICE_WEATHER in services:
        candidates.extend(static_weather_candidates(request))

    if models.SERVICE_AVIATION in services:
        candidates.extend(static_aviation_candidates(request))

    for service, label in (
            (models.SERVICE_MARINE, 'Marine'),
            (models.SERVICE_PUBLIC_SAFETY, 'Public safety'),
            (models.SERVICE_BUSINESS, 'Business/industrial'),
            (models.SERVICE_RAILROAD, 'Railroad'),
            (models.SERVICE_FRS, 'FRS'),
            (models.SERVICE_MURS, 'MURS')):
        if service in services:
            warnings.append(models.PlanWarning(
                severity='info',
                message='%s: no trusted data source is available in this '
                        'release; no channels were generated for this '
                        'service.' % label))
            skipped.append(label)

    return candidates, warnings, skipped
