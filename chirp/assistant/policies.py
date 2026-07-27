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

"""Conservative, centralized transmit-eligibility policy.

A channel may be transmit-enabled only when ALL of the following hold:

    radio_can_transmit
    AND user_declares_authorization
    AND service_policy_allows_transmit

destination_supports_rx_only is tracked separately: it doesn't affect
whether transmit is *allowed*, it affects what happens when a channel
must be receive-only but the radio has no way to represent that -- see
converter.py, which blocks such channels rather than approximating.

This module makes no claim to be legal advice, and none of its
determinations should be read as one. It intentionally errs toward
receive-only or blocked over transmit-enabled whenever suitability
can't be established -- see each service's comment below for why.
"""

from chirp.assistant import models

# Services where no individual amateur/GMRS-style license exists in US
# rules, but the *equipment* must itself be certified for that service
# -- a CHIRP-programmable radio is essentially never such a certified
# device, so this release does not transmit-enable them. This is a
# conservative default; a future service-specific policy could refine
# it (e.g. detecting a radio explicitly marketed/certified for GMRS).
_LICENSE_BY_RULE_NO_TRANSMIT = (models.SERVICE_FRS,)
_LICENSE_BY_RULE_TRANSMIT_OK = (models.SERVICE_MURS,)


def _user_declares_authorization(service, request):
    if service == models.SERVICE_HAM or service == models.SERVICE_SATELLITE:
        return request.amateur_license != models.LICENSE_NONE
    if service == models.SERVICE_GMRS:
        return bool(request.has_gmrs_license)
    if service in _LICENSE_BY_RULE_TRANSMIT_OK:
        return True
    # FRS and every always-receive-only service: no declarable
    # authorization path in this feature.
    return False


def _service_policy_allows_transmit(service):
    if service in models.ALWAYS_RECEIVE_ONLY_SERVICES:
        # No generic "emergency" or other bypass -- these are always
        # receive-only in this release, full stop.
        return False
    if service in _LICENSE_BY_RULE_NO_TRANSMIT:
        return False
    if service in (models.SERVICE_HAM, models.SERVICE_SATELLITE,
                   models.SERVICE_GMRS) + _LICENSE_BY_RULE_TRANSMIT_OK:
        return True
    return False


def _policy_reason(service, auth, license_class):
    if service in models.ALWAYS_RECEIVE_ONLY_SERVICES:
        return ('%s is treated as receive-only in this release; equipment '
                'certification and licensing for transmit on this service '
                'are not verified by CHIRP.') % service
    if service == models.SERVICE_FRS:
        return ('FRS requires FCC-certified, fixed-antenna equipment. '
                'CHIRP-programmable radios are not certified FRS devices, '
                'so FRS channels are treated as receive-only here.')
    if service == models.SERVICE_GMRS:
        if not auth.user_declares_authorization:
            return ('GMRS channel requires a declared GMRS license to be '
                    'transmit-enabled.')
        return ('GMRS license declared. CHIRP does not verify that this '
                'radio is certified for GMRS transmission -- equipment '
                'suitability is the user\'s responsibility.')
    if service in (models.SERVICE_HAM, models.SERVICE_SATELLITE):
        if not auth.user_declares_authorization:
            return 'No amateur license class selected.'
        return 'Amateur license class %r declared.' % license_class
    if service == models.SERVICE_MURS:
        return 'MURS requires no individual license in the US.'
    return ''


def resolve_transmit_eligibility(service, freq_hz, tx_freq_hz, request,
                                 capability):
    """Return a models.ServiceAuthorization for one candidate channel.

    @freq_hz/@tx_freq_hz: the receive and (if different) transmit
    frequency in Hz; pass tx_freq_hz=None for a simplex/no-offset
    channel (freq_hz is then used for the transmit-band check too).
    """
    radio_can_receive = capability.supports_frequency(freq_hz)

    check_tx_freq = tx_freq_hz if tx_freq_hz is not None else freq_hz
    radio_can_transmit = capability.supports_frequency(check_tx_freq)

    user_declares_authorization = _user_declares_authorization(
        service, request)
    service_policy_allows_transmit = _service_policy_allows_transmit(service)
    destination_supports_rx_only = capability.supports_receive_only_duplex

    auth = models.ServiceAuthorization(
        service=service,
        radio_can_receive=radio_can_receive,
        radio_can_transmit=radio_can_transmit,
        user_declares_authorization=user_declares_authorization,
        service_policy_allows_transmit=service_policy_allows_transmit,
        destination_supports_rx_only=destination_supports_rx_only,
    )
    auth.reason = _policy_reason(service, auth, request.amateur_license)
    return auth
