"""NIKKE 게임 StaticData fetch + 복호 (라이브 로비 서버).

blablalink 에 없는 데이터(스킬 FunctionTable, monster/boss)를 게임 공식 StaticData 에서
확보한다. 메커니즘 = STATICDATA_PREP.md (출처: Hiro420/NikkeTools 정독).

⚖️ 복호 산출물은 저작물 — **재배포/커밋 금지**. Database/raw/staticdata/ 는 gitignore.
   로컬 분석 전용. 라이브 서버 fetch 라 사용자 명시 요청 시에만 실행.

흐름: POST 팩정보(protobuf) → pack 다운 → AES-CBC(key2) → zip 'data' → AES-CTR(key1) → StaticData.zip
"""
import base64
import hashlib
import os
import sys
import zipfile
import io

from curl_cffi import requests as creq
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PACK_INFO_URL = "https://global-lobby.nikke-kr.com/v1/get-static-data-pack-info-mpk"
# RE 로 추출된 하드코딩 복호 password (NikkeTools 공개)
PASSWORD = base64.b64decode(
    "y8Icb/P1B/UFusrUmCiEH/DROMdh39bmZJqFEz4aagxoDivE33L4xlXkexQ2GDun0SCBItGpGIRlEwvtowDl2Q=="
)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "staticdata")

EXIT_OK = 0
EXIT_FETCH_FAIL = 10
EXIT_DECRYPT_FAIL = 11


def _read_varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]; i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def parse_pack_info(data):
    """ResStaticDataPackInfo protobuf → dict. 1:Url 4:Salt1 5:Salt2 6:Version (2:Size varint)."""
    out = {}
    i, n = 0, len(data)
    while i < n:
        tag, i = _read_varint(data, i)
        field, wire = tag >> 3, tag & 7
        if wire == 0:                       # varint (Size)
            _, i = _read_varint(data, i)
        elif wire == 2:                     # length-delimited (string/bytes)
            ln, i = _read_varint(data, i)
            chunk = data[i:i + ln]; i += ln
            if field == 1:   out["url"] = chunk.decode("utf-8", "replace")
            elif field == 4: out["salt1"] = chunk
            elif field == 5: out["salt2"] = chunk
            elif field == 6: out["version"] = chunk.decode("utf-8", "replace")
        else:
            raise ValueError(f"unexpected wire type {wire} at field {field}")
    return out


def _aes_cbc_nopad(data, key):
    aes_key, iv = key[:16], key[-16:]
    data = data[: len(data) // 16 * 16]     # PaddingMode.None → 16-정렬
    dec = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def _aes_ctr(data, key):
    aes_key, iv = key[:16], key[-16:]       # iv = 초기 카운터(16B, big-endian 증가)
    dec = Cipher(algorithms.AES(aes_key), modes.CTR(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def fetch_staticdata():
    print("🛰️ NIKKE StaticData 팩 정보 요청...")
    try:
        r = creq.post(PACK_INFO_URL, data=b"", impersonate="chrome", timeout=30,
                      headers={"Accept": "application/octet-stream+protobuf",
                               "Content-Type": "application/octet-stream+protobuf"})
        if r.status_code != 200:
            print(f"❌ 팩정보 status {r.status_code}")
            return EXIT_FETCH_FAIL
        info = parse_pack_info(r.content)
    except Exception as e:
        print(f"❌ 팩정보 실패: {type(e).__name__}: {e}")
        return EXIT_FETCH_FAIL

    if not info.get("url") or not info.get("salt1") or not info.get("salt2"):
        print(f"❌ 팩정보 파싱 불완전: keys={list(info)}")
        return EXIT_FETCH_FAIL
    print(f"   버전 {info.get('version')}, pack={info['url'][:70]}...")

    print("⬇️ pack 다운로드...")
    try:
        pack = creq.get(info["url"], impersonate="chrome", timeout=120).content
        print(f"   {len(pack)} bytes")
    except Exception as e:
        print(f"❌ pack 다운 실패: {type(e).__name__}: {e}")
        return EXIT_FETCH_FAIL

    print("🔓 복호 (2단: CBC → zip → CTR)...")
    try:
        key1 = hashlib.pbkdf2_hmac("sha256", PASSWORD, info["salt1"], 10000, 32)
        key2 = hashlib.pbkdf2_hmac("sha256", PASSWORD, info["salt2"], 10000, 32)
        part1 = _aes_cbc_nopad(pack, key2)
        with zipfile.ZipFile(io.BytesIO(part1)) as z:
            inner_name = next(n for n in z.namelist() if n.endswith("data") or n == "data")
            inner = z.read(inner_name)
        final_zip = _aes_ctr(inner, key1)
    except Exception as e:
        print(f"❌ 복호 실패: {type(e).__name__}: {e}")
        return EXIT_DECRYPT_FAIL

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "StaticData.zip")
    with open(out_path, "wb") as f:
        f.write(final_zip)
    print(f"✅ 복호 완료 → '{out_path}' ({len(final_zip)} bytes)")
    print("   ⚖️ 재배포 금지 — gitignore 로컬 분석 전용.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(fetch_staticdata())
