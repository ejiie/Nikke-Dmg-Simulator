#!/usr/bin/env python3
"""Read NIKKE's local NKDB Addressables catalogs without exporting SQLite.

The embedded AES material is used only in memory.  Public outputs from this
module contain logical catalog names, FK metadata and hashes; never the key,
host URL, player state, or a decrypted database.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import sqlite3
import struct
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:  # cryptography >= 49 moved OFB to the decrepit compatibility namespace.
    from cryptography.hazmat.decrepit.ciphers.modes import OFB
except ImportError:  # pragma: no cover - exercised by older supported runtimes
    from cryptography.hazmat.primitives.ciphers.modes import OFB


class NKDBError(RuntimeError):
    """Catalog corruption, schema drift, or a non-exact FK resolution."""


@dataclasses.dataclass(frozen=True)
class CatalogIdentity:
    logical_name: str
    size: int
    sha256: str
    segment_size: int
    segment_count: int


@dataclasses.dataclass(frozen=True)
class AddressableResolution:
    key: str
    asset_internal_id: str
    asset_provider: str
    asset_assembly: str
    asset_class: str
    bundle_key: str
    bundle_internal_id: str
    bundle_provider: str
    bundle_assembly: str
    bundle_class: str
    bundle_name: str
    bundle_hash: str
    bundle_size: int


@dataclasses.dataclass
class NKDBCatalog:
    identity: CatalogIdentity
    connection: sqlite3.Connection

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NKDBCatalog":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


_REQUIRED_COLUMNS = {
    "keys": {"key"},
    "key_entries": {"key_rowid", "entry_rowid"},
    "entries": {
        "internal_id_rowid",
        "provider_id_rowid",
        "type_rowid",
        "dependency_key_rowid",
        "data_rowid",
    },
    "entry_data": {"hash", "bundle_name", "bundle_size"},
    "internal_ids": {"internal_id"},
    "provider_ids": {"provider_id"},
    "types": {"assembly_name", "class_name"},
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_nkdb(data: bytes) -> tuple[bytes, int, int]:
    """Return the in-memory SQLite image plus segment metadata."""

    if len(data) < 36 or data[:4] != b"NKDB":
        raise NKDBError("not an NKDB catalog")
    version = int.from_bytes(data[4:8], "big")
    if version != 1:
        raise NKDBError(f"unsupported NKDB version {version}")
    key = data[8:24]
    segment_size = int.from_bytes(data[24:28], "big")
    segment_count = int.from_bytes(data[28:32], "big")
    if segment_size <= 0 or segment_count <= 0 or segment_count > 1_000_000:
        raise NKDBError(
            f"invalid segment metadata size={segment_size} count={segment_count}"
        )
    width = 5 if segment_size * segment_count > 0xFFFFFFFF else 4
    table_end = 32 + (segment_count + 1) * width
    if table_end > len(data):
        raise NKDBError("truncated NKDB offset table")
    offsets = [
        int.from_bytes(data[32 + index * width : 32 + (index + 1) * width], "big")
        for index in range(segment_count + 1)
    ]
    if offsets[0] < table_end:
        raise NKDBError("first NKDB segment overlaps its header")
    if offsets[-1] != len(data):
        raise NKDBError(
            f"final NKDB offset mismatch expected={len(data)} actual={offsets[-1]}"
        )
    if any(left >= right for left, right in zip(offsets, offsets[1:])):
        raise NKDBError("NKDB segment offsets are not strictly increasing")

    chunks: list[bytes] = []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        # The source format writes the low 32 bits little-endian (JavaScript's
        # ``| 0`` only changes signed interpretation, not these bytes).
        iv = struct.pack("<II", index & 0xFFFFFFFF, start & 0xFFFFFFFF) + bytes(8)
        decryptor = Cipher(algorithms.AES(key), OFB(iv)).decryptor()
        try:
            compressed = decryptor.update(data[start:end]) + decryptor.finalize()
            inflater = zlib.decompressobj()
            chunk = inflater.decompress(compressed, segment_size + 1)
        except (ValueError, zlib.error) as exc:
            raise NKDBError(f"segment {index}: decrypt/inflate failed") from exc
        if len(chunk) > segment_size or inflater.unconsumed_tail:
            raise NKDBError(f"segment {index}: inflated data exceeds segment size")
        if not inflater.eof:
            raise NKDBError(f"segment {index}: truncated zlib stream")
        if inflater.unused_data:
            raise NKDBError(f"segment {index}: trailing bytes after zlib stream")
        if index + 1 < segment_count and len(chunk) != segment_size:
            raise NKDBError(
                f"segment {index}: inflated size expected={segment_size} actual={len(chunk)}"
            )
        chunks.append(chunk)
    sqlite_image = b"".join(chunks)
    if not sqlite_image.startswith(b"SQLite format 3\0"):
        raise NKDBError("decrypted payload is not SQLite3")
    return sqlite_image, segment_size, segment_count


def _validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table, required in _REQUIRED_COLUMNS.items():
        if table not in tables:
            raise NKDBError(f"catalog schema missing table {table}")
        actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        missing = required - actual
        if missing:
            raise NKDBError(f"catalog schema {table} missing columns {sorted(missing)}")
    quick_check = connection.execute("PRAGMA quick_check").fetchone()
    if quick_check != ("ok",):
        raise NKDBError(f"SQLite quick_check failed: {quick_check!r}")


def open_nkdb(path: Path) -> NKDBCatalog:
    encrypted = path.read_bytes()
    sqlite_image, segment_size, segment_count = decode_nkdb(encrypted)
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(sqlite_image)
        connection.execute("PRAGMA query_only=ON")
        _validate_schema(connection)
    except Exception as exc:
        connection.close()
        if isinstance(exc, NKDBError):
            raise
        raise NKDBError(f"{path.name}: SQLite deserialize/schema validation failed") from exc
    return NKDBCatalog(
        identity=CatalogIdentity(
            logical_name=path.name,
            size=len(encrypted),
            sha256=_sha256(encrypted),
            segment_size=segment_size,
            segment_count=segment_count,
        ),
        connection=connection,
    )


_ASSET_SQL = """
SELECT
  e.internal_id_rowid, i.internal_id, e.dependency_key_rowid,
  p.provider_id, t.assembly_name, t.class_name
FROM keys AS k
JOIN key_entries AS ke ON ke.key_rowid = k.rowid
JOIN entries AS e ON e.rowid = ke.entry_rowid
LEFT JOIN internal_ids AS i ON i.rowid = e.internal_id_rowid
LEFT JOIN provider_ids AS p ON p.rowid = e.provider_id_rowid
LEFT JOIN types AS t ON t.rowid = e.type_rowid
WHERE k.key = ?
"""

_BUNDLE_SQL = """
SELECT
  k.key, i.internal_id, p.provider_id, t.assembly_name, t.class_name,
  d.bundle_name, d.hash, d.bundle_size
FROM keys AS k
JOIN key_entries AS ke ON ke.key_rowid = k.rowid
JOIN entries AS e ON e.rowid = ke.entry_rowid
LEFT JOIN internal_ids AS i ON i.rowid = e.internal_id_rowid
LEFT JOIN provider_ids AS p ON p.rowid = e.provider_id_rowid
LEFT JOIN types AS t ON t.rowid = e.type_rowid
LEFT JOIN entry_data AS d ON d.rowid = e.data_rowid
WHERE k.rowid = ?
"""


def resolve_addressable(
    catalog: NKDBCatalog,
    key: str,
    *,
    expected_class: str | None = None,
) -> AddressableResolution | None:
    """Resolve one addressable and its bundle through exact catalog FKs.

    ``None`` means that the exact key is absent.  Multiple rows, an unexpected
    type, or an incomplete dependency is catalog drift and raises ``NKDBError``.
    """

    asset_rows = catalog.connection.execute(_ASSET_SQL, (key,)).fetchall()
    if not asset_rows:
        return None
    if len(asset_rows) != 1:
        raise NKDBError(f"{key}: expected one asset entry, found {len(asset_rows)}")
    (
        _internal_rowid,
        asset_internal_id,
        dependency_key_rowid,
        asset_provider,
        asset_assembly,
        asset_class,
    ) = asset_rows[0]
    if not all(
        isinstance(value, str) and value
        for value in (asset_internal_id, asset_provider, asset_assembly, asset_class)
    ):
        raise NKDBError(f"{key}: incomplete asset FK metadata")
    if asset_provider != "UnityEngine.ResourceManagement.ResourceProviders.BundledAssetProvider":
        raise NKDBError(f"{key}: unexpected asset provider {asset_provider!r}")
    if expected_class is not None and asset_class != expected_class:
        raise NKDBError(
            f"{key}: type mismatch expected={expected_class!r} actual={asset_class!r}"
        )
    if not isinstance(dependency_key_rowid, int) or dependency_key_rowid <= 0:
        raise NKDBError(f"{key}: missing bundle dependency FK")

    bundle_rows = catalog.connection.execute(
        _BUNDLE_SQL, (dependency_key_rowid,)
    ).fetchall()
    if len(bundle_rows) != 1:
        raise NKDBError(
            f"{key}: expected one dependency bundle, found {len(bundle_rows)}"
        )
    (
        bundle_key,
        bundle_internal_id,
        bundle_provider,
        bundle_assembly,
        bundle_class,
        bundle_name,
        bundle_hash,
        bundle_size,
    ) = bundle_rows[0]
    if bundle_provider != "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider":
        raise NKDBError(f"{key}: unexpected bundle provider {bundle_provider!r}")
    if bundle_class != "UnityEngine.ResourceManagement.ResourceProviders.IAssetBundleResource":
        raise NKDBError(f"{key}: unexpected bundle type {bundle_class!r}")
    if not isinstance(bundle_hash, str) or not re.fullmatch(r"[0-9a-f]{32}", bundle_hash):
        raise NKDBError(f"{key}: invalid bundle hash")
    if not isinstance(bundle_size, int) or bundle_size <= 0:
        raise NKDBError(f"{key}: invalid bundle size")
    if not all(
        isinstance(value, str) and value
        for value in (
            bundle_key,
            bundle_internal_id,
            bundle_assembly,
            bundle_name,
        )
    ):
        raise NKDBError(f"{key}: incomplete bundle FK metadata")

    return AddressableResolution(
        key=key,
        asset_internal_id=asset_internal_id,
        asset_provider=asset_provider,
        asset_assembly=asset_assembly,
        asset_class=asset_class,
        bundle_key=bundle_key,
        bundle_internal_id=bundle_internal_id,
        bundle_provider=bundle_provider,
        bundle_assembly=bundle_assembly,
        bundle_class=bundle_class,
        bundle_name=bundle_name,
        bundle_hash=bundle_hash,
        bundle_size=bundle_size,
    )


def cached_bundle_path(naps_root: Path, resolution: AddressableResolution) -> Path:
    """Return and strictly validate NIKKE's content-hash cache path."""

    path = naps_root / resolution.bundle_hash[:2] / resolution.bundle_hash
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise NKDBError(f"bundle {resolution.bundle_hash}: not present in NAPS") from exc
    if not path.is_file() or stat.st_size != resolution.bundle_size:
        raise NKDBError(
            f"bundle {resolution.bundle_hash}: size mismatch "
            f"expected={resolution.bundle_size} actual={stat.st_size}"
        )
    with path.open("rb") as stream:
        if stream.read(8) != b"UnityFS\0":
            raise NKDBError(f"bundle {resolution.bundle_hash}: not a plain UnityFS file")
    return path
