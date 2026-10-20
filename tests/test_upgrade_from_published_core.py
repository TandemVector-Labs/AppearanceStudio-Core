"""Validate upgrade of the actual pinned public RC1 ZIP, never a live GNOME session."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_command(script: Path, env: dict, *args: str):
    return subprocess.run([sys.executable, str(script), *args],
                          cwd=script.parent, env=env, capture_output=True,
                          text=True, timeout=30)


def must_pass(result):
    assert result.returncode == 0, result.stdout + result.stderr


def run():
    if os.geteuid() == 0:
        print("PUBLISHED_CORE_UPGRADE_SKIPPED_ROOT")
        return
    manifest = json.loads((ROOT / "PUBLIC_MANIFEST.json").read_text(encoding="utf-8"))
    archive_info = manifest["latest_organization_branded_source_archive"]
    archive_path = ROOT / archive_info["path"]
    assert archive_path.is_file() and not archive_path.is_symlink()
    assert archive_path.stat().st_size == archive_info["bytes"]
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == archive_info["sha256"]
    assert archive_info["unsigned"] is True

    with tempfile.TemporaryDirectory(prefix="appearance-studio-upgrade-") as td:
        root = Path(td)
        extracted = root / "published-base"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as package:
            assert package.testzip() is None
            names = package.namelist()
            assert len(names) == len(set(names))
            assert all(not n.startswith("/") and ".." not in Path(n).parts for n in names)
            assert all((info.external_attr >> 16) & 0o170000 != 0o120000
                       for info in package.infolist())
            package.extractall(extracted)
        installers = list(extracted.rglob("install.py"))
        assert len(installers) == 1 and installers[0].is_file()
        old_installer = installers[0]

        home = root / "home"
        home.mkdir()
        fakebin = root / "fakebin"
        fakebin.mkdir()
        log = root / "systemctl.log"
        fake = fakebin / "systemctl"
        fake.write_text(
            '#!/bin/sh\n'
            'if [ "$2" = show ]; then exit 0; fi\n'
            'echo "$*" >> "$CORE_TEST_SYSTEMCTL_LOG"\n',
            encoding="utf-8")
        fake.chmod(0o755)
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "CORE_TEST_SYSTEMCTL_LOG": str(log),
            "PATH": str(fakebin) + os.pathsep + env.get("PATH", ""),
        })

        must_pass(run_command(old_installer, env, "--activate"))
        receipt_path = root / "state" / "appearance-studio" / "install-manifest.json"
        original_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert original_receipt["activate_requested"] is True
        assert "enable --now" in log.read_text(encoding="utf-8")
        initial_log = log.read_text(encoding="utf-8")

        personal_settings = root / "config" / "appearance-studio" / "settings.json"
        personal_settings.parent.mkdir(parents=True)
        personal_settings.write_bytes(b'{"owner":"keep"}')
        personal_pack = root / "data" / "appearance-studio" / "packs" / "custom" / "asset.dat"
        personal_pack.parent.mkdir(parents=True)
        personal_pack.write_bytes(b"custom-data-must-survive")
        personal_state = root / "state" / "appearance-studio" / "local-owner.json"
        personal_state.write_bytes(b'{"preserve":true}')

        # The source branch installer must accept the genuine prior Core receipt.
        must_pass(run_command(ROOT / "install.py", env, "--dry-run"))
        upgraded = run_command(ROOT / "install.py", env)
        must_pass(upgraded)
        assert "already current" in upgraded.stdout or "preserved from existing installation" in upgraded.stdout
        new_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert new_receipt["activate_requested"] is True
        assert original_receipt["version"] == "0.9.0"
        assert new_receipt["version"] == "0.9.1"
        assert (root / "data" / "appearance-studio" / "VERSION").read_text().strip() == "0.9.1"
        assert new_receipt["owned_paths"] == original_receipt["owned_paths"]
        assert log.read_text(encoding="utf-8") == initial_log

        # Repeated owned upgrade must preserve all personal data, without
        # adding a second install or activating a second service instance.
        must_pass(run_command(ROOT / "install.py", env))
        assert personal_settings.read_bytes() == b'{"owner":"keep"}'
        assert personal_pack.read_bytes() == b"custom-data-must-survive"
        assert personal_state.read_bytes() == b'{"preserve":true}'
        assert log.read_text(encoding="utf-8") == initial_log
        assert (root / "data" / "appearance-studio" / "python" /
                "appearance_studio" / "engine.py").is_file()

        # An owned uninstall must stop the explicitly activated services and
        # remove app-owned files, never personal settings or extra theme packs.
        must_pass(run_command(ROOT / "uninstall.py", env))
        assert "disable --now" in log.read_text(encoding="utf-8")
        assert not receipt_path.exists()
        assert not (root / "data" / "appearance-studio" / "python").exists()
        assert personal_settings.read_bytes() == b'{"owner":"keep"}'
        assert personal_pack.read_bytes() == b"custom-data-must-survive"
        assert personal_state.read_bytes() == b'{"preserve":true}'
        print("PUBLISHED_CORE_ZIP_TO_OWNED_UPDATE_AND_UNINSTALL_PASS")


if __name__ == "__main__":
    run()
