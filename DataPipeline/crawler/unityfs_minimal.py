#!/usr/bin/env python3
"""Strict, dependency-free reader for the UnityFS subset used by NIKKE caches.

This module intentionally does not try to be a general Unity asset library.  It
only exposes the decompressed files stored in a UnityFS bundle.  Serialized-file
objects are decoded by a separate, scope-specific reader.

Supported compression methods:

* 0: none
* 2/3: raw LZ4 blocks

LZMA and streamed/unknown layouts fail closed instead of producing a best-effort
payload.
"""

from __future__ import annotations

import dataclasses
import hashlib
import struct
from pathlib import Path


class UnityFSError(RuntimeError):
    """The bundle is malformed or uses an unsupported UnityFS feature."""


MAX_BLOCKS_INFO_SIZE = 256 * 1024 * 1024
MAX_DECOMPRESSED_STREAM_SIZE = 4 * 1024 * 1024 * 1024
ARCHIVE_COMPRESSION_MASK = 0x3F
ARCHIVE_COMBINED_INFO = 0x40
ARCHIVE_INFO_AT_END = 0x80
ARCHIVE_OLD_WEB_PLUGIN = 0x100
ARCHIVE_PADDING_AT_START = 0x200
ARCHIVE_ALLOWED_FLAGS = (
    ARCHIVE_COMPRESSION_MASK
    | ARCHIVE_COMBINED_INFO
    | ARCHIVE_INFO_AT_END
    | ARCHIVE_PADDING_AT_START
)


@dataclasses.dataclass(frozen=True)
class UnityFSNode:
    path: str
    offset: int
    size: int
    flags: int
    data: bytes


@dataclasses.dataclass(frozen=True)
class UnityFSBundle:
    format_version: int
    unity_version: str
    unity_revision: str
    flags: int
    sha256: str
    nodes: tuple[UnityFSNode, ...]


class _Reader:
    def __init__(self, data: bytes, label: str) -> None:
        self.data = data
        self.offset = 0
        self.label = label

    def _take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise UnityFSError(
                f"{self.label}: truncated at {self.offset} while reading {size} bytes"
            )
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def u16be(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def u32be(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def u64be(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def cstring(self, *, max_size: int = 4096) -> str:
        end_limit = min(len(self.data), self.offset + max_size + 1)
        end = self.data.find(b"\0", self.offset, end_limit)
        if end < 0:
            raise UnityFSError(f"{self.label}: unterminated string at {self.offset}")
        raw = self.data[self.offset:end]
        self.offset = end + 1
        try:
            return raw.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise UnityFSError(f"{self.label}: non-UTF8 string at {self.offset}") from exc


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def decompress_lz4_block(data: bytes, expected_size: int) -> bytes:
    """Decode a raw LZ4 block and require the advertised output size."""

    if expected_size < 0:
        raise UnityFSError("LZ4: negative output size")
    source = 0
    output = bytearray()

    def extended_length(base: int) -> int:
        nonlocal source
        total = base
        if base != 15:
            return total
        while True:
            if source >= len(data):
                raise UnityFSError("LZ4: truncated extended length")
            value = data[source]
            source += 1
            total += value
            if value != 255:
                return total

    while source < len(data):
        token = data[source]
        source += 1

        literal_size = extended_length(token >> 4)
        if source + literal_size > len(data):
            raise UnityFSError("LZ4: literal exceeds input")
        output.extend(data[source : source + literal_size])
        source += literal_size

        # The final LZ4 sequence may consist of literals only.
        if source == len(data):
            break
        if source + 2 > len(data):
            raise UnityFSError("LZ4: truncated match offset")
        match_offset = data[source] | (data[source + 1] << 8)
        source += 2
        if match_offset == 0 or match_offset > len(output):
            raise UnityFSError(f"LZ4: invalid match offset {match_offset}")

        match_size = extended_length(token & 0x0F) + 4
        if len(output) + match_size > expected_size:
            raise UnityFSError("LZ4: match exceeds advertised output size")
        for _ in range(match_size):
            output.append(output[-match_offset])

    if len(output) != expected_size:
        raise UnityFSError(
            f"LZ4: output size mismatch expected={expected_size} actual={len(output)}"
        )
    return bytes(output)


def _decompress(data: bytes, method: int, expected_size: int, label: str) -> bytes:
    if method == 0:
        if len(data) != expected_size:
            raise UnityFSError(
                f"{label}: uncompressed size mismatch expected={expected_size} "
                f"actual={len(data)}"
            )
        return data
    if method in (2, 3):
        return decompress_lz4_block(data, expected_size)
    raise UnityFSError(f"{label}: unsupported compression method {method}")


def parse_unityfs(data: bytes) -> UnityFSBundle:
    reader = _Reader(data, "UnityFS header")
    signature = reader.cstring(max_size=16)
    if signature != "UnityFS":
        raise UnityFSError(f"bad signature {signature!r}")
    format_version = reader.u32be()
    if format_version not in (6, 7, 8):
        raise UnityFSError(f"unsupported UnityFS format {format_version}")
    unity_version = reader.cstring(max_size=128)
    unity_revision = reader.cstring(max_size=128)
    file_size = reader.u64be()
    compressed_info_size = reader.u32be()
    uncompressed_info_size = reader.u32be()
    flags = reader.u32be()

    if file_size != len(data):
        raise UnityFSError(
            f"file size mismatch header={file_size} actual={len(data)}"
        )
    if not compressed_info_size or not uncompressed_info_size:
        raise UnityFSError("empty blocks-info section")
    if compressed_info_size > MAX_BLOCKS_INFO_SIZE or uncompressed_info_size > MAX_BLOCKS_INFO_SIZE:
        raise UnityFSError("blocks-info section exceeds safety limit")
    if flags & ~ARCHIVE_ALLOWED_FLAGS:
        raise UnityFSError(f"unsupported UnityFS archive flags {flags:#x}")
    if not flags & ARCHIVE_COMBINED_INFO:
        raise UnityFSError("blocks and directory info are not combined")
    if flags & ARCHIVE_OLD_WEB_PLUGIN:
        raise UnityFSError("old web-plugin UnityFS layout is unsupported")

    blocks_info_at_end = bool(flags & ARCHIVE_INFO_AT_END)
    need_padding_at_start = bool(flags & ARCHIVE_PADDING_AT_START)
    # UnityFS v7+ aligns the blocks-info reader.  NIKKE's v8 bundles also set
    # BlocksInfoNeedPaddingAtStart, which aligns the following data stream.
    if format_version >= 7:
        reader.offset = _align(reader.offset, 16)

    if blocks_info_at_end:
        info_start = len(data) - compressed_info_size
        if info_start < reader.offset:
            raise UnityFSError("blocks-info overlaps header")
        payload_start = reader.offset
        if need_padding_at_start:
            payload_start = _align(payload_start, 16)
    else:
        info_start = reader.offset
        payload_start = info_start + compressed_info_size
        if need_padding_at_start:
            payload_start = _align(payload_start, 16)
    info_end = info_start + compressed_info_size
    if info_start < 0 or info_end > len(data):
        raise UnityFSError("blocks-info lies outside file")

    info = _decompress(
        data[info_start:info_end],
        flags & ARCHIVE_COMPRESSION_MASK,
        uncompressed_info_size,
        "UnityFS blocks-info",
    )
    metadata = _Reader(info, "UnityFS blocks-info")
    metadata._take(16)  # Unity's content hash; source SHA-256 is recorded separately.
    block_count = metadata.u32be()
    if block_count <= 0 or block_count > 1_000_000:
        raise UnityFSError(f"invalid block count {block_count}")
    blocks: list[tuple[int, int, int]] = []
    total_uncompressed = 0
    for _ in range(block_count):
        uncompressed_size = metadata.u32be()
        compressed_size = metadata.u32be()
        block_flags = metadata.u16be()
        if uncompressed_size <= 0 or compressed_size <= 0:
            raise UnityFSError("zero-sized UnityFS data block")
        if block_flags & ~ARCHIVE_COMPRESSION_MASK:
            raise UnityFSError(
                f"unsupported UnityFS data block flags {block_flags:#x}"
            )
        total_uncompressed += uncompressed_size
        if total_uncompressed > MAX_DECOMPRESSED_STREAM_SIZE:
            raise UnityFSError("decompressed UnityFS stream exceeds safety limit")
        blocks.append((uncompressed_size, compressed_size, block_flags))

    node_count = metadata.u32be()
    if node_count <= 0 or node_count > 1_000_000:
        raise UnityFSError(f"invalid node count {node_count}")
    node_headers: list[tuple[int, int, int, str]] = []
    for _ in range(node_count):
        offset = metadata.u64be()
        size = metadata.u64be()
        node_flags = metadata.u32be()
        path = metadata.cstring(max_size=1_048_576)
        if offset + size > total_uncompressed:
            raise UnityFSError(f"node {path!r} exceeds decompressed stream")
        node_headers.append((offset, size, node_flags, path))
    if any(info[metadata.offset:]):
        raise UnityFSError("nonzero trailing bytes in blocks-info")

    payload_end = info_start if blocks_info_at_end else len(data)
    payload_offset = payload_start
    stream = bytearray()
    for index, (uncompressed_size, compressed_size, block_flags) in enumerate(blocks):
        end = payload_offset + compressed_size
        if end > payload_end:
            raise UnityFSError(f"data block {index} exceeds payload")
        stream.extend(
            _decompress(
                data[payload_offset:end],
                block_flags & ARCHIVE_COMPRESSION_MASK,
                uncompressed_size,
                f"UnityFS data block {index}",
            )
        )
        payload_offset = end
    if payload_offset > payload_end:
        raise UnityFSError("compressed data exceeds bundle payload")
    if any(data[payload_offset:payload_end]):
        raise UnityFSError("nonzero trailing bytes after UnityFS data blocks")
    if len(stream) != total_uncompressed:
        raise UnityFSError("decompressed stream size mismatch")

    nodes = tuple(
        UnityFSNode(
            path=path,
            offset=offset,
            size=size,
            flags=node_flags,
            data=bytes(stream[offset : offset + size]),
        )
        for offset, size, node_flags, path in node_headers
    )
    return UnityFSBundle(
        format_version=format_version,
        unity_version=unity_version,
        unity_revision=unity_revision,
        flags=flags,
        sha256=hashlib.sha256(data).hexdigest(),
        nodes=nodes,
    )


def read_unityfs(path: Path) -> UnityFSBundle:
    return parse_unityfs(path.read_bytes())
