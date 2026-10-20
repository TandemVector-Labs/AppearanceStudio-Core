#!/usr/bin/env python3
from __future__ import annotations
import argparse, fcntl, json, os, shutil, subprocess
from pathlib import Path

def xdg(name, fallback):
    return Path(os.environ.get(name, Path.home()/fallback)).expanduser()

def remove_owned(path):
    if not path.exists() and not path.is_symlink():return
    if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
    else:path.unlink()

def main():
    ap=argparse.ArgumentParser(description="Uninstall Appearance Studio application files")
    ap.add_argument("--purge-user-data",action="store_true",help="Also remove Appearance Studio settings, state and user theme packs")
    ns=ap.parse_args()
    if os.geteuid()==0:
        raise SystemExit("Refusing root uninstall. Run as the desktop user.")
    data=xdg("XDG_DATA_HOME",".local/share")
    config=xdg("XDG_CONFIG_HOME",".config")
    state=xdg("XDG_STATE_HOME",".local/state")
    manifest_path=state/"appearance-studio/install-manifest.json"
    if not manifest_path.is_absolute() or any(parent.is_symlink() for parent in manifest_path.parents):
        raise SystemExit("Unsafe XDG state path: refusing uninstall.")
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size>32768:
        raise SystemExit("No owned installation manifest: refusing unrelated deletion.")
    recovery_root=state/"appearance-studio"
    lock=recovery_root/".core-install.lock"
    if lock.is_symlink():
        raise SystemExit("Linked install lock refused.")
    with lock.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(),fcntl.LOCK_EX)
        pending=recovery_root/"core-install-pending"
        preparing=recovery_root/".core-install-preparing"
        if (pending.exists() or pending.is_symlink()
                or preparing.exists() or preparing.is_symlink()):
            raise SystemExit("Unfinished Core install/recovery: refusing uninstall until resolved.")
        receipt=json.loads(manifest_path.read_text(encoding="utf-8"))
        app=data/"appearance-studio"
        expected={
            "python":app/"python", "builtin_pack":app/"packs/studio-default",
            "version":app/"VERSION", "licenses":app/"LICENSES",
            "wrapper":Path.home()/".local/bin/appearance-studio",
            "desktop":data/"applications/io.appearancestudio.Studio.desktop",
            "metainfo":data/"metainfo/io.appearancestudio.Studio.metainfo.xml",
            "service":config/"systemd/user/appearance-studio-theme-monitor.service",
            "system_monitor_service":config/"systemd/user/appearance-studio-system-monitor.service",
        }
        version=(Path(__file__).resolve().parent/"VERSION").read_text().strip()
        if (receipt.get("schema")!=1 or receipt.get("version")!=version
                or receipt.get("owned_paths")!={k:str(v) for k,v in expected.items()}
                or not expected["version"].is_file()
                or expected["version"].read_text().strip()!=version):
            raise SystemExit("Installed path/version mismatch: refusing unsafe uninstall.")
        owned_and_optional = list(expected.values())
        if ns.purge_user_data:
            owned_and_optional.extend([
                config/"appearance-studio", state/"appearance-studio",
                data/"appearance-studio/packs"
            ])
        if any(not p.is_absolute() or p.is_symlink()
               or any(parent.is_symlink() for parent in p.parents)
               for p in owned_and_optional):
            raise SystemExit("Owned target or parent is linked/unsafe: refusing uninstall.")
        activated=receipt.get("activate_requested") is True
        if activated:
            source=Path(__file__).resolve().parent/"share/systemd/user"
            installed=config/"systemd/user"
            for name in ("appearance-studio-theme-monitor.service",
                         "appearance-studio-system-monitor.service"):
                src=source/name
                dest=installed/name
                if not src.is_file() or not dest.is_file() or src.read_bytes()!=dest.read_bytes():
                    raise SystemExit("Activated unit changed: refusing to stop unrelated services.")
        if activated and not shutil.which("systemctl"):
            raise SystemExit("Cannot locate systemctl to stop activated owned services.")
        if activated:
            completed=subprocess.run(["systemctl","--user","disable","--now",
                "appearance-studio-theme-monitor.service",
                "appearance-studio-system-monitor.service"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if completed.returncode:
                raise SystemExit("Could not stop owned services; refusing partial uninstall.")
        paths=[
            Path.home()/".local/bin/appearance-studio",
            data/"applications/io.appearancestudio.Studio.desktop",
            data/"metainfo/io.appearancestudio.Studio.metainfo.xml",
            config/"systemd/user/appearance-studio-theme-monitor.service",
            config/"systemd/user/appearance-studio-system-monitor.service",
            data/"appearance-studio/python",
            data/"appearance-studio/packs/studio-default",
            data/"appearance-studio/VERSION",
            data/"appearance-studio/LICENSES",
        ]
        for path in paths:remove_owned(path)
        if ns.purge_user_data:
            remove_owned(config/"appearance-studio")
            remove_owned(state/"appearance-studio")
            remove_owned(data/"appearance-studio/packs")
        else:
            remove_owned(manifest_path)
        app=data/"appearance-studio"
        try:app.rmdir()
        except OSError:pass
        if activated and shutil.which("systemctl"):
            subprocess.run(["systemctl","--user","daemon-reload"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print("Appearance Studio application files removed.")
        if not ns.purge_user_data:print("User settings, state and additional theme packs were preserved.")
        return 0

if __name__=="__main__":
    raise SystemExit(main())
