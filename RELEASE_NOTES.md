# Appearance Studio Core 0.9.1 — Release Candidate 1

**Publisher:** TandemVector-Labs (GitHub organization)  
**Original author:** Aliakbar Emadoddin (علی‌اکبر عمادالدین)  
**Distribution:** Linux/GNOME Core, source ZIP, **unsigned**  
**Release tag:** `v0.9.1-rc1-tandemvector`  
**Signing:** No cryptographic signing certificate has been applied. SHA-256 verifies download integrity, not publisher identity.

## Changes from 0.9.0 RC1

- Safe **in-place upgrades** of an installation actually owned by the Core installer. No second app installation or permanent duplicate backups; unchanged files do not cause receipt churn.
- Recoverable transactions with an on-disk journal and explicit `python3 install.py --recover` after interrupted installs; successful commits cannot be misread as interrupted rollbacks.
- Refuse foreign/linked installation targets, mismatched ownership receipts and symlinked parent paths.
- Inspect the actual user `systemd --user` manager before activating or disabling either Core-named service. Another customized Appearance Studio installation cannot be stopped or overwritten by mistake.
- Explicit `--activate` reasserts owned service activation; safe default does not start services.
- Safer removal with installation locking and no deletion of personal settings or additional Theme Packs by default.
- GTK/libadwaita UI includes Themes, Packs, Diagnostics and About. Distinguishes a successful rollback from partial or uncertain rollback instead of claiming success incorrectly.
- One public original Theme Pack: **Appearance Studio**, with separate Light/Dark options. No copyrighted franchise artwork or private Ultimate data.

## Verification

- 27 pinned public Core files with SHA-256 integrity and Python AST validation; reproducible unsigned source ZIP.
- Archive and real prior released Core ZIP to new owned-version upgrade, repeat no-op and uninstall under isolated XDG roots.
- Crash/fault-injected journal and rollback tests; foreign-user-manager collision and lock safety.
- GTK4 Broadway window navigation and Dark/Light button and Diagnostics action tests.
- Actual GNOME GSettings operations against a private keyfile backend, including rollback under injected failure.
- Both official Core units started, queried, upgraded and removed under a disposable clean Linux account using **real systemd --user** in CI.
- Noninteractive Ubuntu 26.04/GNOME 50.1 host smoke tests. These do **not** establish full owner-visible GNOME Shell cinematic acceptance.

## Installation and upgrade

Extract this archive into a separate source directory. Verify its adjacent `.sha256` file using `sha256sum -c`, then run as the ordinary desktop user:

```bash
python3 install.py --dry-run
python3 install.py
```

For an already Core-owned install, this upgrades in place. For interrupted operations:

```bash
python3 install.py --recover
```

Use `python3 install.py --activate` only if the Core service names are owned by this installation and background monitoring is desired. Do not remove, reset or overwrite another Appearance Studio, MMZ Theme or Ultimate installation to make Core fit.

## Release limitations

This is a Linux Core prerelease, **not** Appearance Studio Ultimate, Windows, a signed distribution, or v1.0 FINAL. Attended GNOME 50 compositor/Wayland animation and 30-minute visual soak, Windows signing, and public rights to third-party artwork remain outside acceptance.

The historical `v0.9.0-rc1-tandemvector` GitHub Release and its verified unsigned ZIP remain **unchanged**. Its checksum is not interchangeable with this version. Licensing and redistribution conditions remain in `LICENSE` and `NOTICE`.
