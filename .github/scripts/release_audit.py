from pathlib import Path
import ast
import hashlib
import json

root = Path(__file__).resolve().parents[2]
doc = json.loads((root / "PUBLIC_MANIFEST.json").read_text())
assert doc["release"] == "v0.9.1-rc1-tandemvector" and doc["full_product_final"] is False
assert doc["core_version"] == "0.9.1"
assert (root / "VERSION").read_text(encoding="utf-8").strip() == doc["core_version"]
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
# Keep the published, unsigned organization asset and attribution consistent
# with the repository's active manifest without changing the historical ZIP.
import zipfile

release = doc["previous_organization_branded_source_archive"]
assert release["unsigned"] is True and release["full_product_final"] is False
assert release["original_rc1_tag_archive_unchanged"] is True
zip_path = root / release["path"]
assert zip_path.is_file() and not zip_path.is_symlink()
assert zip_path.stat().st_size == release["bytes"]
assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == release["sha256"]
checksum_path = zip_path.with_name(zip_path.name + ".sha256")
parts = checksum_path.read_text(encoding="utf-8").split()
assert parts == [release["sha256"], zip_path.name]
with zipfile.ZipFile(zip_path) as archive:
    names = archive.namelist()
    assert archive.testzip() is None
    assert len(names) == len(set(names)) and len(names) >= 27
    assert not any(n.startswith("/") or ".." in Path(n).parts for n in names)

for filename in ("README.md", "RELEASE_NOTES.md"):
    words = (root / filename).read_text(encoding="utf-8")
    assert doc["publisher_organization"] in words, filename
    assert doc["original_author"] in words, filename
    assert "unsigned" in words.lower() or "not applied" in words.lower(), filename
assert "Arclenor Technologies" not in (root / "RELEASE_NOTES.md").read_text(encoding="utf-8")
print("ORGANIZATION_BRANDED_ARTIFACT_INTEGRITY_PASS")

print("PUBLIC_MANIFEST_27_SHA_AST_NO_PRIVATE_PATHS_PASS")
