from pathlib import Path
import ast
import hashlib
import json

root = Path(__file__).resolve().parents[2]
doc = json.loads((root / "PUBLIC_MANIFEST.json").read_text())
assert doc["release"] == "v0.9.0-rc1" and doc["full_product_final"] is False
assert doc["windows_public_signed_release"] == "NOT_INCLUDED"
assert len(doc["files"]) == 27
for row in doc["files"]:
    p = root / row["path"]
    assert p.is_file() and not p.is_symlink()
    raw = p.read_bytes()
    assert len(raw) == row["bytes"]
    assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    if p.suffix == ".py":
        ast.parse(raw.decode("utf8"), filename=row["path"])
    assert b"/home/aliemad" not in raw and b"/home/mmz" not in raw
pack = json.loads((root / "share/appearance-studio/packs/studio-default/manifest.json").read_text())
assert pack["public_distribution_approved"] is True and len(pack["themes"]) == 1
print("PUBLIC_MANIFEST_27_SHA_AST_NO_PRIVATE_PATHS_PASS")
