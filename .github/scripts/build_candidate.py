#!/usr/bin/env python3
"""Build a deterministic, unsigned PR canary; this NEVER publishes a release."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_NAME = "AppearanceStudio-Core-PR-candidate-unsigned.zip"
CANDIDATE_NOTICE = (
    "Appearance Studio Core - DEVELOPMENT CANDIDATE ONLY\n"
    "NOT A RELEASE. NOT DIGITALLY SIGNED. DO NOT REPLACE PERSONAL/ULTIMATE INSTALLATIONS.\n"
    "Official public release remains v0.9.0-rc1-tandemvector.\n"
    "Generated from the current PR source and its pinned PUBLIC_MANIFEST.json.\n"
).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inputs() -> dict[str, bytes]:
    manifest = json.loads((ROOT / "PUBLIC_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["full_product_final"] is False
    assert manifest["publisher_organization"] == "TandemVector-Labs"
    assert manifest["original_author"] == "Aliakbar Emadoddin"
    assert manifest["cryptographic_code_signing"] == "NOT_APPLIED_TO_LINUX_CORE_SOURCE"
    assert manifest["third_party_artwork_included"] is False
    rows = manifest["files"]
    assert isinstance(rows, list) and len(rows) == 27
    content: dict[str, bytes] = {}
    for entry in rows:
        name = entry["path"]
        pure = Path(name)
        assert (isinstance(name, str) and name and name == pure.as_posix()
                and not pure.is_absolute() and ".." not in pure.parts
                and "\\" not in name and name not in content)
        path = ROOT / pure
        assert path.is_file() and not path.is_symlink()
        assert not any(p.is_symlink() for p in path.parents if p != ROOT)
        raw = path.read_bytes()
        assert len(raw) == entry["bytes"] and digest(raw) == entry["sha256"], name
        content[name] = raw
    for extra in ("PUBLIC_MANIFEST.json", "RELEASE_NOTES.md"):
        path = ROOT / extra
        assert path.is_file() and not path.is_symlink() and extra not in content
        content[extra] = path.read_bytes()
    content["CANDIDATE-NOT-A-RELEASE.txt"] = CANDIDATE_NOTICE
    assert set(content).issuperset({"install.py", "uninstall.py", "LICENSE", "NOTICE"})
    return content


def encode_zip(content: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=False) as archive:
        for name, raw in sorted(content.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o100755 if name in ("install.py", "uninstall.py") else 0o100644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    return buffer.getvalue()


def verify_zip(raw: bytes, content: dict[str, bytes]) -> None:
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(content) == len(set(names))
        assert set(names) == set(content)
        for info in archive.infolist():
            assert not info.is_dir()
            assert not info.filename.startswith("/")
            assert ".." not in Path(info.filename).parts
            assert (info.external_attr >> 16) & 0o170000 == 0o100000
            assert archive.read(info) == content[info.filename]


def smoke_test(raw: bytes) -> None:
    if os.geteuid() == 0:
        raise RuntimeError("isolated XDG canary must run as a nonroot desktop user")
    with tempfile.TemporaryDirectory(prefix="core-candidate-canary-") as td:
        root = Path(td)
        source = root / "candidate"
        source.mkdir()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            archive.extractall(source)
        home = root / "home"
        home.mkdir()
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
        })
        def run(script: str, *args: str) -> subprocess.CompletedProcess:
            result = subprocess.run(
                [sys.executable, str(source / script), *args], cwd=source,
                env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            return result

        run("install.py", "--dry-run")
        run("install.py")
        manifest = root / "state" / "appearance-studio" / "install-manifest.json"
        receipt = json.loads(manifest.read_text(encoding="utf-8"))
        assert receipt["activate_requested"] is False
        assert receipt["version"] == (source / "VERSION").read_text().strip()
        pref = root / "config" / "appearance-studio" / "personal.json"
        pref.parent.mkdir(parents=True)
        pref.write_bytes(b"preserve-owner-preferences")
        custom = root / "data" / "appearance-studio" / "packs" / "owner-pack" / "owner.txt"
        custom.parent.mkdir(parents=True)
        custom.write_bytes(b"preserve-owner-pack")
        receipt_before = manifest.read_bytes()
        no_op = run("install.py")
        assert "already current" in no_op.stdout
        assert manifest.read_bytes() == receipt_before
        run("uninstall.py")
        assert not manifest.exists()
        assert pref.read_bytes() == b"preserve-owner-preferences"
        assert custom.read_bytes() == b"preserve-owner-pack"
        print("CANDIDATE_ISOLATED_INSTALL_NOOP_UNINSTALL_PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    content = inputs()
    first = encode_zip(content)
    second = encode_zip(content)
    assert first == second, "candidate ZIP is not reproducible"
    verify_zip(first, content)
    if args.smoke_test:
        smoke_test(first)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ARCHIVE_NAME
    checksum = output / (ARCHIVE_NAME + ".sha256")
    sha = digest(first)
    for path, desired in ((archive, first),
                          (checksum, (sha + "  " + ARCHIVE_NAME + "\n").encode("ascii"))):
        if path.is_symlink():
            raise RuntimeError("refusing symlinked candidate output")
        if path.exists():
            if path.read_bytes() != desired:
                raise RuntimeError("candidate path already exists with different bytes")
        else:
            path.write_bytes(desired)
    assert digest(archive.read_bytes()) == sha
    print("CANDIDATE_REPRODUCIBLE_ZIP_SHA256_PASS", sha, len(first), "bytes")
    print("CANDIDATE_ONLY_NOT_PUBLISHED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
