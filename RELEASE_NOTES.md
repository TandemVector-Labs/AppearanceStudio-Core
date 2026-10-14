# Appearance Studio Core — 0.9.0 Release Candidate 1

Platform: Linux GNOME/GTK4, with Ubuntu 26.04 / GNOME 50 targeted.
Published by Arclenor Technologies. Written by Dr. Emadoddin.

A public **Linux core release candidate**, not the completed Ultimate Cinematic
product. Includes the original, project-approved Studio Default SVG only.
No game/TV artwork, wallpapers, proprietary external packs, personal account
data, private project Brain, or Windows installer are included.

## Verification
- 27 explicitly packaged core files with SHA-256 manifest and ZIP CRC verification.
- Python source parsing, two functional unit tests, desktop-file and AppStream validation.
- systemd service-file validation.
- Isolated-home install -> uninstall with original settings and user theme packs preserved.
- Fault-injected tree replacement rollback restored previous bytes.
- No activation of background services on default install.

## Install
1. Unzip the archive.
2. Open a terminal in its extracted root.
3. Run `python3 install.py --dry-run` to inspect changes.
4. Run `python3 install.py` as the desktop user when ready.

Do not use sudo. Optional background services are not activated by default.
To remove the installed public core, from the same extracted folder run
`python3 uninstall.py`. User preferences and additional packs are retained.

## Important limitations
- The bundled pack uses GNOME-provided Yaru identities, not copied Yaru assets.
- The full 18-world, 36-mode animation/drag/click/Glass experience is **not** this release.
- Windows signed MSIX, real attended 30-minute GNOME stability and visual acceptance
  remain outstanding. This release must not be represented as product FINAL.
- Public license permits installation/use and backup only, not unauthorized
  redistribution or relicensing. Refer to LICENSE and NOTICE.
