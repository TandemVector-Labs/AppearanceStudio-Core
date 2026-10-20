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

## Updated organization-branded source package (2026-10-20)

The public main branch now offers [AppearanceStudio-Core-v0.9.0-rc1-TandemVector-unsigned.zip](downloads/AppearanceStudio-Core-v0.9.0-rc1-TandemVector-unsigned.zip) built from commit 873c08232aba0ef8e780bc961a652b0ddf3a991c with publisher **TandemVector-Labs**, original author **Aliakbar Emadoddin**, one public original Theme Pack named **Appearance Studio**, and no digital signing requirement.

SHA-256: c8825929c995b590fa75241764c8556e10075879b91a49a0b8915207ee1a4869. The historical release tag and its original ZIP were not replaced; this package has its own checksum. Its install/uninstall, public manifest, transaction and monitor tests passed in an isolated user-local XDG environment. The broader Ultimate, Windows and GNOME cinematic acceptance remain open; no third-party wallpapers are redistributed.
