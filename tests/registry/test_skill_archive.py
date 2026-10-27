import hashlib
import io
import os
import struct
import zipfile
from collections.abc import Mapping

import pytest

from krep.registry.skill_archive import (
    MAX_ENTRIES,
    MAX_FRONTMATTER_BYTES,
    MAX_UNCOMPRESSED_BYTES,
    MAX_ZIP_BYTES,
    validate_skill_archive,
)

SKILL_MD = "---\nname: refund-flow\ndescription: Handles refunds.\n---\n# Refunds\nBody.\n"


def zip_bytes(
    entries: Mapping[str, bytes | str] | None = None,
    infos: list[tuple[zipfile.ZipInfo, bytes]] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in (entries or {}).items():
            zf.writestr(name, content)
        for info, content in infos or []:
            zf.writestr(info, content)
    return buf.getvalue()


def skill_md(**fields: str | None) -> str:
    values: dict[str, str | None] = {"name": "refund-flow", "description": "Handles refunds."}
    values.update(fields)
    lines = [f"{k}: {v}" for k, v in values.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\n# Body\n"


def archive(md: str = SKILL_MD, directory: str = "refund-flow") -> bytes:
    return zip_bytes({f"{directory}/SKILL.md": md})


def fields(data: bytes, slug: str = "refund-flow") -> list[str]:
    parsed, errors = validate_skill_archive(data, slug)
    assert parsed is None
    assert errors
    return [e.field for e in errors]


def test_valid_minimal_archive_passes() -> None:
    data = archive()
    parsed, errors = validate_skill_archive(data, "refund-flow")
    assert errors == []
    assert parsed is not None
    assert parsed.name == "refund-flow"
    assert parsed.description == "Handles refunds."
    assert parsed.size_bytes == len(data)
    assert parsed.warnings == []


def test_hash_is_sha256_of_the_archive_bytes() -> None:
    data = archive()
    parsed, _ = validate_skill_archive(data, "refund-flow")
    assert parsed is not None
    assert parsed.content_sha256 == hashlib.sha256(data).hexdigest()


def test_extra_files_and_nested_directories_pass() -> None:
    data = zip_bytes(
        {
            "refund-flow/SKILL.md": SKILL_MD,
            "refund-flow/scripts/run.py": "print(1)",
            "refund-flow/references/a/b.md": "x",
        }
    )
    assert validate_skill_archive(data, "refund-flow")[1] == []


def test_directory_entries_are_ignored() -> None:
    data = zip_bytes(
        {"refund-flow/": b"", "refund-flow/SKILL.md": SKILL_MD, "refund-flow/scripts/": b""}
    )
    assert validate_skill_archive(data, "refund-flow")[1] == []


def test_all_optional_frontmatter_fields_pass() -> None:
    md = (
        "---\nname: refund-flow\ndescription: d\nlicense: MIT\ncompatibility: needs bash\n"
        "metadata:\n  author: me\n  version: '1.0'\nallowed-tools: Bash(git:*) Read\n---\nbody\n"
    )
    assert validate_skill_archive(archive(md), "refund-flow")[1] == []


def test_unknown_frontmatter_keys_are_accepted() -> None:
    md = "---\nname: refund-flow\ndescription: d\nx-custom: [1, 2]\n---\n"
    assert validate_skill_archive(archive(md), "refund-flow")[1] == []


def test_body_over_500_lines_is_a_warning_not_an_error() -> None:
    md = SKILL_MD + "line\n" * 600
    parsed, errors = validate_skill_archive(archive(md), "refund-flow")
    assert errors == []
    assert parsed is not None
    assert len(parsed.warnings) == 1


def test_body_of_500_lines_has_no_warning() -> None:
    md = "---\nname: refund-flow\ndescription: d\n---\n" + "line\n" * 500
    parsed, _ = validate_skill_archive(archive(md), "refund-flow")
    assert parsed is not None
    assert parsed.warnings == []


@pytest.mark.parametrize("data", [b"", b"not a zip at all", b"PK\x03\x04" + b"garbage" * 10])
def test_not_a_zip(data: bytes) -> None:
    assert fields(data) == ["archive"]


def test_empty_zip_is_rejected() -> None:
    assert fields(zip_bytes({})) == ["archive"]


def test_zip_over_one_mib_is_rejected() -> None:
    data = zip_bytes(
        {"refund-flow/SKILL.md": SKILL_MD, "refund-flow/blob.bin": os.urandom(MAX_ZIP_BYTES)}
    )
    assert len(data) > MAX_ZIP_BYTES
    assert fields(data) == ["archive"]


def test_missing_skill_md() -> None:
    assert fields(zip_bytes({"refund-flow/README.md": "x"})) == ["archive"]


def test_skill_md_is_case_sensitive() -> None:
    assert fields(zip_bytes({"refund-flow/skill.md": SKILL_MD})) == ["archive"]


def test_skill_md_at_zip_root_is_rejected() -> None:
    assert fields(zip_bytes({"SKILL.md": SKILL_MD})) == ["archive"]


def test_skill_md_nested_deeper_is_rejected() -> None:
    assert fields(zip_bytes({"refund-flow/sub/SKILL.md": SKILL_MD})) == ["archive"]


def test_two_top_level_directories() -> None:
    data = zip_bytes({"refund-flow/SKILL.md": SKILL_MD, "other/SKILL.md": SKILL_MD})
    assert fields(data) == ["archive"]


def test_directory_name_must_match_frontmatter_name() -> None:
    assert fields(archive(directory="other-dir")) == ["archive"]


def test_frontmatter_name_must_match_slug() -> None:
    assert fields(archive(), slug="different-slug") == ["archive"]


@pytest.mark.parametrize(
    "md",
    [
        "# just markdown\n",
        "---\nname: refund-flow\ndescription: d\n# never closed\n",
        "\n---\nname: refund-flow\ndescription: d\n---\n",
    ],
)
def test_frontmatter_missing_or_unclosed(md: str) -> None:
    assert fields(archive(md)) == ["archive.SKILL.md"]


@pytest.mark.parametrize("body", ["- a\n- b", "just a string", "42"])
def test_frontmatter_must_be_a_mapping(body: str) -> None:
    assert fields(archive(f"---\n{body}\n---\n")) == ["archive.SKILL.md"]


def test_invalid_yaml() -> None:
    assert fields(archive("---\nname: [unclosed\n---\n")) == ["archive.SKILL.md"]


def test_frontmatter_block_over_16_kb() -> None:
    padding = "x-pad: " + "a" * MAX_FRONTMATTER_BYTES
    md = f"---\nname: refund-flow\ndescription: d\n{padding}\n---\n"
    assert fields(archive(md)) == ["archive.SKILL.md"]


def test_yaml_python_object_tag_is_rejected_by_safe_load() -> None:
    md = "---\nname: refund-flow\ndescription: d\nx: !!python/object/apply:os.getcwd []\n---\n"
    assert fields(archive(md)) == ["archive.SKILL.md"]


@pytest.mark.parametrize(
    "name", ["Refund-Flow", "-refund", "refund-", "refund--flow", "a" * 65, "re_fund"]
)
def test_invalid_names(name: str) -> None:
    errors = fields(archive(skill_md(name=name), directory=name), slug=name)
    assert "archive.SKILL.md.name" in errors


def test_name_of_64_chars_passes() -> None:
    name = "a" * 64
    assert validate_skill_archive(archive(skill_md(name=name), directory=name), name)[1] == []


def test_name_is_required() -> None:
    assert "archive.SKILL.md.name" in fields(archive(skill_md(name=None)))


@pytest.mark.parametrize("description", [None, "''", "'   '", "'" + "d" * 1025 + "'"])
def test_invalid_descriptions(description: str | None) -> None:
    errors = fields(archive(skill_md(description=description)))
    assert "archive.SKILL.md.description" in errors


def test_description_of_1024_chars_passes() -> None:
    md = skill_md(description="'" + "d" * 1024 + "'")
    assert validate_skill_archive(archive(md), "refund-flow")[1] == []


@pytest.mark.parametrize("compatibility", ["''", "'" + "c" * 501 + "'"])
def test_invalid_compatibility(compatibility: str) -> None:
    errors = fields(archive(skill_md(compatibility=compatibility)))
    assert "archive.SKILL.md.compatibility" in errors


def test_compatibility_of_500_chars_passes() -> None:
    md = skill_md(compatibility="'" + "c" * 500 + "'")
    assert validate_skill_archive(archive(md), "refund-flow")[1] == []


def test_license_must_be_a_string() -> None:
    assert "archive.SKILL.md.license" in fields(archive(skill_md(license="[1, 2]")))


@pytest.mark.parametrize("metadata", ["{a: 1}", "[x]", "{a: {b: c}}", "plain"])
def test_metadata_must_map_strings_to_strings(metadata: str) -> None:
    assert "archive.SKILL.md.metadata" in fields(archive(skill_md(metadata=metadata)))


@pytest.mark.parametrize("value", ["[Read, Bash]", "7"])
def test_allowed_tools_must_be_a_string(value: str) -> None:
    errors = fields(archive(skill_md(**{"allowed-tools": value})))
    assert "archive.SKILL.md.allowed-tools" in errors


@pytest.mark.parametrize(
    "name",
    [
        "refund-flow/../evil.txt",
        "refund-flow/a/../../x",
        "/abs/SKILL.md",
        "refund-flow\\a.txt",
        "C:/x.txt",
    ],
)
def test_unsafe_paths(name: str) -> None:
    data = zip_bytes({"refund-flow/SKILL.md": SKILL_MD, name: "x"})
    assert "archive" in fields(data)


def test_duplicate_names_case_insensitive() -> None:
    data = zip_bytes(
        {"refund-flow/SKILL.md": SKILL_MD, "refund-flow/a.txt": "1", "refund-flow/A.TXT": "2"}
    )
    assert fields(data) == ["archive"]


def test_exact_duplicate_names() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("refund-flow/SKILL.md", SKILL_MD)
        with pytest.warns(UserWarning):
            zf.writestr("refund-flow/SKILL.md", SKILL_MD)
    assert fields(buf.getvalue()) == ["archive"]


def test_symlink_entry_is_rejected() -> None:
    link = zipfile.ZipInfo("refund-flow/link")
    link.external_attr = 0o120777 << 16
    data = zip_bytes({"refund-flow/SKILL.md": SKILL_MD}, infos=[(link, b"/etc/passwd")])
    assert fields(data) == ["archive"]


def test_encrypted_entry_is_rejected() -> None:
    data = bytearray(zip_bytes({"refund-flow/SKILL.md": SKILL_MD, "refund-flow/secret.txt": "x"}))
    offset = data.index(b"PK\x01\x02")
    while offset != -1:
        name_len = struct.unpack_from("<H", data, offset + 28)[0]
        if data[offset + 46 : offset + 46 + name_len] == b"refund-flow/secret.txt":
            data[offset + 8] |= 0x1
        offset = data.find(b"PK\x01\x02", offset + 4)
    assert fields(bytes(data)) == ["archive"]


def test_entry_count_limit() -> None:
    ok = {
        "refund-flow/SKILL.md": SKILL_MD,
        **{f"refund-flow/f{i}.txt": "" for i in range(MAX_ENTRIES - 1)},
    }
    assert validate_skill_archive(zip_bytes(ok), "refund-flow")[1] == []
    assert fields(zip_bytes({**ok, "refund-flow/one-more.txt": ""})) == ["archive"]


def test_directory_entries_do_not_count_toward_the_limit() -> None:
    entries = {
        "refund-flow/SKILL.md": SKILL_MD,
        **{f"refund-flow/d{i}/": b"" for i in range(MAX_ENTRIES + 5)},
    }
    assert validate_skill_archive(zip_bytes(entries), "refund-flow")[1] == []


def test_uncompressed_total_at_the_limit_passes() -> None:
    padding = b"\0" * (MAX_UNCOMPRESSED_BYTES - len(SKILL_MD))
    data = zip_bytes({"refund-flow/SKILL.md": SKILL_MD, "refund-flow/pad.bin": padding})
    assert len(data) < 10_000
    assert validate_skill_archive(data, "refund-flow")[1] == []


def test_zip_bomb_over_five_mib_is_rejected() -> None:
    padding = b"\0" * (MAX_UNCOMPRESSED_BYTES + 1)
    data = zip_bytes({"refund-flow/SKILL.md": SKILL_MD, "refund-flow/pad.bin": padding})
    assert len(data) < 10_000
    assert fields(data) == ["archive"]


def test_zip_bomb_spread_across_entries_is_rejected() -> None:
    chunk = b"\0" * (MAX_UNCOMPRESSED_BYTES // 2)
    entries = {
        "refund-flow/SKILL.md": SKILL_MD,
        "refund-flow/a.bin": chunk,
        "refund-flow/b.bin": chunk,
        "refund-flow/c.bin": chunk,
    }
    assert fields(zip_bytes(entries)) == ["archive"]


def test_zip_bomb_with_lying_declared_size_is_rejected() -> None:
    size = MAX_UNCOMPRESSED_BYTES + 1024
    data = zip_bytes({"refund-flow/SKILL.md": SKILL_MD, "refund-flow/pad.bin": b"\0" * size})
    lying = data.replace(struct.pack("<I", size), struct.pack("<I", 10))
    assert lying != data
    assert fields(lying) == ["archive"]
