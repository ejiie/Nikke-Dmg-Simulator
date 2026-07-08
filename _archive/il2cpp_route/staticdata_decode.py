"""StaticData `.mpk` 표 디코더 (스키마 구동).

전제: `metadata_fields.py` 로 뽑은 스키마(all_records.json) + 복호 StaticData.zip.
포맷(STATICDATA_PREP §7): `[u32 count]` + 레코드 `[u8 nFields][필드…]`(선언순).
  - int32 = 4B. string = `[i32 -(len+1)][u32 len][utf8]`(마커 자기검증 + printable 확인).
  - list = `[i32 count]` + count × 중첩레코드(재귀 `[u8 nf][fields]`).
  - int64(큰 HP) = 고정-stride 표에서 excess 로 자동감지, 또는 per-table 지정.

⚠️ 한계: 필드 타입(int32 vs int64 vs float vs List<int> vs List<struct>)은 게임 바이너리의
il2cpp type array 에만 있어(보호됨) — 스칼라 표 + 단순 리스트표는 확정 디코드되나, 혼합 복잡표
(FunctionTable/MonsterTable/CharacterShot 등 List<int>·중첩 struct·float 혼재)는 타입 필요.
완전 디코드 = arm64 네이티브 frida-il2cpp-bridge(전체 타입) — STATICDATA_DECODE_GUIDE.md.

복호값 = 저작권, gitignore. 이 스크립트/스키마만 커밋.

사용: python staticdata_decode.py <StaticData.zip> <all_records.json> <out_dir>
"""
import json
import os
import struct
import sys
import zipfile

# per-table int64 필드(고정-stride 표. 큰 HP 등). 자동감지 실패 시 여기 지정.
INT64 = {
    "CharacterStatRecord": {"Level_hp"},
    "MonsterStatEnhanceRecord": {"Level_hp", "Level_broken_hp"},
}
# 확정 디코드되는 표만 (스칼라 + SkillInfo). 복잡표는 타입 필요라 제외.
CLEAN_TABLES = [
    "AttractiveLevelTable", "CharacterStatTable", "CharacterStatEnhanceTable",
    "MonsterStatEnhanceTable", "CoverStatEnhanceTable", "RecycleResearchStatTable",
    "ElementTable", "SkillInfoTable",
]


def _float(fn):
    l = fn.lower()
    return "ratio" in l or l.endswith("_rate") or "damageratio" in l


def _is_list(fn):
    l = fn.lower()
    return l.endswith("_list") or l.endswith("_data")


def _printable(b):
    return len(b) >= 1 and all(32 <= c <= 126 for c in b)


def _decode_record(raw, off, schema, i64):
    nf = raw[off]; off += 1
    rec = {}
    for fi in range(nf):
        fn = schema[fi] if fi < len(schema) else f"f{fi}"
        if _is_list(fn):
            cnt = struct.unpack_from("<i", raw, off)[0]; off += 4
            if cnt < 0 or cnt > 50000:
                raise ValueError(f"bad list count {cnt} @ {fn}")
            elems = []
            for _ in range(cnt):
                e, off = _decode_record(raw, off, [], set())
                elems.append(e)
            rec[fn] = elems
            continue
        m = struct.unpack_from("<i", raw, off)[0]
        if m < 0 and off + 8 <= len(raw):
            L = struct.unpack_from("<I", raw, off + 4)[0]
            if m == -(L + 1) and 0 < L < 2000 and off + 8 + L <= len(raw) and _printable(raw[off + 8:off + 8 + L]):
                rec[fn] = raw[off + 8:off + 8 + L].decode("utf-8", "replace"); off += 8 + L; continue
        if fn in i64:
            rec[fn] = struct.unpack_from("<q", raw, off)[0]; off += 8
        elif _float(fn):
            rec[fn] = round(struct.unpack_from("<f", raw, off)[0], 6); off += 4
        else:
            rec[fn] = m; off += 4
    return rec, off


def decode_table(raw, schema, i64):
    n = struct.unpack_from("<I", raw, 0)[0]
    off = 4
    out = []
    for _ in range(n):
        rec, off = _decode_record(raw, off, schema, i64)
        out.append(rec)
    return out, (off == len(raw)), n


def main():
    zip_path, schema_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    schemas = json.load(open(schema_path, encoding="utf-8"))
    z = zipfile.ZipFile(zip_path)
    os.makedirs(out_dir, exist_ok=True)
    for tbl in CLEAN_TABLES:
        fn = tbl + ".mpk"
        if fn not in z.namelist():
            print(f"⚠️ {fn} 없음"); continue
        rc = tbl.replace("Table", "") + "Record"
        schema = schemas.get(rc, [])
        try:
            out, ok, n = decode_table(z.read(fn), schema, INT64.get(rc, set()))
        except Exception as e:
            print(f"❌ {tbl}: {type(e).__name__}: {e}"); continue
        json.dump(out, open(os.path.join(out_dir, tbl + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"{'✅' if ok else '⚠️MIS'} {tbl}: {n}행 → {tbl}.json")


if __name__ == "__main__":
    main()
