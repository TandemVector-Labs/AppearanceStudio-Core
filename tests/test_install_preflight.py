from __future__ import annotations

import importlib.util
import json
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

    print("INSTALL_OWNERSHIP_PREFLIGHT_PASS")


if __name__ == "__main__":
    run()
