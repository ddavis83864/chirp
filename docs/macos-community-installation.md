# Installing CHIRP for macOS (Community Edition)

The CHIRP macOS Community Edition is **not signed with an Apple Developer
ID and has not been notarized by Apple**. It is built automatically, from
source, on GitHub-hosted macOS runners, from the exact CHIRP source commit
identified on the release page. Unsigned status means Apple has not
verified the developer identity behind this build -- it does not mean the
package failed validation. Every architecture in a Community Edition
release has passed full structural, resource, and architecture validation
before being published; see the attached provenance manifest on the
release page for details.

## 1. Identify the correct download

CHIRP for macOS is built separately for each processor family. You must
download the one matching your Mac.

**Check which one you have:** Apple menu (top-left corner) -> **About This
Mac**.

- If you see a line labeled **Chip** (e.g. "Apple M1", "Apple M2", "Apple
  M3", "Apple M4"), download the **arm64** build:
  `CHIRP-1.12.0-macOS-arm64-unsigned.dmg`
- If you see a line labeled **Processor** (e.g. "Intel Core i5", "Intel
  Core i7"), download the **x86_64** build:
  `CHIRP-1.12.0-macOS-x86_64-unsigned.dmg`

Installing the wrong architecture's DMG will simply fail to open the app
(or Finder will refuse it) -- it is not harmful, just won't work.

## 2. Install from the DMG

1. Download the DMG matching your Mac's chip from the official GitHub
   release page.
2. (Recommended) Verify the checksum -- see section 4 below.
3. Double-click the downloaded `.dmg` file to open it.
4. Drag `CHIRP.app` onto the `Applications` shortcut in the same window.
5. Eject the mounted disk image (right-click its icon on the Desktop or in
   Finder's sidebar -> Eject).

## 3. First launch

Because this build is unsigned, macOS will block it the first time you try
to open it. This is expected, standard macOS behavior for any application
without an Apple Developer ID signature -- it is not specific to CHIRP and
not a sign that something is wrong. You need to explicitly authorize it
once; macOS will remember your choice for future launches.

### Path 1: Control-click (or right-click) to open

This is the simplest method for most macOS versions:

1. Open **Finder** -> **Applications**.
2. Control-click (or right-click) **CHIRP**.
3. Select **Open** from the menu.
4. macOS will show a warning dialog. Read it, then click **Open** again.
5. CHIRP should now launch, and future double-clicks will work normally.

### Path 2: Privacy & Security settings

On some macOS versions, or if Path 1's **Open** option doesn't appear, use
this instead:

1. Try to open CHIRP once (double-click it in Applications). macOS will
   block it with a dialog saying it can't verify the developer.
2. Open **System Settings**.
3. Select **Privacy & Security** in the sidebar.
4. Scroll down -- you should see a message noting that "CHIRP" was blocked.
5. Click **Open Anyway**.
6. You may be asked to authenticate with your password or Touch ID.
7. Try opening CHIRP again; it should now launch.

**Do not** disable Gatekeeper system-wide (`sudo spctl --master-disable`)
or disable System Integrity Protection to install CHIRP. Neither is
necessary, and both remove security protection for your entire Mac, not
just this one app.

## 4. Verify your download (recommended)

The release page includes a `CHIRP-1.12.0-macOS-Community-SHA256SUMS.txt`
file with SHA-256 checksums for every artifact. To verify the DMG you
downloaded:

```bash
shasum -a 256 CHIRP-1.12.0-macOS-arm64-unsigned.dmg
```

(substitute `x86_64` for the Intel build). Compare the printed hash against
the matching line in `CHIRP-1.12.0-macOS-Community-SHA256SUMS.txt`. They
must match exactly.

A matching checksum confirms the file you downloaded is byte-for-byte
identical to what this project's build produced -- it confirms **file
integrity**, not that the software is inherently safe. It's the same
guarantee a checksum gives for any download; it doesn't replace judgment
about whether to trust the source. Only download CHIRP from the official
GitHub releases page for this repository -- never from a third-party
mirror.

## 5. Advanced: manual quarantine removal

If you've already verified the download's checksum and prefer not to use
the GUI prompts above, you can remove the quarantine attribute directly
from Terminal:

```bash
xattr -d com.apple.quarantine /Applications/CHIRP.app
```

This removes the quarantine flag **only** from this specific app -- it does
not disable Gatekeeper, does not affect any other application, and should
only be used after you've verified the download's source and checksum.
Do not run a recursive quarantine removal (`xattr -dr` over broad
directories) and do not use this as a substitute for verifying what you
downloaded. This is an advanced alternative to Path 1/2 above, not the
primary recommended installation method.

## Getting help

If CHIRP doesn't launch after following the steps above, please report the
issue with:

- your Mac's chip/processor (from step 1);
- your macOS version (Apple menu -> About This Mac);
- which download you used (arm64 or x86_64);
- the exact error message or behavior you saw.
