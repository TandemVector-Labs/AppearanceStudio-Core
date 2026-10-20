# Appearance Studio Core — public release status (2026-10-19)

**Available now:** [Appearance Studio Core v0.9.0-rc1](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/tag/v0.9.0-rc1).

This is the Linux/GNOME public Core edition, not the full cinematic Ultimate edition. The ZIP release is public and contains the software's public Core sources, installer, and a bundled original default pack. It excludes private development state, user settings, and third-party franchise artwork.

## Install
Download the release ZIP, extract it, and follow its `README.md` and `install.py` instructions. It installs under the user account; optional services are not activated by default. Existing full/custom Appearance Studio installations should not be replaced with this smaller Core package.

## Verification scope
- Archive and release source are available in this public repository.
- Ubuntu 26.04/Core installer checks and a user-local installation on a second Linux host passed on 2026-10-19 without requiring sudo, enabling additional monitor services, or changing that host's current GNOME theme.
- Hardware-specific GNOME50 visual acceptance, full cinematic global Open/Close/Drag effects, the Windows backend and public distribution of third-party art remain outside this release's acceptance scope.

**No cryptographic signing certificate is asserted.** Download integrity may be verified using the published SHA-256 checksum; a checksum is not an identity signature.

The full private development repository stays separate. Project Ultimate remains under active development; this Core release is the usable early delivery.
