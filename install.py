#!/usr/bin/env python3
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, shutil, subprocess, sys, tempfile, time
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
        if backup_root is not None:
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
    paths = {**targets, "install_manifest": manifest_path}
    for name, path in paths.items():
        if not path.is_absolute():
            raise RuntimeError("XDG install path must be absolute: " + name)
        if any(parent.is_symlink() for parent in path.parents):
            raise RuntimeError("linked parent directory refused: " + name)
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


def _same_content(source: Path, target: Path) -> bool:
    """Check owned content without changing timestamps or any desktop state."""
    if source.is_symlink() or target.is_symlink():
        return False
    if source.is_file():
        return target.is_file() and sha256(source) == sha256(target)
    if not source.is_dir() or not target.is_dir():
        return False
    a = {p.relative_to(source): p for p in source.rglob("*")}
    b = {p.relative_to(target): p for p in target.rglob("*")}
    if a.keys() != b.keys():
        return False
    return all(
        not p.is_symlink() and not b[rel].is_symlink()
        and (p.is_dir() and b[rel].is_dir()
             or p.is_file() and b[rel].is_file() and sha256(p) == sha256(b[rel]))
        for rel, p in a.items()
    )


def _copy_file_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + target.name + ".", dir=target.parent)
    os.close(fd)
    try:
        shutil.copy2(source, name, follow_symlinks=False)
        os.replace(name, target)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def _remove_target(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _path_digest(path: Path) -> str:
    """Digest snapshot bytes and symlink identities before attempting recovery."""
    if path.is_file() and not path.is_symlink():
        return sha256(path)
    if not path.is_dir() or path.is_symlink():
        raise RuntimeError("invalid transaction snapshot")
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path).as_posix().encode("utf-8")
        if p.is_symlink():
            h.update(b"L\x00" + rel + b"\x00" + os.readlink(p).encode("utf-8"))
        elif p.is_dir():
            h.update(b"D\x00" + rel + b"\x00")
        elif p.is_file():
            h.update(b"F\x00" + rel + b"\x00" + sha256(p).encode("ascii"))
        else:
            raise RuntimeError("unsupported snapshot item")
    return h.hexdigest()


def _transaction_paths(targets: dict, manifest_path: Path) -> dict:
    return {**targets, "install_manifest": manifest_path}


def begin_install_transaction(paths: dict, state: Path) -> Path:
    """Snapshot only the fixed Core-owned slots. Never archive personal pack dirs."""
    state.mkdir(parents=True, exist_ok=True)
    pending = state / "core-install-pending"
    preparing = state / ".core-install-preparing"
    if pending.exists() or pending.is_symlink():
        raise RuntimeError("unfinished installation: run install.py --recover")
    if preparing.is_symlink():
        raise RuntimeError("invalid incomplete preparation")
    if preparing.exists():
        if not (preparing / "PREPARATION_MARKER").is_file():
            raise RuntimeError("unrecognized transaction staging; refusing removal")
        shutil.rmtree(preparing)  # incomplete staging: no writes happen before promotion
    preparing.mkdir(mode=0o700)
    atomic_text(preparing / "PREPARATION_MARKER", "Appearance Studio Core staging\n", 0o600)
    try:
        preimages = preparing / "preimages"
        preimages.mkdir()
        previous = {}
        for name, path in paths.items():
            if path.is_symlink():
                raise RuntimeError("linked owned path: " + name)
            if not path.exists():
                previous[name] = {"kind": "absent"}
                continue
            snapshot = preimages / name
            if path.is_dir():
                shutil.copytree(path, snapshot, symlinks=True)
                kind = "dir"
            elif path.is_file():
                shutil.copy2(path, snapshot, follow_symlinks=False)
                kind = "file"
            else:
                raise RuntimeError("unsupported owned path: " + name)
            previous[name] = {"kind": kind, "digest": _path_digest(snapshot)}
        atomic_text(preparing / "journal.json",
                    json.dumps({"schema": 1, "old": previous,
                                "targets": {name: str(path) for name, path in paths.items()}},
                               sort_keys=True) + "\n",
                    0o600)
        os.replace(preparing, pending)
        return pending
    finally:
        if preparing.exists():
            shutil.rmtree(preparing)


def recover_install_transaction(paths: dict, state: Path) -> bool:
    pending = state / "core-install-pending"
    if pending.is_symlink():
        raise RuntimeError("linked recovery journal refused")
    if not pending.exists():
        return False
    if not pending.is_dir():
        raise RuntimeError("invalid recovery journal")
    if (pending / "commit.complete").is_file():
        shutil.rmtree(pending)  # previously committed; never undo a successful install
        return False
    journal_file = pending / "journal.json"
    if journal_file.is_symlink() or not journal_file.is_file():
        raise RuntimeError("invalid recovery journal")
    journal = json.loads(journal_file.read_text(encoding="utf-8"))
    if (not isinstance(journal, dict) or journal.get("schema") != 1
            or not isinstance(journal.get("old"), dict)
            or set(journal["old"]) != set(paths)
            or journal.get("targets") != {name: str(path) for name, path in paths.items()}):
        raise RuntimeError("mismatched recovery journal")
    # Verify the entire snapshot before mutating anything.
    for name, path in paths.items():
        entry = journal["old"][name]
        if not isinstance(entry, dict) or entry.get("kind") not in ("file", "dir", "absent"):
            raise RuntimeError("invalid preimage metadata: " + name)
        if path.is_symlink():
            raise RuntimeError("linked owned target blocks recovery: " + name)
        if entry["kind"] != "absent":
            saved = pending / "preimages" / name
            if (saved.is_symlink() or
                    (saved.is_dir() if entry["kind"] == "file" else not saved.is_dir()) or
                    _path_digest(saved) != entry.get("digest")):
                raise RuntimeError("corrupt recovery snapshot: " + name)
    # Replay-safe restoration: source snapshots remain until every target is restored.
    for name, path in reversed(list(paths.items())):
        entry = journal["old"][name]
        _remove_target(path)
        if entry["kind"] == "absent":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = pending / "preimages" / name
        if entry["kind"] == "dir":
            shutil.copytree(saved, path, symlinks=True)
        else:
            shutil.copy2(saved, path)
    shutil.rmtree(pending)
    return True


def finish_install_transaction(pending: Path) -> None:
    atomic_text(pending / "commit.complete", "committed\n", 0o600)
    shutil.rmtree(pending)

def main():
    ap=argparse.ArgumentParser(description="Install Appearance Studio for the current user")
    ap.add_argument("--activate",action="store_true",help="Enable the Light/Dark monitor after installation")
    ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--recover",action="store_true",help="Restore owned slots after an interrupted install")
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
    manifest_path = state/"appearance-studio/install-manifest.json"
    recovery_state = state/"appearance-studio"
    pending = recovery_state/"core-install-pending"
    if ns.dry_run:
        if pending.exists() or pending.is_symlink():
            raise SystemExit("Incomplete install: run install.py --recover")
        preflight_owned_paths(targets, manifest_path)
        print(json.dumps({k:str(v) for k,v in targets.items()},indent=2))
        return 0

    recovery_state.mkdir(parents=True, exist_ok=True)
    lock = recovery_state/".core-install.lock"
    with lock.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            slots = _transaction_paths(targets, manifest_path)
            if ns.recover:
                restored = recover_install_transaction(slots, recovery_state)
                print("Recovery:", "restored previous owned installation" if restored else "nothing pending")
                return 0
            if pending.exists() or pending.is_symlink():
                if (pending/"commit.complete").is_file() and not pending.is_symlink():
                    recover_install_transaction(slots, recovery_state)
                else:
                    raise SystemExit("Incomplete install: run install.py --recover")
            try:
                install_kind = preflight_owned_paths(targets, manifest_path)
            except RuntimeError as exc:
                raise SystemExit("Refusing unsafe installation: " + str(exc)) from exc
            previously_activated = (
                install_kind == "owned-update"
                and json.loads(manifest_path.read_text(encoding="utf-8")).get("activate_requested") is True
            )
            sources = [
                (SOURCE/"src/appearance_studio", targets["python"]/"appearance_studio", "tree"),
                (SOURCE/"share/appearance-studio/packs/studio-default", targets["builtin_pack"], "tree"),
                (SOURCE/"LICENSE", targets["licenses"]/"Appearance-Studio-LICENSE", "file"),
                (SOURCE/"NOTICE", targets["licenses"]/"Appearance-Studio-NOTICE", "file"),
                (SOURCE/"VERSION", targets["version"], "file"),
            ]
            if (SOURCE/"LICENSES").is_dir():
                sources.append((SOURCE/"LICENSES", targets["licenses"], "tree"))
            sources.extend([
                (SOURCE/"share/applications/io.appearancestudio.Studio.desktop", targets["desktop"], "file"),
                (SOURCE/"share/metainfo/io.appearancestudio.Studio.metainfo.xml", targets["metainfo"], "file"),
                (SOURCE/"share/systemd/user/appearance-studio-theme-monitor.service", targets["service"], "file"),
                (SOURCE/"share/systemd/user/appearance-studio-system-monitor.service", targets["system_monitor_service"], "file"),
            ])
            wrapper='''#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/appearance-studio"
export APPEARANCE_STUDIO_ROOT="$APP_ROOT"
export PYTHONPATH="$APP_ROOT/python${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m appearance_studio "$@"
'''
            desired = [(src, dst, kind) for src, dst, kind in sources if not _same_content(src, dst)]
            wrapper_changed = (not targets["wrapper"].is_file()
                               or targets["wrapper"].is_symlink()
                               or not (targets["wrapper"].stat().st_mode & 0o111)
                               or targets["wrapper"].read_text(encoding="utf-8") != wrapper)
            if not desired and not wrapper_changed and install_kind == "owned-update" and not ns.activate:
                print("Appearance Studio Core is already current; no files or receipt changed.")
                return 0
            journal = begin_install_transaction(slots, recovery_state)
            try:
                for src, dst, kind in desired:
                    if kind == "tree":
                        replace_tree(src, dst, None)
                    else:
                        _copy_file_atomic(src, dst)
                if wrapper_changed:
                    atomic_text(targets["wrapper"], wrapper, 0o755)
                receipt = {
                    "schema": 1, "version": (SOURCE/"VERSION").read_text().strip(),
                    "installed_at_unix": time.time(),
                    "owned_paths": {k: str(v) for k, v in targets.items()},
                    "preserve_on_uninstall": [
                        str(config/"appearance-studio"),
                        str(state/"appearance-studio"),
                        str(app/"packs")],
                    "activate_requested": bool(ns.activate or previously_activated),
                }
                atomic_text(manifest_path, json.dumps(receipt, indent=2)+"\n", 0o600)
            except Exception as exc:
                try:
                    recover_install_transaction(slots, recovery_state)
                except Exception as recovery_error:
                    raise RuntimeError(
                        "install failed; recovery remains pending for --recover: "
                        + str(recovery_error)) from exc
                raise RuntimeError("install failed; previous installation restored") from exc
            finish_install_transaction(journal)
            if shutil.which("update-desktop-database"):
                subprocess.run(["update-desktop-database", str(data/"applications")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ns.activate and shutil.which("systemctl"):
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                subprocess.run(["systemctl", "--user", "enable", "--now",
                                "appearance-studio-theme-monitor.service",
                                "appearance-studio-system-monitor.service"], check=False)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    print("Appearance Studio installed for the current user.")
    print("Monitor activation:",
          "requested" if ns.activate else
          "preserved from existing installation" if previously_activated else
          "deferred (safe default)")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
