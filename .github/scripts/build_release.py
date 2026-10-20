#!/usr/bin/env python3
"""Create a deterministic, unsigned 0.9.1 RC1 release ZIP from verified source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from build_candidate import encode_zip, inputs, smoke_test, verify_zip

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.9.1"
TAG = "v0.9.1-rc1-tandemvector"
NAME = "AppearanceStudio-Core-v0.9.1-rc1-TandemVector-unsigned.zip"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "PUBLIC_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["release"] == TAG
    assert manifest["core_version"] == VERSION
    assert manifest["publisher_organization"] == "TandemVector-Labs"
    assert manifest["original_author"] == "Aliakbar Emadoddin"
    assert manifest["cryptographic_code_signing"] == "NOT_APPLIED_TO_LINUX_CORE_SOURCE"
    assert manifest["third_party_artwork_included"] is False
    assert manifest["full_product_final"] is False

    content = inputs()  # verify all 27 pinned source bytes before packaging
    assert content.pop("CANDIDATE-NOT-A-RELEASE.txt", None) is not None
    assert content["VERSION"].decode("ascii").strip() == VERSION
    assert ('__version__ = "' + VERSION + '"').encode("ascii") in content[
        "src/appearance_studio/__init__.py"
    ]
    assert ('subtitle="' + VERSION + '"').encode("ascii") in content[
        "src/appearance_studio/ui.py"
    ]
    assert ('release version="' + VERSION + '"').encode("ascii") in content[
        "share/metainfo/io.appearancestudio.Studio.metainfo.xml"
    ]
    pack = json.loads(content["share/appearance-studio/packs/studio-default/manifest.json"])
    assert pack["public_distribution_approved"] is True
    assert len(pack["themes"]) == 1 and pack["themes"][0]["name"] == "Appearance Studio"
    notes = content["RELEASE_NOTES.md"].decode("utf-8")
    assert TAG in notes and "unsigned" in notes.lower()
    assert "TandemVector-Labs" in notes and "Aliakbar Emadoddin" in notes
    assert not any("ultimate/" in name.lower() or name.startswith("/") for name in content)

    raw = encode_zip(content)
    assert encode_zip(content) == raw, "release ZIP is not byte-reproducible"
    verify_zip(raw, content)
    if args.smoke_test:
        smoke_test(raw)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(raw).hexdigest()
    desired = {
        output / NAME: raw,
        output / (NAME + ".sha256"): (sha + "  " + NAME + "\n").encode("ascii"),
    }
    for path, payload in desired.items():
        if path.is_symlink():
            raise RuntimeError("refusing linked release output: " + str(path))
        if path.exists():
            if path.read_bytes() != payload:
                raise RuntimeError("conflicting release asset; refusing replacement: " + str(path))
        else:
            with path.open("xb") as stream:
                stream.write(payload)
    assert hashlib.sha256((output / NAME).read_bytes()).hexdigest() == sha
    assert (output / (NAME + ".sha256")).read_bytes().split() == [
        sha.encode("ascii"), NAME.encode("ascii")
    ]
    print("CORE_0_9_1_RELEASE_REPRODUCIBLE_UNSIGNED_PASS", sha, len(raw), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
