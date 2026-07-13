#!/usr/bin/env python3
"""Recover the protected IL2CPP metadata embedded in GameAssembly.dll.

The current PC build stores an XXTEA-encrypted payload in the PE resource
``CFG/130`` while leaving ``global-metadata.dat`` empty.  This module only
performs offline file parsing: it never starts or attaches to the game.

Plaintext is returned in memory by :func:`extract_metadata`.  The CLI writes it
only when ``--output`` is explicit, and confines output to the repository's
gitignored ``Database/raw/staticdata`` tree unless the caller deliberately
passes ``--allow-output-anywhere``.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Any


DEFAULT_INPUT = Path(r"C:\NIKKE\NIKKE\game\GameAssembly.dll")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "Database/raw/staticdata"

RESOURCE_TYPE = "CFG"
RESOURCE_ID = 130
METADATA_MAGIC = 0xFAB11BAF
METADATA_VERSION = 31
_XXTEA_DELTA = 0x9E3779B9
_UINT32_MASK = 0xFFFFFFFF
_NATIVE_THRESHOLD = 1024 * 1024

# Verified against the current GameAssembly image and, independently, by the
# decrypted payload's IL2CPP magic/version and exact hashes.  Keep it out of
# reports: reports are intended to be safe to retain with build diagnostics.
_XXTEA_KEY = bytes.fromhex("45384646000000000000000000000000")

_NATIVE_SOURCE = r"""
#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

EXPORT int xxtea_decrypt_in_place(
    unsigned char *data,
    size_t byte_length,
    const unsigned char *key_bytes,
    uint32_t *plaintext_size)
{
    if (!data || !key_bytes || !plaintext_size || byte_length < 8 ||
        (byte_length & 3) != 0) {
        return 1;
    }
    uint32_t *values = (uint32_t *)data;
    const uint32_t *key = (const uint32_t *)key_bytes;
    size_t count = byte_length / 4;
    uint32_t rounds = 6u + 52u / (uint32_t)count;
    uint32_t sum = rounds * UINT32_C(0x9E3779B9);
    uint32_t y = values[0];
    while (sum != 0) {
        uint32_t e = (sum >> 2) & 3;
        for (size_t position = count - 1; position > 0; --position) {
            uint32_t z = values[position - 1];
            uint32_t mix =
                (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^
                ((sum ^ y) + (key[(position & 3) ^ e] ^ z));
            y = values[position] -= mix;
        }
        uint32_t z = values[count - 1];
        uint32_t mix =
            (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^
            ((sum ^ y) + (key[e] ^ z));
        y = values[0] -= mix;
        sum -= UINT32_C(0x9E3779B9);
    }
    uint32_t size = values[count - 1];
    if (size < byte_length - 7 || size > byte_length - 4) {
        return 2;
    }
    *plaintext_size = size;
    return 0;
}
"""


class MetadataExtractionError(RuntimeError):
    """The input is not the expected protected IL2CPP build artifact."""


@dataclass(frozen=True)
class ResourcePayload:
    data: bytes
    language_id: int
    rva: int
    file_offset: int
    code_page: int


@dataclass(frozen=True)
class _Section:
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int


def _read_exact(stream: BinaryIO, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0:
        raise MetadataExtractionError(f"{label}: invalid file range")
    stream.seek(offset)
    value = stream.read(size)
    if len(value) != size:
        raise MetadataExtractionError(f"{label}: truncated file range")
    return value


class _PEImage:
    """Small, bounds-checked PE reader for the resource directory."""

    def __init__(self, stream: BinaryIO, file_size: int) -> None:
        self.stream = stream
        self.file_size = file_size
        dos = _read_exact(stream, 0, 64, "DOS header")
        if dos[:2] != b"MZ":
            raise MetadataExtractionError("input is not a PE image (missing MZ)")
        pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
        signature_and_coff = _read_exact(
            stream, pe_offset, 24, "PE signature/COFF header"
        )
        if signature_and_coff[:4] != b"PE\0\0":
            raise MetadataExtractionError("input is not a PE image (missing PE signature)")
        number_of_sections = struct.unpack_from("<H", signature_and_coff, 6)[0]
        optional_size = struct.unpack_from("<H", signature_and_coff, 20)[0]
        if number_of_sections == 0 or number_of_sections > 96:
            raise MetadataExtractionError("PE image has an invalid section count")
        optional_offset = pe_offset + 24
        optional = _read_exact(
            stream, optional_offset, optional_size, "PE optional header"
        )
        if len(optional) < 64:
            raise MetadataExtractionError("PE optional header is too small")
        magic = struct.unpack_from("<H", optional, 0)[0]
        if magic == 0x20B:
            directory_count_offset, directory_offset = 108, 112
        elif magic == 0x10B:
            directory_count_offset, directory_offset = 92, 96
        else:
            raise MetadataExtractionError("unsupported PE optional-header magic")
        if len(optional) < directory_count_offset + 4:
            raise MetadataExtractionError("PE optional header has no data directories")
        directory_count = struct.unpack_from("<I", optional, directory_count_offset)[0]
        resource_entry = directory_offset + 2 * 8
        if directory_count <= 2 or len(optional) < resource_entry + 8:
            raise MetadataExtractionError("PE image has no resource directory")
        self.resource_rva, self.resource_size = struct.unpack_from(
            "<II", optional, resource_entry
        )
        if self.resource_rva == 0 or self.resource_size < 16:
            raise MetadataExtractionError("PE resource directory is empty")
        self.size_of_headers = struct.unpack_from("<I", optional, 60)[0]

        section_offset = optional_offset + optional_size
        raw_sections = _read_exact(
            stream, section_offset, number_of_sections * 40, "PE section table"
        )
        self.sections: list[_Section] = []
        for index in range(number_of_sections):
            base = index * 40
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII", raw_sections, base + 8
            )
            if raw_size and raw_offset + raw_size > file_size:
                raise MetadataExtractionError(
                    f"PE section {index} extends beyond the input file"
                )
            self.sections.append(
                _Section(virtual_address, virtual_size, raw_offset, raw_size)
            )

    def rva_to_offset(self, rva: int, size: int, label: str) -> int:
        if rva < 0 or size < 0 or rva + size > 0x1_0000_0000:
            raise MetadataExtractionError(f"{label}: invalid RVA range")
        if rva < self.size_of_headers and rva + size <= self.size_of_headers:
            if rva + size <= self.file_size:
                return rva
        for section in self.sections:
            # Data can only be read from the raw part of a section.  Using
            # VirtualSize here would incorrectly map zero-filled image tails.
            if (
                section.virtual_address <= rva
                and rva + size <= section.virtual_address + section.raw_size
            ):
                result = section.raw_offset + (rva - section.virtual_address)
                if result + size <= self.file_size:
                    return result
        raise MetadataExtractionError(f"{label}: RVA is not backed by file data")

    def resource_read(self, relative_offset: int, size: int, label: str) -> bytes:
        if (
            relative_offset < 0
            or size < 0
            or relative_offset + size > self.resource_size
        ):
            raise MetadataExtractionError(f"{label}: outside resource directory")
        file_offset = self.rva_to_offset(
            self.resource_rva + relative_offset, size, label
        )
        return _read_exact(self.stream, file_offset, size, label)

    def resource_name(self, name_word: int) -> str | int:
        if not name_word & 0x80000000:
            return name_word & 0xFFFF
        relative = name_word & 0x7FFFFFFF
        length_raw = self.resource_read(relative, 2, "resource name length")
        length = struct.unpack("<H", length_raw)[0]
        raw = self.resource_read(relative + 2, length * 2, "resource name")
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise MetadataExtractionError("resource name is not valid UTF-16") from exc

    def directory(self, relative_offset: int) -> list[tuple[str | int, bool, int]]:
        header = self.resource_read(relative_offset, 16, "resource directory header")
        named, numeric = struct.unpack_from("<HH", header, 12)
        total = named + numeric
        if total > 65535:
            raise MetadataExtractionError("resource directory has too many entries")
        raw = self.resource_read(
            relative_offset + 16, total * 8, "resource directory entries"
        )
        result: list[tuple[str | int, bool, int]] = []
        for index in range(total):
            name_word, target_word = struct.unpack_from("<II", raw, index * 8)
            result.append(
                (
                    self.resource_name(name_word),
                    bool(target_word & 0x80000000),
                    target_word & 0x7FFFFFFF,
                )
            )
        return result


def _unique_entry(
    entries: list[tuple[str | int, bool, int]], expected: str | int, label: str
) -> tuple[str | int, bool, int]:
    matches = [entry for entry in entries if entry[0] == expected]
    if len(matches) != 1:
        raise MetadataExtractionError(
            f"expected exactly one {label} resource {expected!r}, found {len(matches)}"
        )
    return matches[0]


def read_cfg_resource(path: Path) -> ResourcePayload:
    """Read the exact ``CFG/130`` ciphertext without loading the full DLL."""

    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            pe = _PEImage(stream, file_size)
            _, is_directory, type_offset = _unique_entry(
                pe.directory(0), RESOURCE_TYPE, "type"
            )
            if not is_directory:
                raise MetadataExtractionError("CFG resource type is not a directory")
            _, is_directory, id_offset = _unique_entry(
                pe.directory(type_offset), RESOURCE_ID, "ID"
            )
            if not is_directory:
                raise MetadataExtractionError("CFG/130 resource is not a directory")
            languages = pe.directory(id_offset)
            data_entries = [entry for entry in languages if not entry[1]]
            if len(data_entries) != 1:
                raise MetadataExtractionError(
                    "CFG/130 must have exactly one language data entry"
                )
            language, _, data_entry_offset = data_entries[0]
            if not isinstance(language, int):
                raise MetadataExtractionError("CFG/130 language is not numeric")
            data_entry = pe.resource_read(
                data_entry_offset, 16, "CFG/130 resource data entry"
            )
            data_rva, data_size, code_page, reserved = struct.unpack(
                "<IIII", data_entry
            )
            if reserved != 0 or data_size < 8 or data_size % 4:
                raise MetadataExtractionError("CFG/130 has invalid ciphertext metadata")
            data_offset = pe.rva_to_offset(data_rva, data_size, "CFG/130 ciphertext")
            data = _read_exact(stream, data_offset, data_size, "CFG/130 ciphertext")
    except OSError as exc:
        raise MetadataExtractionError(f"cannot read input PE image: {path}") from exc
    return ResourcePayload(data, language, data_rva, data_offset, code_page)


def _validate_xxtea_input(ciphertext: bytes, key: bytes) -> None:
    if len(key) != 16:
        raise MetadataExtractionError("XXTEA key must be exactly 16 bytes")
    if len(ciphertext) < 8 or len(ciphertext) % 4:
        raise MetadataExtractionError("XXTEA ciphertext must be aligned 32-bit data")


def _xxtea_decrypt_python(ciphertext: bytes, key: bytes) -> bytes:
    """Portable fallback for standard XXTEA with an included length word."""

    _validate_xxtea_input(ciphertext, key)
    if sys.byteorder != "little" or array("I").itemsize != 4:
        raise MetadataExtractionError("this extractor requires 32-bit little-endian arrays")
    values = array("I")
    values.frombytes(ciphertext)
    key_words = struct.unpack("<4I", key)
    count = len(values)
    rounds = 6 + 52 // count
    total = (rounds * _XXTEA_DELTA) & _UINT32_MASK
    y = values[0]
    while total:
        e = (total >> 2) & 3
        for position in range(count - 1, 0, -1):
            z = values[position - 1]
            mix = (
                (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
                ^ ((total ^ y) + (key_words[(position & 3) ^ e] ^ z))
            ) & _UINT32_MASK
            y = values[position] = (values[position] - mix) & _UINT32_MASK
        z = values[count - 1]
        mix = (
            (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
            ^ ((total ^ y) + (key_words[e] ^ z))
        ) & _UINT32_MASK
        y = values[0] = (values[0] - mix) & _UINT32_MASK
        total = (total - _XXTEA_DELTA) & _UINT32_MASK

    decrypted = values.tobytes()
    plaintext_size = struct.unpack_from("<I", decrypted, len(decrypted) - 4)[0]
    # Standard include-length XXTEA permits at most three bytes of word padding.
    if not len(decrypted) - 7 <= plaintext_size <= len(decrypted) - 4:
        raise MetadataExtractionError("XXTEA plaintext length word is invalid")
    return decrypted[:plaintext_size]


def _find_native_compiler() -> str | None:
    # The accelerator is optional.  It compiles only the constant source above;
    # no input paths, resource bytes, or key material are interpolated into it.
    for name in ("clang", "gcc"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    return None


def _xxtea_decrypt_native(ciphertext: bytes, key: bytes, compiler: str) -> bytes:
    """Compile a temporary helper DLL and decrypt entirely in process memory."""

    _validate_xxtea_input(ciphertext, key)
    if os.name != "nt":
        raise MetadataExtractionError("native XXTEA acceleration currently requires Windows")
    with tempfile.TemporaryDirectory(prefix="nikke-xxtea-") as temporary:
        library_path = Path(temporary) / "xxtea_helper.dll"
        try:
            compiled = subprocess.run(
                [
                    compiler,
                    "-shared",
                    "-O3",
                    "-std=c99",
                    "-x",
                    "c",
                    "-",
                    "-o",
                    str(library_path),
                ],
                input=_NATIVE_SOURCE,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MetadataExtractionError("native XXTEA helper compilation failed") from exc
        if compiled.returncode != 0 or not library_path.is_file():
            raise MetadataExtractionError("native XXTEA helper compilation failed")

        mutable = bytearray(ciphertext)
        data_buffer = (ctypes.c_ubyte * len(mutable)).from_buffer(mutable)
        key_buffer = (ctypes.c_ubyte * len(key)).from_buffer_copy(key)
        plaintext_size = ctypes.c_uint32()
        library = ctypes.CDLL(str(library_path))
        try:
            decrypt = library.xxtea_decrypt_in_place
            decrypt.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.POINTER(ctypes.c_uint32),
            ]
            decrypt.restype = ctypes.c_int
            status = decrypt(
                data_buffer,
                len(mutable),
                key_buffer,
                ctypes.byref(plaintext_size),
            )
            if status == 2:
                raise MetadataExtractionError("XXTEA plaintext length word is invalid")
            if status != 0:
                raise MetadataExtractionError("native XXTEA helper rejected its input")
            result = bytes(mutable[: plaintext_size.value])
        finally:
            # A loaded DLL cannot be removed on Windows.  Unload it before the
            # TemporaryDirectory cleanup attempts to remove the helper.
            ctypes.windll.kernel32.FreeLibrary(ctypes.c_void_p(library._handle))
        return result


def _decrypt_with_backend(
    ciphertext: bytes,
    key: bytes,
    backend: str,
) -> tuple[bytes, str, float]:
    if backend not in {"auto", "native", "python"}:
        raise MetadataExtractionError(f"unsupported XXTEA backend: {backend}")
    started = time.perf_counter()
    compiler = _find_native_compiler() if backend in {"auto", "native"} else None
    use_native = backend == "native" or (
        backend == "auto"
        and len(ciphertext) >= _NATIVE_THRESHOLD
        and compiler is not None
    )
    if use_native:
        if compiler is None:
            raise MetadataExtractionError("native XXTEA backend requested but no compiler found")
        try:
            result = _xxtea_decrypt_native(ciphertext, key, compiler)
            selected = f"native_temp_helper:{Path(compiler).name}"
        except MetadataExtractionError:
            if backend == "native":
                raise
            result = _xxtea_decrypt_python(ciphertext, key)
            selected = "python_fallback_after_native_failure"
    else:
        result = _xxtea_decrypt_python(ciphertext, key)
        selected = "python"
    return result, selected, time.perf_counter() - started


def xxtea_decrypt(
    ciphertext: bytes,
    key: bytes = _XXTEA_KEY,
    *,
    backend: str = "auto",
) -> bytes:
    """Decrypt standard XXTEA data whose final decrypted word is its length."""

    return _decrypt_with_backend(ciphertext, key, backend)[0]


def validate_metadata(metadata: bytes) -> None:
    if len(metadata) < 24:
        raise MetadataExtractionError("decrypted metadata header is truncated")
    magic, version = struct.unpack_from("<II", metadata, 0)
    if magic != METADATA_MAGIC:
        raise MetadataExtractionError(
            f"decrypted metadata magic mismatch: 0x{magic:08X}"
        )
    if version != METADATA_VERSION:
        raise MetadataExtractionError(
            f"decrypted metadata version mismatch: {version}"
        )


def fix_string_literals(metadata: bytes) -> tuple[bytes, dict[str, int]]:
    """Undo the build's per-literal XOR layer after XXTEA decryption."""

    validate_metadata(metadata)
    info_offset, info_size, data_offset, data_size = struct.unpack_from(
        "<IIII", metadata, 8
    )
    if info_size % 8:
        raise MetadataExtractionError("string-literal info table is misaligned")
    if (
        info_offset < 24
        or info_offset + info_size > len(metadata)
        or data_offset < 24
        or data_offset + data_size > len(metadata)
    ):
        raise MetadataExtractionError("string-literal table is outside metadata")
    fixed = bytearray(metadata)
    entry_count = info_size // 8
    touched = 0
    for index in range(entry_count):
        # Il2CppStringLiteral is serialized as (length, dataIndex).  The
        # current table sums to exactly the literal-data size in this order;
        # interpreting it in reverse causes massive overlapping ranges.
        literal_length, literal_offset = struct.unpack_from(
            "<II", metadata, info_offset + index * 8
        )
        if literal_offset + literal_length > data_size:
            raise MetadataExtractionError(
                f"string-literal entry {index} is outside the literal-data table"
            )
        xor_value = (literal_length ^ 0x2E) & 0xFF
        start = data_offset + literal_offset
        end = start + literal_length
        for position in range(start, end):
            fixed[position] ^= xor_value
        touched += literal_length
    result = bytes(fixed)
    validate_metadata(result)
    return result, {
        "info_offset": info_offset,
        "info_size": info_size,
        "data_offset": data_offset,
        "data_size": data_size,
        "entry_count": entry_count,
        "bytes_processed": touched,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise MetadataExtractionError(f"cannot hash input file: {path}") from exc
    return digest.hexdigest()


def _validated_output_path(
    output: Path,
    *,
    input_path: Path,
    allow_output_anywhere: bool,
    allowed_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    resolved = output.resolve()
    if resolved == input_path.resolve():
        raise MetadataExtractionError("refusing to overwrite the input PE image")
    if not allow_output_anywhere:
        root = allowed_root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise MetadataExtractionError(
                f"output must stay below {root}; use --allow-output-anywhere to override"
            ) from exc
    return resolved


def _atomic_write(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise MetadataExtractionError(f"cannot write output metadata: {path}") from exc


def extract_metadata(
    input_path: Path = DEFAULT_INPUT,
    *,
    output: Path | None = None,
    allow_output_anywhere: bool = False,
    allowed_output_root: Path = DEFAULT_OUTPUT_ROOT,
    backend: str = "auto",
) -> tuple[bytes, dict[str, Any]]:
    """Extract, validate, postprocess and optionally write IL2CPP metadata."""

    resource = read_cfg_resource(input_path)
    raw_metadata, selected_backend, decrypt_seconds = _decrypt_with_backend(
        resource.data, _XXTEA_KEY, backend
    )
    validate_metadata(raw_metadata)
    fixed_metadata, literals = fix_string_literals(raw_metadata)
    destination = None
    if output is not None:
        destination = _validated_output_path(
            output,
            input_path=input_path,
            allow_output_anywhere=allow_output_anywhere,
            allowed_root=allowed_output_root,
        )
        _atomic_write(destination, fixed_metadata)
    report: dict[str, Any] = {
        "status": "metadata_recovered",
        "input": {
            "path": str(input_path.resolve()),
            "size_bytes": input_path.stat().st_size,
            "sha256": _sha256_file(input_path),
        },
        "resource": {
            "type": RESOURCE_TYPE,
            "id": RESOURCE_ID,
            "language_id": resource.language_id,
            "rva": f"0x{resource.rva:X}",
            "file_offset": f"0x{resource.file_offset:X}",
            "size_bytes": len(resource.data),
            "ciphertext_sha256": _sha256(resource.data),
        },
        "metadata": {
            "magic": f"0x{METADATA_MAGIC:08X}",
            "version": METADATA_VERSION,
            "raw_decrypted_size_bytes": len(raw_metadata),
            "raw_decrypted_sha256": _sha256(raw_metadata),
            "decrypt_backend": selected_backend,
            "decrypt_duration_seconds": round(decrypt_seconds, 6),
            "fixed_size_bytes": len(fixed_metadata),
            "fixed_sha256": _sha256(fixed_metadata),
            "string_literal_postprocess": literals,
        },
        "output": {
            "written": destination is not None,
            "path": str(destination) if destination is not None else None,
        },
    }
    return fixed_metadata, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="offline recovery of protected IL2CPP global metadata"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-output-anywhere",
        action="store_true",
        help="allow an explicit output outside Database/raw/staticdata",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "native", "python"),
        default="auto",
        help="XXTEA backend; auto uses a temporary in-memory native helper for large files",
    )
    args = parser.parse_args(argv)
    try:
        _, report = extract_metadata(
            args.input,
            output=args.output,
            allow_output_anywhere=args.allow_output_anywhere,
            backend=args.backend,
        )
    except MetadataExtractionError as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
