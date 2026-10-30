# Appearance Studio

<p align="center">
  <img src="https://raw.githubusercontent.com/TandemVector-Labs/.github/main/brand/social/AppearanceStudio-Core.png" alt="Appearance Studio Core visual project card" width="720">
</p>

Appearance Studio is a professional desktop appearance center for GNOME on Linux. It is designed around a portable core, verified Theme Packs, bounded desktop writes, transactional rollback, and independent monitoring services.

**Original author: Aliakbar Emadoddin · نویسندهٔ اصلی: علی‌اکبر عمادالدین**

Published under **TandemVector-Labs** on GitHub for Linux and future Windows products. The current Appearance Studio implementation targets Linux/GNOME; Windows support is planned and is not claimed as shipped yet.

## Release status

Version **0.9.1** is a release candidate. The portable core, Theme Pack validation, transaction rollback, installer/uninstaller, and read-only monitoring model are testable independently of a live desktop session. A stable GNOME 50 live canary and soak remain required before declaring version 1.0 final.

## Platform strategy

Appearance Studio uses a shared Theme Pack and validation contract with platform-specific desktop backends. The current release candidate targets Linux/GNOME. Windows is an explicitly tracked platform target, but no Windows build is claimed as shipped yet. Machine-readable support status is bundled at `share/appearance-studio/platform-support.json`.

## Core capabilities

- Theme Pack discovery with path confinement and SHA-256 asset verification.
- Transactional application of Light/Dark GTK identity, icons, cursor, sound, and wallpaper.
- Write-if-changed desktop settings to minimize configuration churn.
- Exact rollback when an appearance transaction fails.
- Light/Dark synchronization with event coalescing and rate limiting.
- Professional GTK/libadwaita interface with Themes, Packs, Diagnostics, and About pages.
- Independent StatusNotifier system monitor for CPU, RAM, temperature, battery, network, and disk I/O.
- Numeric Network/Disk throughput plus compact spark bars.
- Privacy-bounded diagnostic export: no username, host, IP, MAC, serial, process list, interface name, disk device name, or private file paths.
- Per-user installation without sudo.
- Uninstall preserves user settings, state, and additional Theme Packs by default.

## Requirements

Recommended target:

- Ubuntu 26.04 or another current GNOME desktop with GTK 4 and libadwaita.
- Python 3.12 or newer.
- `python3-gi` and GTK/libadwaita introspection packages for the graphical interface.
- `python3-dbus` for the optional panel system monitor.
- `gsettings` from GLib.
- Yaru assets for the bundled Studio Default release-candidate pack on Ubuntu.

The command-line core remains useful when the optional graphical or panel dependencies are not installed.

## Appearance Studio Core 0.9.1 RC1 (unsigned)

**0.9.1 RC1 is published as an unsigned Linux Core prerelease**, not Stable:
[official release and verification notes](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/tag/v0.9.1-rc1-tandemvector) ·
[versioned Linux Core ZIP](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/download/v0.9.1-rc1-tandemvector/AppearanceStudio-Core-v0.9.1-rc1-TandemVector-unsigned.zip) ·
[SHA-256 checksum](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/download/v0.9.1-rc1-tandemvector/AppearanceStudio-Core-v0.9.1-rc1-TandemVector-unsigned.zip.sha256).
Verify the asset against its published checksum before installation. The earlier **0.9.0 RC1** remains available below for historical reference; neither prerelease establishes GNOME 50 live acceptance or a shipped Windows product.

The 0.9.1 update includes ownership-checked **in-place upgrade**, journal
recovery via `python3 install.py --recover`, actual user-manager service-name
collision protection, and safer GTK error reporting. It retains the single
original **Appearance Studio** Theme Pack; Windows and Ultimate are separate.

## Previous official unsigned organization-branded RC1


**Official GitHub Release:** [Appearance Studio Core 0.9.0 RC1 — TandemVector-Labs](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/tag/v0.9.0-rc1-tandemvector). Download its [unsigned Linux Core ZIP](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/download/v0.9.0-rc1-tandemvector/AppearanceStudio-Core-v0.9.0-rc1-TandemVector-unsigned.zip) and [SHA-256 checksum](https://github.com/TandemVector-Labs/AppearanceStudio-Core/releases/download/v0.9.0-rc1-tandemvector/AppearanceStudio-Core-v0.9.0-rc1-TandemVector-unsigned.zip.sha256). The same verified ZIP is also kept in [repository downloads](downloads/AppearanceStudio-Core-v0.9.0-rc1-TandemVector-unsigned.zip).

The ZIP contains the **Linux Core 0.9.0 release candidate** from public source commit [873c08232aba](https://github.com/TandemVector-Labs/AppearanceStudio-Core/commit/873c08232aba0ef8e780bc961a652b0ddf3a991c); the release's verification workflow passed on 20 October 2026. It is **not** the unfinished Ultimate edition or a stable v1.0 release.

**Publisher:** TandemVector-Labs (GitHub organization). **Original author:** Aliakbar Emadoddin (علی‌اکبر عمادالدین). **Code signing:** not applied; the checksum is an integrity check, not an author signature.

**SHA-256:** c8825929c995b590fa75241764c8556e10075879b91a49a0b8915207ee1a4869 — the matching [checksum file](downloads/AppearanceStudio-Core-v0.9.0-rc1-TandemVector-unsigned.zip.sha256) is supplied.

The historical v0.9.0-rc1 tagged GitHub Release remains unchanged; its ZIP differs from this subsequent organization-branded source package. Do not overwrite an existing customized or Ultimate installation without first reviewing and preserving its data.

## Install

Run as the desktop user, not root:

```bash
python3 install.py
```

The safe default installs the application and services but does **not** start background services in the current graphical session.

To install and explicitly activate the Light/Dark and system-monitor services:

```bash
python3 install.py --activate
```

For a non-mutating installation preview:

```bash
python3 install.py --dry-run
```

## Safe in-place Core upgrades and interruption recovery

For an existing installation **owned by this Core installer**, extract the
updated Core ZIP into a separate temporary source directory and run
`python3 install.py` from that new source directory. It updates the *same*
user-owned destinations and does not create a second application installation.
Unchanged files and the ownership receipt are left untouched on a no-op update.
User settings, state and additional personal Theme Packs remain outside
the owned-file replacement. Do **not** use this installer to replace another
customized Appearance Studio, MMZ Theme or Ultimate installation.

If an update stops after a partial change, run the following from the
**same version of Core source** that attempted the update, before trying again:

```bash
python3 install.py --recover
```

Recovery uses a bounded journal to restore the previously owned files. If the
journal reports a collision, unexpected symlink, wrong location, or unresolved
service cleanup, do not manually delete its files or reinstall over them:
resolve the specific error without disturbing the existing desktop. A
successfully committed update is not rolled back by later journal cleanup.

`--activate` is optional and checks which unit files the **actual user
systemd manager** loaded. If another installation owns either official Core
service name, activation refuses the collision instead of enabling or
disabling that other service. An update without `--activate` does not
activate background services for the first time.

## Use

Launch the graphical center:

```bash
appearance-studio
```

Useful command-line operations:

```bash
appearance-studio status
appearance-studio diagnostics
appearance-studio plan studio-default --mode dark
appearance-studio apply studio-default --mode dark
appearance-studio system-monitor-diagnostic
```

## Uninstall

```bash
python3 uninstall.py
```

This removes application-owned files and the bundled Studio Default pack while preserving user settings, state, and additional Theme Packs.

To also remove user data:

```bash
python3 uninstall.py --purge-user-data
```

## Theme Pack format

Theme Packs use manifest schema 2. Each pack declares:

- stable pack and theme identifiers,
- human-readable names and version,
- a license identifier,
- explicit public-distribution approval,
- GTK, icon, cursor, and sound theme identities,
- a relative wallpaper path and SHA-256,
- theme color tokens.

Pack paths are confined to the pack directory. Absolute paths and parent-directory traversal are rejected. Duplicate pack and theme identifiers are rejected.

The bundled `studio-default` pack is original project artwork and contains no third-party wallpaper asset.

## Safety model

Appearance Studio intentionally avoids large bursts of desktop configuration writes. The public core:

1. reads current values first,
2. skips unchanged settings,
3. serializes appearance changes with a user-level lock,
4. applies a bounded set of owned settings,
5. verifies the resulting state,
6. restores the pre-state if verification fails.

The Light/Dark monitor coalesces change bursts instead of running one full transaction per event. The system monitor samples `/proc` and `/sys` independently rather than running telemetry inside GNOME Shell.

## Privacy

Appearance Studio is local-first. The public core does not require an online account and does not include developer-machine paths, private project metadata, user names, host names, or machine-specific identifiers.

## Licensing

See `LICENSE` for Appearance Studio and the bundled original pack. If a future distribution includes third-party code or assets, their required notices are stored in `LICENSES/` and remain governed by their own licenses.
