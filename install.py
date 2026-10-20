#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent

def xdg(name, fallback):
    return Path(os.environ.get(name, Path.home()/fallback)).expanduser()

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()

def atomic_text(path, text, mode=0o755):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix="."+path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass

def backup(path, root):
    if not path.exists() and not path.is_symlink():return None
    root.mkdir(parents=True,exist_ok=True)
    dst=root/path.name
    n=1
    while dst.exists() or dst.is_symlink():
        dst=root/f"{path.name}.{n}";n+=1
    if path.is_dir() and not path.is_symlink():shutil.copytree(path,dst,symlinks=True)
    else:shutil.copy2(path,dst,follow_symlinks=False)
    return dst

def replace_tree(source, target, backup_root):
    """Stage fully before replacing; restore exact previous tree on promotion failure."""
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("Invalid install source tree")
    if target.is_symlink():
        raise RuntimeError("Refusing to overwrite a linked install target")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="."+target.name+".stage-",dir=target.parent))
    hold = Path(tempfile.mkdtemp(prefix="."+target.name+".hold-",dir=target.parent))
    previous = hold/target.name
    original_moved = False
    promoted = False
    try:
        for item in source.iterdir():
            dst = stage/item.name
            if item.is_symlink():
                raise RuntimeError("Linked source item rejected")
            if item.is_dir():
                shutil.copytree(item, dst, symlinks=False)
            else:
                shutil.copy2(item, dst, follow_symlinks=False)
        backup(target,backup_root)
        if target.exists():
            os.replace(target, previous)
            original_moved = True
        try:
            os.replace(stage,target)
            promoted = True
        except Exception:
            if original_moved:
                os.replace(previous,target)
                original_moved = False
            raise
    finally:
        if not promoted and original_moved and previous.exists() and not target.exists():
            os.replace(previous,target)
            original_moved = False
        if stage.exists():
            shutil.rmtree(stage)
        if promoted:
            shutil.rmtree(hold)
        elif not original_moved and hold.exists():
            hold.rmdir()

def preflight_owned_paths(targets, manifest_path):
    """Admit a fresh installation or an update owned by this Core installer."""
    linked = [name for name, path in targets.items() if path.is_symlink()]
    if linked:
        raise RuntimeError("linked install target refused: " + ", ".join(linked))
    if manifest_path.is_symlink():
        raise RuntimeError("linked install manifest refused")
    occupied = [name for name, path in targets.items() if path.exists()]
    if not manifest_path.exists():
        if occupied:
            raise RuntimeError("existing unowned install targets: " + ", ".join(occupied))
        return "fresh"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 32768:
        raise RuntimeError("invalid existing install manifest")
    try:
        receipt = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid existing install manifest") from exc
    expected = {name: str(path) for name, path in targets.items()}
    if (not isinstance(receipt, dict) or receipt.get("schema") != 1
            or receipt.get("owned_paths") != expected):
        raise RuntimeError("existing install is not owned by this Core installer")
    version_file = targets["version"]
    recorded_version = receipt.get("version")
    if (not isinstance(recorded_version, str) or not version_file.is_file()
            or version_file.read_text(encoding="utf-8").strip() != recorded_version):
        raise RuntimeError("existing Core version does not match its install receipt")
    return "owned-update"

def main():
    ap=argparse.ArgumentParser(description="Install Appearance Studio for the current user")
    ap.add_argument("--activate",action="store_true",help="Enable the Light/Dark monitor after installation")
    ap.add_argument("--dry-run",action="store_true")
    ns=ap.parse_args()
    if os.geteuid()==0:
        raise SystemExit("Refusing root install. Run as the desktop user.")

    data=xdg("XDG_DATA_HOME",".local/share")
    config=xdg("XDG_CONFIG_HOME",".config")
    state=xdg("XDG_STATE_HOME",".local/state")
    app=data/"appearance-studio"
    bindir=Path.home()/".local/bin"
    desktop=data/"applications/io.appearancestudio.Studio.desktop"
    metainfo=data/"metainfo/io.appearancestudio.Studio.metainfo.xml"
    unit=config/"systemd/user/appearance-studio-theme-monitor.service"
    system_unit=config/"systemd/user/appearance-studio-system-monitor.service"
    targets={
        "python":app/"python",
        "builtin_pack":app/"packs/studio-default",
        "version":app/"VERSION",
        "licenses":app/"LICENSES",
        "wrapper":bindir/"appearance-studio",
        "desktop":desktop,
        "metainfo":metainfo,
        "service":unit,
        "system_monitor_service":system_unit,
    }
    try:
        preflight_owned_paths(targets, state/"appearance-studio/install-manifest.json")
    except RuntimeError as exc:
        raise SystemExit("Refusing unsafe installation: " + str(exc)) from exc
    if ns.dry_run:
        print(json.dumps({k:str(v) for k,v in targets.items()},indent=2))
        return 0

    stamp=time.strftime("%Y%m%d-%H%M%S")
    backup_root=state/f"appearance-studio/install-backups/{stamp}"
    replace_tree(SOURCE/"src/appearance_studio",targets["python"]/"appearance_studio",backup_root/"python")
    replace_tree(SOURCE/"share/appearance-studio/packs/studio-default",targets["builtin_pack"],backup_root/"pack")
    if (SOURCE/"LICENSES").is_dir():
        replace_tree(SOURCE/"LICENSES",targets["licenses"],backup_root/"licenses")
    targets["licenses"].mkdir(parents=True,exist_ok=True)
    shutil.copy2(SOURCE/"LICENSE",targets["licenses"]/"Appearance-Studio-LICENSE")
    shutil.copy2(SOURCE/"NOTICE",targets["licenses"]/"Appearance-Studio-NOTICE")
    app.mkdir(parents=True,exist_ok=True)
    shutil.copy2(SOURCE/"VERSION",targets["version"])

    wrapper='''#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/appearance-studio"
export APPEARANCE_STUDIO_ROOT="$APP_ROOT"
export PYTHONPATH="$APP_ROOT/python${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m appearance_studio "$@"
'''
    atomic_text(targets["wrapper"],wrapper,0o755)
    for source,target in (
        (SOURCE/"share/applications/io.appearancestudio.Studio.desktop",desktop),
        (SOURCE/"share/metainfo/io.appearancestudio.Studio.metainfo.xml",metainfo),
        (SOURCE/"share/systemd/user/appearance-studio-theme-monitor.service",unit),
        (SOURCE/"share/systemd/user/appearance-studio-system-monitor.service",system_unit),
    ):
        target.parent.mkdir(parents=True,exist_ok=True)
        backup(target,backup_root/"integration")
        shutil.copy2(source,target)

    manifest={
        "schema":1,"version":(SOURCE/"VERSION").read_text().strip(),"installed_at_unix":time.time(),
        "owned_paths":{k:str(v) for k,v in targets.items()},
        "preserve_on_uninstall":[str(config/"appearance-studio"),str(state/"appearance-studio"),str(app/"packs")],
        "activate_requested":bool(ns.activate),
    }
    manifest_path=state/"appearance-studio/install-manifest.json"
    atomic_text(manifest_path,json.dumps(manifest,indent=2)+"\n",0o600)

    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database",str(data/"applications")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if ns.activate and shutil.which("systemctl"):
        subprocess.run(["systemctl","--user","daemon-reload"],check=False)
        subprocess.run(["systemctl","--user","enable","--now","appearance-studio-theme-monitor.service","appearance-studio-system-monitor.service"],check=False)

    print("Appearance Studio installed for the current user.")
    print("Monitor activation:", "requested" if ns.activate else "deferred (safe default)")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
