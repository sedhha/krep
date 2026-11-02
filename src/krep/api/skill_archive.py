from dataclasses import dataclass, field

from fastapi import Request
from python_multipart import FormParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import Field, File, parse_options_header

from krep.api.errors import ApiError
from krep.registry.skill_archive import MAX_ZIP_BYTES

METADATA_ALLOWANCE = 64 * 1024
MAX_BODY_BYTES = MAX_ZIP_BYTES + 1 + METADATA_ALLOWANCE


@dataclass
class MultipartBody:
    fields: dict[str, str] = field(default_factory=dict[str, str])
    archive: bytes | None = None


def is_multipart(request: Request) -> bool:
    return request.headers.get("content-type", "").startswith("multipart/form-data")


def _too_large() -> ApiError:
    return ApiError(413, "payload_too_large", "request body is too large")


async def read_multipart(request: Request) -> MultipartBody:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()

    body = MultipartBody()

    def on_field(f: Field) -> None:
        name = (f.field_name or b"").decode()
        body.fields[name] = (f.value or b"").decode(errors="replace")

    def on_file(f: File) -> None:
        if (f.field_name or b"") != b"archive":
            return
        assert f.file_object is not None
        f.file_object.seek(0)
        body.archive = f.file_object.read(MAX_ZIP_BYTES + 1)

    content_type, params = parse_options_header(request.headers.get("content-type", ""))
    try:
        parser = FormParser(
            content_type.decode(),
            on_field,
            on_file,
            boundary=params.get(b"boundary"),
            config={"MAX_MEMORY_FILE_SIZE": MAX_BODY_BYTES},
        )
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                raise _too_large()
            parser.write(chunk)
        parser.finalize()
    except FormParserError:
        raise ApiError(
            422,
            "validation_failed",
            "request validation failed",
            errors=[{"field": "body", "message": "malformed multipart body"}],
        ) from None
    return body


async def read_archive_part(request: Request) -> bytes | None:
    return (await read_multipart(request)).archive
