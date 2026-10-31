import base64
import json

import pytest

from backend.engine.ck3_discovery import _fields
from backend.engine.ck3_writer import INSTRUCTIONS_PATH, ck3_bundle_files
from backend.engine.releases import ReleaseManager
from backend.engine.safety import sha256_bytes


def file_record(path="common/traits/review.txt", raw=b'\xef\xbb\xbfitem = { x = 2 }\r\n# exact bytes\r\n'):
    return {"path": path, "bytes_base64": base64.b64encode(raw).decode(), "sha256": sha256_bytes(raw)}


def assemble(files=None, **kwargs):
    return ck3_bundle_files(files if files is not None else [file_record()], mod_directory="review_patch",
                            name=kwargs.get("name", "Reviewed patch"), supported_version=kwargs.get("supported_version", "1.19.0.4"))


def decoded(records):
    return {item["path"]: base64.b64decode(item["bytes_base64"]) for item in records}


def test_packaging_preserves_exact_payload_and_generates_fresh_descriptors():
    original = file_record()
    original.update(remote_file_id="123", source_name="SOURCE_IDENTITY")
    records = assemble([original])
    files = decoded(records)
    assert files["review_patch/" + original["path"]] == base64.b64decode(original["bytes_base64"])
    assert files["review_patch/descriptor.mod"] == b'name="Reviewed patch"\nsupported_version="1.19.0.4"\n'
    assert files["review_patch.mod"] == files["review_patch/descriptor.mod"] + b'path="mod/review_patch"\n'
    assert b"inactive and unvalidated" in files[INSTRUCTIONS_PATH]
    assert b"123" not in files["review_patch.mod"]
    assert b"SOURCE_IDENTITY" not in b"".join(files.values())
    assert all(item["sha256"] == sha256_bytes(files[item["path"]]) for item in records)
    assert set(original) == {"path", "bytes_base64", "sha256", "remote_file_id", "source_name"}


def test_descriptor_string_escaping_round_trips_without_injecting_fields():
    name = 'Quoted "patch" \\ # { remote_file_id="evil" }'
    fields, errors = _fields(decoded(assemble(name=name))["review_patch/descriptor.mod"])
    assert not errors
    assert fields == {"name": [name], "supported_version": ["1.19.0.4"]}
    with pytest.raises(ValueError, match="single-line"):
        assemble(name='bad"\nremote_file_id="evil')
    with pytest.raises(ValueError, match="single-line"):
        assemble(supported_version="")


@pytest.mark.parametrize("path", ["descriptor.mod", "DESCRIPTOR.MOD", "elsewhere.mod", "nested/payload.mod",
                                   ".metadata/metadata.json", "IN_GAME/.METADATA/metadata.json",
                                   "../outside.txt", "/absolute.txt", "C:/drive.txt", "common/NUL.txt",
                                   "common/../bad.txt", "common/stream:ads", "common\\traits\\bad.txt"])
def test_unsafe_and_source_metadata_paths_are_rejected(path):
    with pytest.raises(ValueError):
        assemble([file_record(path)])


@pytest.mark.parametrize("paths", [["common/A.txt", "common/a.txt"],
                                    ["common/é.txt", "common/e\u0301.txt"],
                                    ["common", "common/traits/a.txt"]])
def test_case_unicode_and_file_directory_collisions_are_rejected(paths):
    with pytest.raises(ValueError, match="collid|collision"):
        assemble([file_record(path) for path in paths])


@pytest.mark.parametrize("folder", ["../bad", "mod/nested", ".hidden", "CON", "trailing.", INSTRUCTIONS_PATH,
                                     "with\\separator"])
def test_output_folder_is_portable_and_cannot_collide_with_instructions(folder):
    with pytest.raises(ValueError):
        ck3_bundle_files([file_record()], mod_directory=folder, name="Patch", supported_version="1.19")


def test_empty_files_hash_mismatch_and_invalid_base64_fail_closed():
    with pytest.raises(ValueError, match="nonempty"):
        assemble([])
    wrong = file_record()
    wrong["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="declared hash"):
        assemble([wrong])
    wrong = file_record()
    wrong["bytes_base64"] = "!invalid!"
    with pytest.raises(ValueError, match="base64"):
        assemble([wrong])
    wrong = file_record()
    wrong.pop("sha256")
    with pytest.raises(ValueError, match="SHA-256"):
        assemble([wrong])


def test_experimental_release_export_keeps_package_inactive(tmp_path):
    files = assemble()
    manager = ReleaseManager(tmp_path / "managed")
    candidate = {"id": "ck3-review-fixture", "mode": "game", "game_id": "ck3",
                 "plan": {"files": files, "write_set": [{"path": item["path"], "sha256": item["sha256"]}
                                                         for item in files]}}
    bundle = manager.export_bundle(candidate)
    assert (bundle / "files/review_patch.mod").read_bytes() == decoded(files)["review_patch.mod"]
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    assert manifest["activated"] is False and manifest["validation_label"] == "unvalidated"
    assert not (manager.root / "active-release.json").exists()
    assert manager.active() is None
