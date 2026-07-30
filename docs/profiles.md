# Radio Profiles: developer documentation

## Profile vs. image

A CHIRP **image** is the device-specific contents of one radio: whatever
memory slots, banks, and settings that particular driver exposes, in that
driver's own binary or text format. A **profile** is a separate, portable
domain object: the channels, groups, priorities, and safety restrictions a
user cares about, independent of any one radio's memory map.

CHIRP can *adapt* a profile onto a supported target radio. It never
repurposes or extends existing image file formats to carry profile data, and
existing image load/save/download/upload workflows are unaffected by this
feature.

## Architecture

```
chirp/profiles/            pure Python, no wxPython import anywhere
  errors.py                 typed exceptions for every expected failure
  schema.py                 wire-format constants, enums, schema version,
                             the Issue type used by validation
  model.py                  the canonical dataclasses (Profile,
                             ProfileChannel, TransmitBehavior, ...)
  validation.py              structural + semantic validation, collecting
                             every problem as an Issue with a field path
  serialization.py          JSON (de)serialization, atomic save/load
  safety.py                 preservation of explicit receive-only intent
  capabilities.py           reads a target radio's declared RadioFeatures
  adaptation.py              per-channel classification (Exact/Adapted/
                             Degraded/Incompatible/Unsafe) and adaptation
  matching.py                matches profile channels against existing
                             memories in an open image
  placement.py               memory-number placement strategies
  conflicts.py                structured, cross-channel conflict objects
  changeset.py                ties matching+placement+adaptation+conflicts
                             into one deterministic, previewable ChangeSet
  extraction.py                builds a Profile from an already-open image

chirp/wxui/
  profilecontroller.py       the ONLY UI/domain boundary (section 3.4) --
                             dialogs never call chirp.profiles.* directly
  profileeditor.py            profile identity/defaults/groups/channel editor
  profileapply.py             apply-preview dialog (filter, approve/reject,
                             blocked items)
  main.py                     Profile menu + thin handler methods
```

The domain layer (`chirp/profiles/`) has zero wxPython dependency and is
independently unit-testable; see `tests/unit/test_profiles_*.py`. The wx
integration lives entirely under `chirp/wxui/profile*.py` and
`chirp/wxui/main.py`'s Profile menu section, and reaches the domain layer
only through `chirp.wxui.profilecontroller`.

### Reading a source radio's memories

`extraction.enumerate_source_memories(radio)` is the one place a radio's
current memory list is read for profile purposes (both extracting a
profile from a source image, and reading a target image's existing
memories before placement). It uses `RadioFeatures.memory_bounds`
unconditionally, for both fixed-capacity and dynamic/file-backed radios
(e.g. `chirp.drivers.generic_csv.CSVRadio`) alike: `memory_bounds` always
describes a radio's *current*, concrete, enumerable range, regardless of
`has_infinite_number` -- that flag means only "no fixed ceiling on how
large this may grow later" (it suppresses an out-of-range validation
warning), never "the current range is unsafe to read" or "this cannot be
enumerated." There is no invented maximum (100/500/1000/...) anywhere in
this path; a radio with N memories right now yields exactly N reads.
`errors.CapabilityUnknownError` is reserved for the genuinely different
case of a radio whose `memory_bounds` cannot be interpreted as a `(lo,
hi)` pair at all.

## Schema versioning

`schema.SCHEMA_VERSION = '1.0'` (`SCHEMA_MAJOR = 1`, `SCHEMA_MINOR = 0`).
`validation.check_schema_version()` rejects any document whose major version
doesn't match `SCHEMA_MAJOR` with `errors.ProfileSchemaVersionError`, before
anything else about the document is trusted. A future compatible minor bump
can add optional fields without breaking this release's ability to read a
newer-minor-version file; a major bump signals a shape change and is
rejected outright rather than guessed at.

## Logical channel identity

A channel's identity is `ProfileChannel.logical_id` -- a lowercase slug
(`local-cda-2m-repeater-01`, `noaa-weather-01`) -- never a memory number.
`model.ProfileChannel` has no memory-number field at all; a target memory
number is a placement *decision* made later by `placement.py` and recorded
only in a `changeset.ChangeSetItem.target_memory_number`, never as identity.
This is what makes a logical_id stable across renames, re-placement onto a
different memory, and application to a different radio model (section 3.2).

`extraction.make_logical_id()` derives one deterministically from an
existing memory's name (falling back to `channel-<number>` only as a seed
for unnamed memories, with numeric disambiguation on collision) when
building a profile from an open image.

## Compatibility classifications

`chirp.profiles.adaptation.adapt_channel(profile, channel, capabilities)` is
a pure function returning an `AdaptationResult` with one of five
classifications (`schema.CLASS_*`), most to least severe:

| Classification | Meaning | Example |
|---|---|---|
| `unsafe` | Blocked outright; never offered for approval | Receive-only channel would become transmit-capable |
| `incompatible` | Cannot be meaningfully represented; no proposed memory is produced | Digital mode on an analog-only radio; out-of-range receive frequency |
| `degraded` | Applied, but something is lost | Comment dropped; group membership not representable (no bank support) |
| `adapted` | Applied with a minor, reported transformation | Name abbreviated to fit; power tier mapped to nearest level |
| `exact` | No meaningful change needed | — |

`adaptation.SEVERITY` orders these; a channel's overall result is the worst
(most severe) of every per-dimension finding. `blocked` is `True` only for
`unsafe` -- `incompatible` channels also get no proposed memory, but are not
"blocked" in the safety sense (a `changeset.ChangeSetItem` for one gets
action `skip`, not `blocked`); see `changeset.build_changeset()`.

## Safety model

`chirp.profiles.safety` isolates the one hard guarantee: a channel the
profile marks `schema.TRANSMIT_RECEIVE_ONLY` never comes out the other end
of adaptation, overrides, or placement as transmit-capable.

- `model.TransmitBehavior.mode` is the single, explicit source of truth for
  transmit permission -- never inferred from duplex/offset alone.
- `schema.ALLOWED_OVERRIDE_FIELDS` structurally excludes any
  transmit-permission field, so a target-specific override (section 4.6)
  *cannot* carry a key that would re-enable transmit on a receive-only
  channel -- this is enforced by the schema itself, not just by a runtime
  check (though `safety.check_override_does_not_remove_safety()` also
  exists as defense-in-depth for callers that bypass `validation.py`).
- `adaptation._resolve_transmit()`: a receive-only channel is only ever
  proposed as target `duplex='off'` (CHIRP's own existing convention for "no
  transmit" -- see `chirp_common.Memory.duplex` and
  `RadioFeatures.validate_memory`); if the target has no `'off'` duplex value
  at all (`capabilities.can_enforce_receive_only()` is `False`), the result
  is `unsafe` and blocked, never silently downgraded to a warning.
- An **unspecified** transmit intent is never treated as permission to
  transmit (section 9.3): it defaults to receive-only, classified
  `degraded` with `lost=('transmit permission',)`, surfacing the ambiguity
  for the user to resolve explicitly rather than guessing "enabled".
- An out-of-band *transmit* request (rx in range, but the computed tx
  frequency is not) is downgraded to receive-only (`degraded`) rather than
  programmed as-is, **if** the target can enforce `'off'`; if it can't,
  that's `unsafe` and blocked (section 9.2).
- `capabilities.py` reports the handful of things `RadioFeatures` does not
  model at all (`scan_list_support()`, `empty_memory_behavior()`) as
  `None` (unknown) rather than assuming "supported" -- callers must fail
  closed on `None` (section 9.10).
- `capabilities.validate_memory()` delegates to the driver's own
  `RadioFeatures.validate_memory()` -- the authoritative safety net,
  re-run immediately before every mutation
  (`profilecontroller.apply_changeset()`), independent of whatever
  `adaptation.py` concluded (section 9.9).

## Placement strategies

`placement.plan_placement()` only decides numbers for channels with **no**
existing match -- a channel matched by `matching.py` always keeps the
matched memory's number, regardless of strategy (that's "update matching
channels" / "preserve existing memories" from the design doc: always-on
behaviors, not something a caller opts into).

- `PLACEMENT_FILL_EMPTY` -- lowest-numbered empty, non-immutable slots first.
- `PLACEMENT_APPEND` -- sequentially after the highest occupied/locked number.
- `PLACEMENT_REPLACE_RANGE` -- an explicit, caller-supplied list of memory
  numbers, one per channel needing placement. This is the only strategy that
  can overwrite an already-occupied, unmatched memory, and only because the
  caller explicitly chose that number; `PlacementDecision.replaces_existing`
  records this so it's surfaced as a conflict, never silently overwritten.

An immutable-locked existing memory (any `Memory.immutable` field set) is
never treated as available by any strategy, including `REPLACE_RANGE`.

## Matching

`matching.match_channel()` compares one proposed target memory (from
`adaptation.py`) against an image's existing memories using two signatures,
both **excluding name** (section 11: name is a weak signal, never identity):

1. The *full* operational-duplicate signature CHIRP itself already uses
   (`chirp_common.find_duplicate_memories`/`DUPE_SIGNATURE_FIELDS`) --
   if it matches **and** the name also matches, that's `MATCH_EXACT`
   ("already there, nothing to do"). If everything else matches but the
   name differs, that downgrades to `MATCH_UPDATE_CANDIDATE` (same
   channel, needs a name update).
2. A looser freq+duplex+offset-only signature for "same channel, something
   else changed" (tone, power, comment, skip). Two or more existing
   memories tying at this looser signature is `MATCH_AMBIGUOUS` and is
   never auto-resolved -- it's surfaced to the user as a conflict.

Profile-linkage metadata (section 16 -- a persisted logical_id-to-memory
mapping from a previous apply) would outrank both of these if present, but
that tracking is deferred past this release; every match today is
content-based.

## Conflicts and the change set

`conflicts.py` covers only the conflicts that are inherently cross-channel
or placement-level (two channels wanting one memory, capacity exceeded, an
immutable/locked target, an unresolved ambiguous match, two proposed
channels sharing a display name). Unsupported modes/tones and "valid to
receive but unsafe to transmit" are per-channel `adaptation.py`
classifications (`incompatible`/`unsafe`), not re-detected here; a
target-override removing a safety restriction is structurally impossible
(see Safety model above), so it isn't re-detected either -- this is a
deliberate design choice to avoid duplicating the same judgment in two
places with two different opinions.

`changeset.build_changeset(profile, capabilities, existing_memories,
placement_strategy, explicit_range)` ties matching + placement + adaptation
+ conflicts into one `ChangeSet` of `ChangeSetItem`s (action one of
`add`/`modify`/`keep`/`skip`/`conflict`/`blocked`; `move` is reserved for
future profile-linkage-based repositioning, unused in this release). It is a
pure function of its inputs -- same profile, same target capabilities, same
existing memories, same placement strategy/decisions -> same result,
deterministically (section 3.5). It never touches `existing_memories` or
mutates the profile.

Each item's `approval_state` defaults to `blocked` for blocked items,
`approved` for `keep` (nothing to decide), and `pending` for everything
else. `ChangeSet.set_approval()` raises `errors.UnsafeOperationError` if
called on a blocked item -- there is no code path that lets a UI "force"
approval of an Unsafe item.

## Transaction semantics

`chirp.wxui.profilecontroller.apply_changeset(memedit_widget, profile_name,
change_set)`:

1. Takes only `change_set.approved_items()` (`add`/`modify` actions with
   `approval_state == approved`).
2. Re-validates every one of them against the target's own
   `RadioFeatures.validate_memory()` *again*, immediately before touching
   anything. If any fails, `errors.ProfileValidationError` is raised and
   **nothing** is applied.
3. Applies every item inside one `memedit.undo_context()` -- CHIRP's
   existing per-editor undo/redo mechanism (`chirp/wxui/memedit.py`,
   `MemeditUndoContext`) -- so the whole transaction is exactly **one**
   entry in the normal Undo menu, e.g. "Apply North Idaho Camping profile".
   This reuses the same "validate everything against a throwaway copy
   first, then apply in one undo_context" idiom already used by bulk
   operations like CSV import and multi-memory drag
   (`memedit.memedit_import_all`, `_apply_column_value`).
4. If a mutation fails *unexpectedly* after step 2's pre-validation pass
   (should not happen in practice -- this is the residual case a driver
   raises for a reason `RadioFeatures.validate_memory` didn't catch),
   `apply_changeset()` explicitly reverses every item already applied in
   this transaction (`_rollback()`, using each item's recorded
   `existing_memory` or erasing back to empty) and raises
   `errors.TransactionError`. The image is left as it was before `apply()`
   was called.
5. Nothing is ever uploaded to a physical radio automatically. Applying a
   profile only ever changes the currently open, in-memory/file-backed
   image; the user reviews the result and initiates any radio upload
   through CHIRP's normal Download/Upload workflow, same as any other edit.

### Why step 4 doesn't just call `memedit_widget.set_memory()`

`memedit.ChirpMemEdit.set_memory()` routes through `do_radio()`, which --
for *both* of memedit's editor backends -- catches whatever the driver
raises and stashes it on the job object rather than re-raising it to the
caller; it only ever surfaces as a per-row red error indicator in the grid.
That's the right default for interactive single-cell edits, but it would
make step 4's rollback silently unreachable: an exception the driver raises
during `set_memory()` would never propagate to `apply_changeset()`'s
`try/except` at all.

`chirp.wxui.memedit` has two editor backends: `ChirpSyncEditor`
(synchronous, in-memory -- used for opened image files, `ChirpMemEdit`'s own
base class) and `ChirpAsyncEditor` (queues jobs to a background thread --
used for a live serial-connected radio, `ChirpLiveMemEdit`).
`apply_changeset()` tells them apart (`_is_live_radio()`) and, for a
synchronous target only, calls `memedit_widget._radio.set_memory()`
directly (recording undo state manually via
`memedit_widget._undo_ctx.record_current_memory()` first) instead of going
through `set_memory()`'s job wrapper -- so a driver failure raises
synchronously, right here, and step 4's rollback actually runs (this is
exercised by
`test_wxui_profiles.py::TransactionalApplyTest::test_failed_apply_rolls_back_and_raises`,
which injects a failure on the second of three memories and asserts the
image ends up with none of the three applied). This intentionally bypasses
`set_memory()`'s `FrozenMemory` copy-protection and `set_memory_extra()`
syncing for `ExternalMemoryProperties` radios (e.g. D-STAR call lists) --
an acceptable trade-off since profiles don't model those extra,
driver-specific properties in this release anyway (section 2: "translation
of every device-specific radio setting" is explicitly out of scope).

For a live radio (`_is_live_radio()` is `True`), doing the same direct call
would be unsafe -- `ChirpAsyncEditor`'s whole contract is that only its own
worker thread touches the radio object -- so `apply_changeset()` keeps using
`set_memory()`/`erase_memory()` as normal there. That means applying a
profile directly against a live radio connection has the same semantics as
any other existing bulk edit in CHIRP (queued jobs, per-row error
indication, one Undo entry) rather than the synchronous rollback guarantee
described above; this is not a regression from existing behavior, but it is
a real, documented difference (see Known limitations, below). Every
documented/tested apply workflow for this release targets an opened image
file, matching the "review, then explicitly upload" mental model (section
15.6/15.7).

## Target-specific overrides and composition

`model.TargetOverride` (selector: `capability_class` / `vendor_family` /
`driver` / `model`, in that ascending precedence order per
`schema.SELECTOR_PRECEDENCE`) lets a profile carry a radio-specific
adaptation (currently: `name`, `power_preference`, `preferred_memory_range`,
`preferred_group`, `scan_intent` -- see `schema.ALLOWED_OVERRIDE_FIELDS`)
separate from the canonical channel definition. Overrides are validated
(`validation.validate_override()`) but **not yet consumed** by
`adaptation.adapt_channel()` in this release -- the schema and model
reserve the field and precedence order, and safety structurally excludes
the one field that would matter most (transmit permission), but wiring
override resolution into the adaptation pipeline is deferred (see Known
limitations).

Full base/overlay profile **composition** (section 5) is out of scope for
this release entirely; the schema/model don't prevent adding it later (there
is no field that would conflict with a future `composition.py`), but no such
module exists yet.

## Extension points

- New placement strategies: add a `schema.PLACEMENT_*` constant and a branch
  in `placement.plan_placement()`.
- New conflict types: add a `schema.CONFLICT_*` constant and a detector in
  `conflicts.detect_conflicts()`.
- Consuming target overrides: resolve applicable `TargetOverride.fields`
  inside `adaptation.adapt_channel()` (after resolving profile defaults,
  before building the proposed `chirp_common.Memory`), respecting
  `schema.SELECTOR_PRECEDENCE`.
- Profile-linkage tracking (section 16): a small, versioned,
  application-managed record (profile_id, schema_version, content hash,
  last-applied timestamp, logical_id-to-memory-number mapping, target
  driver/model) would upgrade `matching.py`'s hierarchy without changing
  its public interface -- check linkage before the content-based
  signatures, not instead of them.
- Composition: a `composition.py` resolving base/overlay profiles into one
  effective `Profile` before it reaches `validation.py`/`adaptation.py`
  would slot in without changing either.

## Testing strategy

- `tests/unit/test_profiles_*.py` -- the pure-Python domain layer, zero wx
  dependency, covering model/validation/serialization/safety/capabilities/
  adaptation/matching/placement/conflicts/changeset/extraction.
- `tests/unit/fake_radios.py` -- representative target capability profiles
  (feature-rich, limited analog handheld, short-name, no-bank,
  restricted-range, cannot-enforce-receive-only, analog-only,
  immutable-memory) built directly from `chirp_common.RadioFeatures` --
  no physical hardware or specific vendor driver required.
- `tests/unit/test_wxui_profiles.py` -- real wx widget construction and
  interaction (menu, dialogs, apply/undo), skipped cleanly (not failed) when
  `$DISPLAY` is unset, and defensive against a pre-existing, unrelated test
  isolation gap where `test_wxui_radiothread.py` permanently replaces
  `sys.modules['wx']` with a mock for the rest of the process.
- `docs/examples/north_idaho_camping.chirp-profile.json` -- a fixture kept
  valid by `tests/unit/test_profiles_examples.py` as the schema evolves.

## Relationship to the Programming Assistant

Radio Profiles and the Programming Assistant (see
`docs/programming_assistant.md`) are independent, complementary
features. A profile is a portable, radio-independent description of
channels; the assistant instead creates and populates a normal,
device-specific memory image. Profile > Create Profile from Current
Image can turn any open image, including one the assistant built,
into a profile, but this is always an explicit, user-initiated step —
the assistant never produces or updates a profile on its own.

## Known limitations

- Target-specific overrides are validated and preserved through save/load,
  but not yet applied during adaptation (see Extension points).
- Base/overlay profile composition (section 5) is not implemented.
- Profile-to-image linkage tracking (section 16) is not implemented; every
  match is content-based (frequency/duplex/offset/tone), not
  linkage-assisted.
- Bank/group membership extraction from an open image
  (`extraction._extract_groups()`) is best-effort: it works when a radio's
  `MappingModel.get_memory_mappings()` is implemented, and is reported as an
  unknown/lost field (not silently empty) when it isn't.
- Applying a profile directly to a live serial-connected radio (as opposed
  to an opened image file) does not get the same synchronous
  rollback-on-unexpected-failure guarantee as file-backed images; it follows
  the same semantics as any other existing CHIRP bulk edit against a live
  radio (queued jobs, one Undo entry, per-row error indication on failure).
- The profile editor's channel grid is a `wx.ListCtrl` with a modal
  add/edit dialog per channel, not an inline spreadsheet-style grid; this
  was a deliberate first-release scope choice (section 18: reuse existing
  components "when practical," but "do not force profile channels into a
  device-specific model prematurely" -- `chirp.wxui.memedit`'s grid is built
  around `chirp_common.Memory`/live radio editing and is not a natural fit
  for editing a `ProfileChannel` directly).
