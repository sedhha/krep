import hashlib
import io
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Any, cast

import yaml

from krep.registry.specs import FieldError

MAX_ZIP_BYTES = 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 200
MAX_FRONTMATTER_BYTES = 16 * 1024
MAX_BODY_LINES = 500

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
SKILL_FILE = "SKILL.md"
FRONTMATTER = "archive.SKILL.md"
READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class SkillArchive:
    content_sha256: str
    size_bytes: int
    name: str
    description: str
    warnings: list[str] = field(default_factory=list[str])


def _fail(message: str, path: str = "archive") -> tuple[None, list[FieldError]]:
    return None, [FieldError(path, message)]


def _unsafe_path(name: str) -> bool:
    return (
        name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or bool(DRIVE_RE.match(name))
        or ".." in name.split("/")
    )


def _read_entries(
    zf: zipfile.ZipFile, files: list[zipfile.ZipInfo], skill_path: str
) -> tuple[bytes | None, str | None]:
    total = 0
    skill_md = bytearray()
    for info in files:
        with zf.open(info) as src:
            while chunk := src.read(READ_CHUNK):
                total += len(chunk)
                if total > MAX_UNCOMPRESSED_BYTES:
                    return None, "uncompressed size exceeds 5 MiB"
                if info.filename == skill_path:
                    skill_md += chunk
    return bytes(skill_md), None


def _split_frontmatter(text: str) -> tuple[str, str] | str:
    lines = text.split("\n")
    if lines[0].rstrip("\r") != "---":
        return "SKILL.md must start with a --- frontmatter block"
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            block = "\n".join(lines[1:i])
            if len(block.encode()) > MAX_FRONTMATTER_BYTES:
                return "frontmatter block exceeds 16 KB"
            return block, "\n".join(lines[i + 1 :])
    return "SKILL.md frontmatter block is not closed"


def _string(front: dict[str, Any], key: str, lo: int, hi: int, required: bool) -> str | None:
    if key not in front:
        return f"{key} is required" if required else None
    value = front[key]
    if not isinstance(value, str) or not value.strip():
        return f"{key} must be a non-empty string"
    if not lo <= len(value) <= hi:
        return f"{key} must be {lo}-{hi} characters"
    return None


def _frontmatter_errors(front: dict[str, Any]) -> list[FieldError]:
    problems: dict[str, str | None] = {
        "name": _string(front, "name", 1, 64, True),
        "description": _string(front, "description", 1, 1024, True),
        "compatibility": _string(front, "compatibility", 1, 500, False),
    }
    name = front.get("name")
    if problems["name"] is None and not NAME_RE.fullmatch(str(name)):
        problems["name"] = "name must be lowercase letters, digits and single hyphens"
    if "license" in front and not isinstance(front["license"], str):
        problems["license"] = "license must be a string"
    if "allowed-tools" in front and not isinstance(front["allowed-tools"], str):
        problems["allowed-tools"] = "allowed-tools must be a string"
    if "metadata" in front:
        meta = front["metadata"]
        if not isinstance(meta, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in cast("dict[Any, Any]", meta).items()
        ):
            problems["metadata"] = "metadata must map strings to strings"
    return [FieldError(f"{FRONTMATTER}.{k}", m) for k, m in problems.items() if m]


def validate_skill_archive(
    data: bytes, slug: str
) -> tuple[SkillArchive | None, list[FieldError]]:
    if not 1 <= len(data) <= MAX_ZIP_BYTES or not data.startswith(b"PK\x03\x04"):
        return _fail("not a valid zip")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return _fail("not a valid zip")

    with zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        if not files:
            return _fail("archive is empty")
        if len(files) > MAX_ENTRIES:
            return _fail(f"more than {MAX_ENTRIES} entries")
        seen: set[str] = set()
        for info in files:
            if _unsafe_path(info.filename):
                return _fail("entry path is not allowed")
            if info.flag_bits & 0x1:
                return _fail("encrypted entries are not allowed")
            if stat.S_ISLNK(info.external_attr >> 16):
                return _fail("symlinks are not allowed")
            lowered = info.filename.lower()
            if lowered in seen:
                return _fail("duplicate entry names")
            seen.add(lowered)

        if any("/" not in i.filename for i in files):
            return _fail("every file must be inside the single top-level directory")
        tops = {i.filename.split("/", 1)[0] for i in zf.infolist() if i.filename.strip("/")}
        if len(tops) != 1:
            return _fail("archive must contain exactly one top-level directory")
        top = next(iter(tops))
        skill_path = f"{top}/{SKILL_FILE}"
        if not any(i.filename == skill_path for i in files):
            return _fail("SKILL.md must be directly inside the top-level directory")

        try:
            skill_md, problem = _read_entries(zf, files, skill_path)
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
            return _fail("not a valid zip")
    if problem is not None or skill_md is None:
        return _fail(problem or "not a valid zip")

    try:
        text = skill_md.decode()
    except UnicodeDecodeError:
        return _fail("SKILL.md must be UTF-8", FRONTMATTER)
    split = _split_frontmatter(text)
    if isinstance(split, str):
        return _fail(split, FRONTMATTER)
    block, body = split
    try:
        loaded: Any = yaml.safe_load(block)
    except yaml.YAMLError:
        return _fail("frontmatter is not valid YAML", FRONTMATTER)
    if not isinstance(loaded, dict):
        return _fail("frontmatter must be a mapping", FRONTMATTER)
    front = cast("dict[str, Any]", loaded)

    errors = _frontmatter_errors(front)
    if not errors:
        if top != front["name"]:
            errors.append(FieldError("archive", "directory name must equal frontmatter name"))
        if front["name"] != slug:
            errors.append(FieldError("archive", "frontmatter name must equal the resource slug"))
    if errors:
        return None, errors

    warnings: list[str] = []
    if len(body.splitlines()) > MAX_BODY_LINES:
        warnings.append(f"SKILL.md body is over {MAX_BODY_LINES} lines")
    return (
        SkillArchive(
            content_sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            name=front["name"],
            description=front["description"],
            warnings=warnings,
        ),
        [],
    )
