# Radio Profiles: user guide

A **Radio Profile** is your own portable radio setup -- which channels you
care about, how they're grouped, which ones are receive-only, what power
and scan behavior you prefer -- saved independently of any one radio. CHIRP
can apply the same profile to different supported radio models, adapting it
to what each one can actually do.

A profile is **not** a CHIRP image. An image is the exact contents of one
radio's memory. A profile is your intent; CHIRP figures out how to best
represent that intent on whatever radio you're currently working with.

All of this lives under the new **Profile** menu.

## Creating a profile from a radio image

1. Open (or download) the radio image you want to base a profile on. This
   includes CSV-backed images -- for example, the blank memory grid the
   Programming Assistant creates and lets you fill in -- not only
   downloaded/cloned images from a specific radio model.
2. **Profile > Create Profile from Current Image**.
3. Give the profile a name.
4. CHIRP shows a summary: how many channels were extracted, how many were
   skipped (empty slots and special/named channels aren't included), which
   fields were preserved as-is, which needed a small conversion, which
   couldn't be carried over at all, and how many channels were detected as
   receive-only.
5. The new profile opens in the profile editor so you can review or adjust
   it right away.
6. If you haven't saved the profile yet, CHIRP asks whether to save it now
   (see "Saving, sharing, and importing/exporting profiles" below) -- you
   can also decline and save later from **Profile > Save Profile**.

Only *populated* memories become channels; a completely blank image (no
memories programmed into it yet) has nothing to extract, and CHIRP tells
you so directly rather than creating an empty profile. A brand new CSV
grid's own starter row (the one pre-filled entry that gives a new
document something to click on) doesn't count as programmed either --
Create Profile treats it the same as an untouched row until you (or
Programming Assistant) actually change it.

Each channel gets a stable **logical ID** derived from its name (e.g. a
memory named "CDA Repeater" becomes `cda-repeater`). This ID is what CHIRP
uses to track the channel from now on -- it stays the same even if you
rename the channel, move it to a different memory slot, or apply the
profile to a completely different radio model.

## Editing a profile

**Profile > Edit Profile** opens the editor, with four tabs:

- **Identity** -- name, description, region.
- **Defaults** -- profile-wide defaults (mode, power preference, scan
  intent, naming style, duplicate-handling policy). Any channel can
  override these individually.
- **Groups** -- logical groups like "Local Repeaters," "Simplex," "Weather,"
  or "Emergency." A channel can belong to more than one group. Groups are
  profile metadata -- they're preserved even when you apply the profile to a
  radio that has no concept of banks or groups at all.
- **Channels** -- add, edit, or delete channels. Each channel has its
  receive frequency, transmit behavior (see below), tones, mode, power
  preference, scan intent, category, and group membership.

The bottom of the editor always shows current validation problems, if any.
**Save Profile** is disabled until the profile is valid.

**OK** in this dialog only accepts your edits and closes the editor --
it does not write anything to any memory image. The editor is a modal
dialog, so the main menu (including Apply, below) isn't reachable
while it's open; the editor itself reminds you of this, next to its
OK/Cancel buttons, so it's never unclear where Apply actually is once
you close it.

### Transmit behavior

Every channel has an explicit transmit setting, one of:

- **Transmit enabled** -- simplex, a repeater offset (+/-), or a full split
  transmit frequency.
- **Receive-only** -- this channel should never transmit, on any radio.
- **Unspecified** -- you haven't decided yet. CHIRP treats this the same as
  receive-only when applying the profile (it will never guess that you
  meant to enable transmit), and will flag it so you can make an explicit
  choice later.

Receive-only is a hard safety setting, not just a note. See "Understanding
results" below for what happens if a target radio can't actually enforce it.

## Applying a profile to a radio

1. Open (or download) the image for the radio you want to apply the
   profile to.
2. **Profile > Apply Profile to Current Image**.
3. CHIRP compares your profile against that radio's actual capabilities and
   what's already programmed, and shows a **preview** -- nothing is changed
   yet.
4. Review each proposed change. You can filter by result type, approve or
   reject individual items, and see exactly why something needs attention.
5. Click **Apply** to apply everything you've approved as a single step, or
   **Cancel** to close the preview without changing anything at all.
6. After applying, review the resulting image like you would after any
   other edit. **Applying a profile does not upload anything to your
   physical radio** -- you still use CHIRP's normal Upload to Radio when
   you're ready.

If you change your mind after applying, a single **Undo** (Edit > Undo, or
Ctrl+Z) reverses the entire apply in one step.

A profile with no channels can't be applied -- Apply tells you so
directly rather than showing an empty preview. The same is true if no
Profile is currently loaded, or the active tab has no memory grid to
apply to.

## Understanding the results

Every proposed channel gets one of five results:

| Result | What it means |
|---|---|
| **Exact** | The radio can represent this exactly as you specified it. |
| **Adapted** | A small, clearly-reported change was needed -- e.g. the name was abbreviated to fit, or your power preference was mapped to the nearest level this radio actually has. |
| **Degraded** | The channel is still usable, but something is lost -- e.g. this radio has no comment field, or no bank/group support, so that information stays in the profile but isn't written to the radio. |
| **Incompatible** | This radio genuinely can't represent the channel -- e.g. a digital mode it doesn't support, or a frequency outside its range. Nothing is added for this channel. |
| **Unsafe** | Blocked. The radio can't safely honor a receive-only restriction, or a change would let a channel transmit that you explicitly marked receive-only. **Unsafe items cannot be approved** -- there is no override button. |

Adapted and Degraded results always tell you exactly what changed or was
lost. Unsafe results always tell you why, so you can decide whether to skip
that channel or pick a different radio.

## Reviewing conflicts

Some situations need your attention before CHIRP can proceed automatically:

- **Two profile channels want the same memory slot.**
- **Not enough room** on the target radio for everything in the profile.
- **A memory slot is locked** by the radio driver and can't be reassigned.
- **Ambiguous match** -- an existing memory on the radio looks like it could
  be an earlier version of more than one profile channel; CHIRP won't guess
  which one, and asks you to resolve it.
- **Name collision** -- two profile channels would end up with the same
  displayed name on this radio.

Conflicts show up in the preview like any other item, with a clear
explanation, and are never silently resolved by overwriting something you
didn't ask to change.

## Saving, sharing, and importing/exporting profiles

Profiles are saved as plain, human-readable JSON files (extension
`.chirp-profile.json`) -- **Profile > Save Profile** / **Save Profile As**.
**Import Profile** / **Export Profile** currently work the same way (there's
only one profile file format today); they're separate menu entries so a
future release can add other interchange formats without changing this one.

Profiles are ordinary files: you choose exactly where to save one, the same
way you choose where to save any other document in CHIRP -- there is no
separate, managed "profiles folder". **Save Profile As** opens a normal save
dialog defaulting to the same directory CHIRP last used for a profile (or
the platform's usual default location the first time), and after a
successful save CHIRP shows you the full path the file was written to.

To reopen a saved profile later, use **Profile > Open Profile**, which opens
in that same last-used directory. A successful Open brings up the profile
editor on the loaded profile, with the filename shown in its title, so
there is no ambiguity about which file you loaded or whether Open did
anything at all. Opening does not touch any memory grid by itself --
applying the profile is always a separate, deliberate step (**Profile >
Apply Profile to Current Image...**), and you can inspect a profile this
way even with no memory grid open at all.

Because it's just a file, you can email it, put it in version control, or
share it with your club exactly like any other document. Opening someone
else's profile is safe: profile files cannot contain or execute code, and a
malformed or hand-edited file will fail to load with a clear error rather
than silently doing something unexpected.

See `docs/examples/north_idaho_camping.chirp-profile.json` for a worked
example (a fictionalized camping/travel profile -- verify any real
frequency against an authoritative source before using it).

## Relationship to the Programming Assistant

The Programming Assistant (Radio > Programming Assistant...) and Radio
Profiles are separate, complementary tools. The assistant creates and
populates a normal memory image; it never creates or saves a profile by
itself. If you want to turn assistant-programmed memories into a reusable
profile, do that explicitly with **Profile > Create Profile from Current
Image**, described above.

## A note on frequencies

CHIRP profiles carry whatever frequencies you enter. CHIRP does not
independently verify that a given frequency is legal to transmit on in your
location, licensed to you, or currently accurate for a real repeater or
service. Preserving your explicit receive-only intent is a hard safety
rule (see above); everything else about regulatory compliance and
frequency accuracy remains your responsibility, same as manually
programming a radio today.
