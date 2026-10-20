from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("core_install_preflight", ROOT / "install.py")
assert spec is not None and spec.loader is not None
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def must_refuse(targets, manifest):
    try:
        installer.preflight_owned_paths(targets, manifest)
    except RuntimeError:
        return
    raise AssertionError("unsafe installation unexpectedly admitted")


def run():
    with tempfile.TemporaryDirectory(prefix="core-preflight-") as td:
        root = Path(td)
        targets = {
            "python": root / "data" / "python",
            "version": root / "data" / "VERSION",
            "wrapper": root / "bin" / "appearance-studio",
        }
        receipt = root / "state" / "install-manifest.json"

        # A fresh XDG sandbox must still permit a normal first installation.
        assert installer.preflight_owned_paths(targets, receipt) == "fresh"

        targets["wrapper"].parent.mkdir(parents=True)
        targets["wrapper"].write_text("someone else's install", encoding="utf-8")
        must_refuse(targets, receipt)  # no install receipt: user data is not owned
        targets["wrapper"].unlink()

        targets["wrapper"].symlink_to(targets["wrapper"].parent)
        must_refuse(targets, receipt)
        targets["wrapper"].unlink()

        linked_parent = root / "linked-parent"
        linked_parent.symlink_to(root / "data", target_is_directory=True)
        must_refuse({"wrapper": linked_parent / "appearance-studio"}, receipt)
        linked_parent.unlink()

        receipt.parent.mkdir(parents=True)
        receipt.symlink_to(targets["wrapper"].parent)
        must_refuse(targets, receipt)
        receipt.unlink()

        receipt.write_text("not JSON", encoding="utf-8")
        must_refuse(targets, receipt)
        receipt.unlink()

        targets["version"].parent.mkdir(parents=True)
        targets["version"].write_text("0.9.0\n", encoding="utf-8")
        owned = {
            "schema": 1,
            "version": "0.9.0",
            "owned_paths": {name: str(path) for name, path in targets.items()},
        }
        receipt.write_text(json.dumps({**owned, "owned_paths": {"other": "path"}}), encoding="utf-8")
        must_refuse(targets, receipt)

        receipt.write_text(json.dumps({**owned, "version": "9.9.9"}), encoding="utf-8")
        must_refuse(targets, receipt)

        receipt.write_text(json.dumps(owned), encoding="utf-8")
        assert installer.preflight_owned_paths(targets, receipt) == "owned-update"

        targets["version"].write_text("externally modified\n", encoding="utf-8")
        must_refuse(targets, receipt)

    # Exercise the real install.py entry point without a live desktop or user data.
    if os.geteuid() != 0:
        with tempfile.TemporaryDirectory(prefix="core-installer-e2e-") as td:
            root = Path(td)
            home = root / "home"
            home.mkdir()
            env = dict(os.environ)
            env.update({
                "HOME": str(home),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_STATE_HOME": str(root / "state"),
            })
            command = [sys.executable, str(ROOT / "install.py")]
            def call(*extra):
                return subprocess.run(command + list(extra), cwd=ROOT,
                                      env=env, capture_output=True, text=True, timeout=30)

            assert call("--dry-run").returncode == 0
            conflict = root / "data" / "appearance-studio" / "python"
            conflict.mkdir(parents=True)
            marker = conflict / "private-original.txt"
            marker.write_text("preserve-me", encoding="utf-8")
            rejected = call("--dry-run")
            assert rejected.returncode != 0, rejected.stdout + rejected.stderr
            assert marker.read_text(encoding="utf-8") == "preserve-me"
            assert not (root / "state" / "appearance-studio" / "install-manifest.json").exists()
            marker.unlink()
            conflict.rmdir()

            installed = call()
            assert installed.returncode == 0, installed.stdout + installed.stderr
            receipt = root / "state" / "appearance-studio" / "install-manifest.json"
            assert receipt.is_file()
            assert call("--dry-run").returncode == 0
            assert "appearance-studio" in json.loads(receipt.read_text())["owned_paths"]["python"]
            assert not (root / "config" / "appearance-studio").exists()

            # A Core upgrade preserves a user's settings, extra packs and activation
            # history without running a real systemd user service.
            prefs = root / "config" / "appearance-studio" / "settings.json"
            prefs.parent.mkdir(parents=True)
            prefs.write_text('{"selected_theme":"personal"}', encoding="utf-8")
            extra = root / "data" / "appearance-studio" / "packs" / "personal" / "sample.txt"
            extra.parent.mkdir(parents=True)
            extra.write_text("keep-this-pack", encoding="utf-8")
            private_state = root / "state" / "appearance-studio" / "owner-state.txt"
            private_state.write_text("keep-state", encoding="utf-8")

            fakebin = root / "fakebin"
            fakebin.mkdir()
            sysctl = fakebin / "systemctl"
            sysctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CORE_TEST_SYSTEMCTL_LOG"\n',
                              encoding="utf-8")
            sysctl.chmod(0o755)
            service_log = root / "systemctl.log"
            env["CORE_TEST_SYSTEMCTL_LOG"] = str(service_log)
            env["PATH"] = str(fakebin) + os.pathsep + os.environ.get("PATH", "")
            activated = call("--activate")
            assert activated.returncode == 0, activated.stdout + activated.stderr
            assert json.loads(receipt.read_text())["activate_requested"] is True
            events = service_log.read_text(encoding="utf-8")
            assert "enable --now appearance-studio-theme-monitor.service" in events

            # A normal later update must not falsely de-authorize already running services.
            updated = call()
            assert updated.returncode == 0, updated.stdout + updated.stderr
            assert "already current" in updated.stdout or "preserved from existing installation" in updated.stdout
            assert json.loads(receipt.read_text())["activate_requested"] is True
            assert service_log.read_text(encoding="utf-8") == events
            assert prefs.read_text(encoding="utf-8") == '{"selected_theme":"personal"}'
            assert extra.read_text(encoding="utf-8") == "keep-this-pack"
            assert private_state.read_text(encoding="utf-8") == "keep-state"
            assert (root / "data" / "appearance-studio" / "python" /
                    "appearance_studio" / "__init__.py").is_file()

            # A byte-identical upgrade must not rewrite the receipt or produce
            # the growing install-backups folders used by the previous installer.
            manifest_bytes = receipt.read_bytes()
            backup_root = root / "state" / "appearance-studio" / "install-backups"
            backup_dirs_before = sorted(backup_root.iterdir()) if backup_root.exists() else []
            must_pass = call()
            assert must_pass.returncode == 0, must_pass.stdout + must_pass.stderr
            assert "already current" in must_pass.stdout
            assert receipt.read_bytes() == manifest_bytes
            assert (sorted(backup_root.iterdir()) if backup_root.exists() else []) == backup_dirs_before
            assert not (root / "state" / "appearance-studio" / "core-install-pending").exists()

            # Fault-inject after a tree promotion, then require exact old bytes.
            original_engine = root / "data" / "appearance-studio" / "python" / "appearance_studio" / "engine.py"
            original_engine.write_bytes(original_engine.read_bytes() + b"\n# personal-core-adjustment\n")
            prior_engine = original_engine.read_bytes()
            prior_receipt = receipt.read_bytes()
            original_replace = installer.replace_tree

            def fail_after_promotion(source, target, backup_root):
                original_replace(source, target, backup_root)
                raise OSError("injected transaction failure after tree promotion")

            installer.replace_tree = fail_after_promotion
            try:
                # main() runs in this process to monkeypatch a staging operation.
                previous_argv = sys.argv
                previous_env = dict(os.environ)
                try:
                    sys.argv = [str(ROOT / "install.py")]
                    os.environ.update(env)
                    try:
                        installer.main()
                        raise AssertionError("fault injection unexpectedly completed")
                    except RuntimeError as exc:
                        assert "previous installation restored" in str(exc)
                finally:
                    sys.argv = previous_argv
                    os.environ.clear()
                    os.environ.update(previous_env)
            finally:
                installer.replace_tree = original_replace
            assert original_engine.read_bytes() == prior_engine
            assert receipt.read_bytes() == prior_receipt
            assert not (root / "state" / "appearance-studio" / "core-install-pending").exists()
            assert prefs.read_text(encoding="utf-8") == '{"selected_theme":"personal"}'
            assert extra.read_text(encoding="utf-8") == "keep-this-pack"

            # Simulate an interrupted transaction and recover from the pinned
            # preimage without touching settings or extra theme packs.
            slots = json.loads(receipt.read_text(encoding="utf-8"))["owned_paths"]
            owned_slots = {key: Path(value) for key, value in slots.items()}
            owned_slots["install_manifest"] = receipt
            state_root = root / "state" / "appearance-studio"
            installer.begin_install_transaction(owned_slots, state_root)
            original_engine.write_bytes(b"incomplete upgrade")
            foreign_target = root / "outside-transaction.txt"
            foreign_target.write_text("do-not-touch", encoding="utf-8")
            wrong_slots = dict(owned_slots)
            wrong_slots["version"] = foreign_target
            try:
                installer.recover_install_transaction(wrong_slots, state_root)
                raise AssertionError("mismatched recovery path unexpectedly accepted")
            except RuntimeError as exc:
                assert "mismatched recovery journal" in str(exc)
            assert foreign_target.read_text(encoding="utf-8") == "do-not-touch"
            app_path = root / "data" / "appearance-studio"
            parked = root / "data" / "appearance-studio-parked"
            app_path.rename(parked)
            app_path.symlink_to(parked, target_is_directory=True)
            try:
                try:
                    installer.recover_install_transaction(owned_slots, state_root)
                    raise AssertionError("recovery through symlinked ancestor unexpectedly accepted")
                except RuntimeError as exc:
                    assert "linked owned target or parent" in str(exc)
            finally:
                app_path.unlink()
                parked.rename(app_path)
            recovery_run = call("--recover")
            assert recovery_run.returncode == 0, recovery_run.stdout + recovery_run.stderr
            assert "restored previous owned installation" in recovery_run.stdout
            assert original_engine.read_bytes() == prior_engine
            assert receipt.read_bytes() == prior_receipt
            assert installer.recover_install_transaction(owned_slots, state_root) is False
            assert not (state_root / "core-install-pending").exists()
        print("CORE_RECOVERABLE_TRANSACTION_PASS")
        print("INSTALL_ISOLATED_XDG_END_TO_END_PASS")
    else:
        print("INSTALL_ISOLATED_XDG_END_TO_END_SKIPPED_ROOT")

    # Integration: failed service enable must not commit an installation receipt.
    # systemctl is an isolated fake; no real daemon/service is contacted.
    with tempfile.TemporaryDirectory(prefix="core-service-reject-") as td:
        root = Path(td)
        home = root / "home"
        home.mkdir()
        fakebin = root / "fakebin"
        fakebin.mkdir()
        systemctl = fakebin / "systemctl"
        systemctl.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$CORE_TEST_SYSTEMCTL_LOG"\n'
            'if [ "$2" = enable ]; then exit 37; fi\n'
            'if [ "$2" = disable ] && [ "$CORE_TEST_FAIL_DISABLE" = 1 ]; then exit 39; fi\n',
            encoding="utf-8")
        systemctl.chmod(0o755)
        log = root / "service.log"
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "PATH": str(fakebin) + os.pathsep + env.get("PATH", ""),
            "CORE_TEST_SYSTEMCTL_LOG": str(log),
        })
        installed = subprocess.run([sys.executable, str(ROOT / "install.py")],
                                   env=env, capture_output=True, text=True, timeout=30)
        assert installed.returncode == 0, installed.stdout + installed.stderr
        receipt = root / "state" / "appearance-studio" / "install-manifest.json"
        saved = receipt.read_bytes()
        rejected = subprocess.run([sys.executable, str(ROOT / "install.py"), "--activate"],
                                  env=env, capture_output=True, text=True, timeout=30)
        assert rejected.returncode != 0, rejected.stdout + rejected.stderr
        assert "previous installation restored" in rejected.stderr
        assert receipt.read_bytes() == saved
        assert json.loads(receipt.read_text())["activate_requested"] is False
        assert not (root / "state" / "appearance-studio" / "core-install-pending").exists()
        assert (root / "data" / "appearance-studio" / "python" /
                "appearance_studio" / "engine.py").is_file()
        events = log.read_text(encoding="utf-8")
        assert "enable --now" in events
        assert "disable --now" in events
        assert (root / "data" / "appearance-studio" / "packs" / "studio-default").is_dir()
        # Abrupt termination after recording service intent must cause the
        # next explicit CLI recovery to perform owned-service cleanup.
        code = (
            "import importlib.util, os, sys\n"
            f"spec=importlib.util.spec_from_file_location('installer', {str(ROOT / 'install.py')!r})\n"
            "module=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "def crash(*args):\n"
            "    os._exit(46)\n"
            "module._systemctl=crash\n"
            "sys.argv=['install.py', '--activate']\n"
            "module.main()\n"
        )
        killed = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, timeout=30)
        assert killed.returncode == 46, killed.stdout + killed.stderr
        pending = root / "state" / "appearance-studio" / "core-install-pending"
        assert (pending / "service-intent.json").is_file()
        log_before = log.read_text(encoding="utf-8")
        incomplete_receipt = receipt.read_bytes()
        env["CORE_TEST_FAIL_DISABLE"] = "1"
        blocked = subprocess.run([sys.executable, str(ROOT / "install.py"), "--recover"],
                                 env=env, capture_output=True, text=True, timeout=30)
        assert blocked.returncode != 0
        assert pending.exists() and (pending / "service-intent.json").is_file()
        # Cleanup failed before restoring preimages: preserve the pending snapshot
        # and the exact interrupted state until recovery can succeed.
        assert receipt.read_bytes() == incomplete_receipt
        env.pop("CORE_TEST_FAIL_DISABLE")
        recovered = subprocess.run([sys.executable, str(ROOT / "install.py"), "--recover"],
                                   env=env, capture_output=True, text=True, timeout=30)
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert "restored previous owned installation" in recovered.stdout
        assert receipt.read_bytes() == saved
        assert "disable --now" in log.read_text(encoding="utf-8")[len(log_before):]
        assert not pending.exists()
        print("CORE_SERVICE_INTENT_CRASH_RECOVERY_PASS")
        print("CORE_FAILED_SERVICE_ACTIVATION_ROLLBACK_PASS")

    # Simulate SIGKILL-like exit after a tree promotion, then invoke the CLI recovery.
    with tempfile.TemporaryDirectory(prefix="core-crash-recovery-") as td:
        root = Path(td)
        home = root / "home"
        home.mkdir()
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
        })
        command = [sys.executable, str(ROOT / "install.py")]
        first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        assert first.returncode == 0, first.stdout + first.stderr
        original_engine = root / "data" / "appearance-studio" / "python" / "appearance_studio" / "engine.py"
        original_engine.write_bytes(original_engine.read_bytes() + b"\n# force-upgrade\n")
        expected = original_engine.read_bytes()
        receipt = root / "state" / "appearance-studio" / "install-manifest.json"
        expected_receipt = receipt.read_bytes()
        code = (
            "import importlib.util, os, sys\n"
            f"spec=importlib.util.spec_from_file_location('installer', {str(ROOT / 'install.py')!r})\n"
            "module=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "real=module.replace_tree\n"
            "def crash(*args):\n"
            "    real(*args)\n"
            "    os._exit(43)\n"
            "module.replace_tree=crash\n"
            "sys.argv=['install.py']\n"
            "module.main()\n"
        )
        crashed = subprocess.run([sys.executable, "-c", code], env=env,
                                 capture_output=True, text=True, timeout=30)
        assert crashed.returncode == 43, crashed.stdout + crashed.stderr
        pending = root / "state" / "appearance-studio" / "core-install-pending"
        assert pending.is_dir()
        assert original_engine.read_bytes() != expected
        blocked = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        assert blocked.returncode != 0 and "Incomplete install" in blocked.stderr
        recover = subprocess.run(command + ["--recover"], env=env,
                                 capture_output=True, text=True, timeout=30)
        assert recover.returncode == 0, recover.stdout + recover.stderr
        assert original_engine.read_bytes() == expected
        assert receipt.read_bytes() == expected_receipt
        assert not pending.exists()
        print("CORE_CRASH_INTERRUPTION_CLI_RECOVERY_PASS")

    print("INSTALL_OWNERSHIP_PREFLIGHT_PASS")


if __name__ == "__main__":
    run()
