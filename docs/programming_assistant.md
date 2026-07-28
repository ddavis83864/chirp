# Programming Assistant

The Programming Assistant (Radio > Programming Assistant..., marked
"Experimental") turns a description of what you want programmed —
either typed structured fields, or an optional AI-interpreted plain
description — into a previewed, editable batch of proposed memories
that you approve before anything is written to the open image.

**Sample request:**

> I live near Coeur d'Alene. I fly general aviation. I camp. I have a
> GMRS license and an Amateur Radio Technician license. Program my
> radio.

## What it does

- Deterministically builds a proposed set of channels from trusted
  sources (see below), scoped to the services you request.
- Fully usable with **no AI provider configured** — every field the AI
  would fill in can be entered directly.
- Groups, deduplicates, names, and allocates memory numbers for the
  proposed channels without touching your existing memories.
- Converts and validates every proposed channel through CHIRP's own
  `chirp.import_logic`/`RadioFeatures.validate_memory()` for the
  specific radio you have open — the same gate a normal paste or import
  goes through.
- Shows a full preview (frequency, duplex, tone, mode, status,
  source/provenance) before anything is applied, and lets you exclude,
  rename, or reorder individual entries.
- Applies only what you approve, to the currently open image, as **one
  undoable action**.

## What it does not do

- It does not open a serial port, clone from a radio, or upload to a
  radio. Applying a plan only changes the open in-memory image; you
  still use Radio > Upload to Radio yourself when ready.
- It does not treat AI output as a source of frequencies, tones,
  offsets, or any other technical fact. An AI provider's only job is
  turning your typed sentence into the same structured fields the
  manual form uses (location, radius, license, requested services,
  channel limit, etc.) — never a specific channel.
- It does not verify your license or legal authorization to transmit.
  It also does not certify that a given radio is approved equipment for
  a given service (e.g. GMRS). See "Regulatory disclaimer" below.
- It does not overwrite existing, populated memories by default, and
  never touches protected or immutable memories.

## The deterministic wizard (no AI required)

1. **Describe** — optional free-text box, plus the same structured
   fields directly: location, radius, amateur license class, GMRS
   license declaration, activities, requested services, receive-only
   services, channel limit, naming style, existing-memory handling,
   protected memory ranges, and an optional target memory range.
2. **Confirm** — a read-only summary of exactly what will be queried
   and built; nothing is queried until you continue from here.
3. **Review** — a checkable table of every proposed channel with its
   status (Ready / Adjusted / Warning / Blocked / Receive-only /
   Duplicate / Existing conflict / Source unavailable / Unsupported by
   radio), source, and details. Uncheck anything you don't want.
4. **Result** — after Apply, a count of applied/skipped/blocked/
   adjusted/replaced entries, and a reminder that the image has not
   been uploaded to a radio.

## Data sources and provenance

| Category | Source in this release | Notes |
|---|---|---|
| Amateur repeaters | `chirp.sources.repeaterbook.RepeaterBook` (existing, reused) | Network, cached 30 days |
| GMRS repeaters | Same RepeaterBook adapter, `service='gmrs'` | Network |
| Amateur calling/simplex | Static table (shared with the memory color-coding feature's `chirp.memcolors.frequency_data`) | Offline, always available |
| Amateur satellites | `chirp.sources.amsats.RadioAmateurSatellites` (existing, reused) | Network |
| NOAA Weather | Static table (all 7 channels) | Offline; not geo-filtered — a receiver just scans for whichever comes in locally |
| Aviation | Static table, **guard/emergency frequencies only** (121.5/243.0 MHz) | Offline. No airport/CTAF/tower database exists in this codebase — airport-specific aviation frequencies are **not supported** in this release |
| FRS, MURS, marine, public safety, business, railroad | **Not implemented** | Requesting these produces a "source unavailable" warning, not fabricated data |

Every proposed channel shows its source and, where known, how old the
underlying data is. Nothing is ever presented as more current or
authoritative than it actually is. Network source failures produce a
warning and an empty contribution for that source — they never crash
the assistant or fall back to guessed data.

## Receive-only and transmit policy

A channel is only ever transmit-enabled when **all** of the following
hold (`chirp.assistant.policies`):

- the destination radio can technically transmit on that frequency,
- you've declared the relevant authorization (an amateur license class
  for ham/satellite, an explicit GMRS license declaration for GMRS),
- and service policy allows it.

Weather, aviation, marine, public safety, business, and railroad
channels are **always** receive-only in this release, regardless of any
license or activity you enter — there is no bypass. FRS is also always
receive-only, since a CHIRP-programmable radio is essentially never a
certified FRS device. If a radio can't represent a receive-only channel
at all (no "off" duplex support), that channel is **blocked**, not
approximated as a transmit-capable simplex channel.

## Regulatory disclaimer

The Programming Assistant organizes publicly available and curated
frequency information into a proposed set of radio memories. It does
not verify your license or authorization to transmit, and a radio's
technical ability to transmit on a frequency does not establish legal
authorization or equipment certification for that service. You remain
responsible for operating lawfully. This text is also shown in the
Review page's "Regulatory & Privacy Details..." button.

## Privacy and AI configuration

- Reachable from the Describe page's "Configure AI Provider..." button.
- Providers: **Disabled** (default), **OpenAI-compatible** (any Chat
  Completions-compatible HTTP endpoint), or **Ollama** (a local
  server's native `/api/chat`). No remote call happens until you
  explicitly click "Interpret with AI" after configuring a provider.
- An AI provider is given only your typed text — never radio image
  bytes, serial port details, file paths, or existing memory comments.
- No OS keyring dependency exists in this project, so API keys are
  handled conservatively: an environment variable
  (`CHIRP_ASSISTANT_API_KEY`) takes precedence, then optional
  session-only entry, then optional persisted storage using the same
  (explicitly non-secure, obfuscated) mechanism CHIRP already uses for
  other passwords — the preferences dialog says so plainly.
- Precise coordinates are never sent anywhere unless you explicitly
  enable "Share precise coordinates" on the Confirm page; otherwise
  only your typed location text/state is used.
- Provider output is validated JSON against a strict schema
  (`chirp.assistant.models.ProgrammingRequest`) — unknown fields,
  out-of-range values, and anything that isn't a recognized structured
  field are dropped, never executed. See `chirp/assistant/providers.py`
  for the full trust-boundary explanation.

## Undo and apply

Applying a plan wraps every approved memory write in one
`ChirpMemEdit.undo_context()` — the same mechanism the existing
"Insert Rows" and paste-anyway features use — so the entire result is
a single Undo entry. Existing memories are preserved by default;
replacing a conflicting existing memory requires explicitly enabling
"allow duplicate replacement," and even then it's shown in the preview
before you approve it.

Apply is **not** an atomic all-or-nothing write: if one entry in a
batch unexpectedly fails to write, entries already applied before it
are not automatically rolled back. What Apply does guarantee, and what
has regression test coverage
(`test_partial_apply_failure_reports_and_undo_still_works` in
`tests/unit/test_wxui_programming_assistant.py`), is that the whole
batch — including any partial success — is still exactly one Undo
entry, so a single Undo always fully reverts everything Apply did,
whether it fully succeeded or not. The Result page's failure count
tells you if anything didn't apply.

A candidate targeting an immutable or special destination memory is
already blocked during preview/validation, before Apply runs at all —
converting a candidate goes through CHIRP's own `import_logic`, which
calls the destination radio's `check_set_memory_immutable_policy()`
and refuses the candidate rather than let Apply attempt an invalid
write (`test_immutable_memory_blocked_before_apply_not_silently_written`
in the same file).

If a target memory becomes occupied after the plan was built but
before Apply actually runs (a manual edit elsewhere, or clicking
Apply a second time on an already-applied plan), that candidate is
blocked rather than silently overwritten — see
`AssistantService.finalize_for_apply()` and
`test_finalize_blocks_slot_occupied_since_plan_was_built` /
`test_reapplying_the_same_plan_is_blocked_not_silently_repeated` in
`tests/unit/test_assistant_service.py`. Applied memories persist
correctly through a normal File > Save and reopen, including
receive-only duplex settings and excluded candidates staying absent
(`tests/unit/test_assistant_save_reopen.py`).

## Enabling/disabling

The Programming Assistant is **disabled by default** (`[assistant]
enabled` is false unless you turn it on) — see
`chirp.wxui.programming_assistant.assistant_enabled()`. Enable it from
**Help > Enable Programming Assistant (Experimental)**, next to the
existing Developer Mode and Reporting toggles; enabling shows a short
disclosure you must accept. Like Developer Mode, CHIRP must be
restarted after toggling this for the Radio menu item to appear or
disappear.

## Known limitations

- No airport/CTAF/tower frequency database — aviation is limited to the
  international guard/emergency frequencies.
- No source for FRS, MURS, marine, public safety, business, or railroad
  channels in this release.
- Location resolution from free text (e.g. "Coeur d'Alene") to a US
  state/coordinates is not implemented in this release; enter the state
  name and/or coordinates directly, or have an AI provider extract
  `location_text` and confirm/correct it before building the plan.
  RepeaterBook queries require a resolvable US state name.
- RepeaterBook-sourced candidates don't carry a per-candidate distance
  value in the preview (the adapter sorts by distance internally, but
  `chirp_common.Memory` has no field to carry the source coordinates
  back out) — see `chirp.assistant.sources.memory_to_candidate`'s
  docstring.
- Apply is one undoable action but is not atomic (see "Undo and apply"
  above): a mid-batch failure does not roll back entries already
  written, though a single Undo still reverts the whole batch.

## Developer architecture

```
chirp/assistant/            (no wx dependency; independently unit-tested)
    models.py       typed request/candidate/plan/provenance dataclasses
    capability.py   normalizes a RadioFeatures into a queryable snapshot
    policies.py     transmit-eligibility policy (the ONLY place that decides)
    sources.py      source adapters + static tables; dispatch by service
    provenance.py   ChannelProvenance builders/summaries
    planner.py      deterministic dedup/group/name/order/allocate
    converter.py    ChannelCandidate -> chirp_common.Memory via import_logic
    validator.py    destination-radio validate_memory() classification
    providers.py    AI provider interface (disabled/OpenAI-compatible/Ollama)
    service.py      coordinates the above; the wx layer's only entry point
    audit.py         privacy-conscious logging helpers

chirp/wxui/programming_assistant.py   the wx.adv.Wizard UI (thin layer)
```

### Adding a source adapter

Add a function to `sources.py` returning `(list[ChannelCandidate], error_or_None)`
(see `fetch_repeaterbook`/`fetch_satellites` for the network pattern, or
`static_weather_candidates` for the offline pattern), then dispatch to
it from `build_candidates()` based on `request.requested_services`.
Reuse an existing `chirp.sources.*` adapter if one exists for your
category — don't write a new network client if a trusted one already
exists.

### Adding an AI provider

Subclass `providers._HTTPJSONProvider`, implement `_build_payload(text)`
and `_extract_content(response_json)`, and register it in
`providers.create_provider()`. The shared base class already handles
timeouts, no-retry, size limits, cancellation, and sanitized error
messages — a new provider should not need to touch any of that.

### Testing

```
tox -e unit -- tests/unit/test_assistant_*.py tests/unit/test_wxui_programming_assistant.py -v
```

`chirp/assistant/*` has no wx dependency and is tested with plain
`unittest`/fakes. `chirp/wxui/programming_assistant.py` is tested with
a real (not mocked) `wx.App`, since `wx.adv.Wizard` page-chaining isn't
meaningfully testable behind a mock — see the top of
`tests/unit/test_wxui_programming_assistant.py` for why.
