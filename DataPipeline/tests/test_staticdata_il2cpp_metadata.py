import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import DataPipeline.crawler.staticdata_il2cpp_metadata as metadata_module

from DataPipeline.crawler.staticdata_il2cpp_metadata import (
    METADATA_MAGIC,
    METADATA_VERSION,
    MetadataExtractionError,
    _validated_output_path,
    extract_metadata,
    fix_string_literals,
    read_cfg_resource,
    validate_metadata,
    xxtea_decrypt,
)


KEY = bytes.fromhex("45384646000000000000000000000000")
MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9


def _xxtea_encrypt(plaintext, key=KEY):
    padding = (-len(plaintext)) % 4
    encoded = plaintext + b"\0" * padding + struct.pack("<I", len(plaintext))
    values = list(struct.unpack(f"<{len(encoded) // 4}I", encoded))
    key_words = struct.unpack("<4I", key)
    count = len(values)
    rounds = 6 + 52 // count
    total = 0
    z = values[-1]
    for _ in range(rounds):
        total = (total + DELTA) & MASK
        e = (total >> 2) & 3
        for position in range(count - 1):
            y = values[position + 1]
            mix = (
                (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
                ^ ((total ^ y) + (key_words[(position & 3) ^ e] ^ z))
            ) & MASK
            z = values[position] = (values[position] + mix) & MASK
        y = values[0]
        position = count - 1
        mix = (
            (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
            ^ ((total ^ y) + (key_words[(position & 3) ^ e] ^ z))
        ) & MASK
        z = values[-1] = (values[-1] + mix) & MASK
    return struct.pack(f"<{count}I", *values)


def _metadata_fixture():
    metadata = bytearray(0x60)
    struct.pack_into("<II", metadata, 0, METADATA_MAGIC, METADATA_VERSION)
    struct.pack_into("<IIII", metadata, 8, 0x40, 16, 0x50, 8)
    struct.pack_into("<II", metadata, 0x40, 4, 0)
    struct.pack_into("<II", metadata, 0x48, 3, 4)
    metadata[0x50:0x58] = b"testxyz\0"
    return bytes(metadata)


def _align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def _pe_with_cfg(ciphertext):
    resource = bytearray(0x100 + len(ciphertext))
    # Root: one named type.  The name string follows its entry.
    struct.pack_into("<IIHHHH", resource, 0, 0, 0, 0, 0, 1, 0)
    struct.pack_into("<II", resource, 16, 0x80000018, 0x80000020)
    struct.pack_into("<H6s", resource, 24, 3, "CFG".encode("utf-16-le"))
    # CFG directory: numeric resource ID 130.
    struct.pack_into("<IIHHHH", resource, 32, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", resource, 48, 130, 0x80000038)
    # ID directory: language 2052, pointing at a data entry.
    struct.pack_into("<IIHHHH", resource, 56, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", resource, 72, 2052, 80)
    struct.pack_into("<IIII", resource, 80, 0x1100, len(ciphertext), 0, 0)
    resource[0x100:] = ciphertext

    raw_size = _align(len(resource), 0x200)
    image = bytearray(0x200 + raw_size)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", image, 0x84, 0x8664, 1, 0, 0, 0, 240, 0)
    optional = 0x98
    struct.pack_into("<H", image, optional, 0x20B)
    struct.pack_into("<I", image, optional + 32, 0x1000)
    struct.pack_into("<I", image, optional + 36, 0x200)
    struct.pack_into("<I", image, optional + 56, 0x2000)
    struct.pack_into("<I", image, optional + 60, 0x200)
    struct.pack_into("<I", image, optional + 108, 16)
    struct.pack_into("<II", image, optional + 112 + 16, 0x1000, len(resource))
    section = optional + 240
    image[section : section + 8] = b".rsrc\0\0\0"
    struct.pack_into(
        "<IIII", image, section + 8, len(resource), 0x1000, raw_size, 0x200
    )
    struct.pack_into("<I", image, section + 36, 0x40000040)
    image[0x200 : 0x200 + len(resource)] = resource
    return bytes(image)


class Il2CppMetadataTests(unittest.TestCase):
    def test_standard_xxtea_length_word_round_trip(self):
        for plaintext in (b"metadata", b"unaligned bytes", bytes(range(64))):
            self.assertEqual(plaintext, xxtea_decrypt(_xxtea_encrypt(plaintext)))

        with self.assertRaisesRegex(MetadataExtractionError, "aligned"):
            xxtea_decrypt(b"bad")
        with self.assertRaisesRegex(MetadataExtractionError, "length word"):
            xxtea_decrypt(_xxtea_encrypt(b"good")[:-4] + b"\0\0\0\0")

    def test_native_backend_and_auto_fallback(self):
        plaintext = bytes(range(251)) * 10
        ciphertext = _xxtea_encrypt(plaintext)
        compiler = metadata_module._find_native_compiler()
        if compiler is not None and os.name == "nt":
            self.assertEqual(
                plaintext,
                xxtea_decrypt(ciphertext, backend="native"),
            )
        with mock.patch.object(
            metadata_module, "_find_native_compiler", return_value=None
        ):
            recovered, selected, duration = metadata_module._decrypt_with_backend(
                ciphertext, KEY, "auto"
            )
        self.assertEqual(plaintext, recovered)
        self.assertEqual("python", selected)
        self.assertGreaterEqual(duration, 0)

    def test_string_literal_postprocess_and_header_validation(self):
        raw = _metadata_fixture()
        fixed, details = fix_string_literals(raw)
        expected = bytearray(raw)
        expected[0x50:0x54] = bytes(value ^ (4 ^ 0x2E) for value in b"test")
        expected[0x54:0x57] = bytes(value ^ (3 ^ 0x2E) for value in b"xyz")
        self.assertEqual(bytes(expected), fixed)
        self.assertEqual(2, details["entry_count"])
        self.assertEqual(7, details["bytes_processed"])

        bad_magic = bytearray(raw)
        bad_magic[0] ^= 1
        with self.assertRaisesRegex(MetadataExtractionError, "magic mismatch"):
            validate_metadata(bytes(bad_magic))
        bad_version = bytearray(raw)
        struct.pack_into("<I", bad_version, 4, 30)
        with self.assertRaisesRegex(MetadataExtractionError, "version mismatch"):
            validate_metadata(bytes(bad_version))

    def test_pe_cfg_route_and_safe_atomic_output(self):
        raw = _metadata_fixture()
        cipher = _xxtea_encrypt(raw)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "GameAssembly.dll"
            input_path.write_bytes(_pe_with_cfg(cipher))
            resource = read_cfg_resource(input_path)
            self.assertEqual(2052, resource.language_id)
            self.assertEqual(cipher, resource.data)

            fixed, report = extract_metadata(input_path)
            self.assertFalse(report["output"]["written"])
            self.assertEqual(hashlib.sha256(cipher).hexdigest(), report["resource"]["ciphertext_sha256"])
            self.assertEqual(hashlib.sha256(fixed).hexdigest(), report["metadata"]["fixed_sha256"])
            serialized = json.dumps(report, sort_keys=True)
            self.assertNotIn(KEY.hex(), serialized)

            forbidden = root / "outside.dat"
            with self.assertRaisesRegex(MetadataExtractionError, "must stay below"):
                extract_metadata(input_path, output=forbidden)
            self.assertFalse(forbidden.exists())

            allowed_root = root / "Database/raw/staticdata"
            output = allowed_root / "global-metadata.fixed.dat"
            written, report = extract_metadata(
                input_path, output=output, allowed_output_root=allowed_root
            )
            self.assertEqual(written, output.read_bytes())
            self.assertTrue(report["output"]["written"])
            self.assertFalse(list(output.parent.glob("*.tmp")))

    def test_output_never_overwrites_input_even_with_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "same.dll"
            path.write_bytes(b"input")
            with self.assertRaisesRegex(MetadataExtractionError, "overwrite"):
                _validated_output_path(
                    path,
                    input_path=path,
                    allow_output_anywhere=True,
                )


if __name__ == "__main__":
    unittest.main()
