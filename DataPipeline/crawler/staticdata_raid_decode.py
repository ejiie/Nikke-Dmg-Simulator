"""레이드 보스 관련 StaticData 표 디코더 + 보스 체인 조립.

배경: 서버 .mpk 표 디코드가 필드 타입/필드셋 drift 로 실패했으나, 두 발견으로 해결:
 1) **bool = 1바이트** (int32 4B 아님) — Spot_autocontrol/Is_*/Use_* 등.
 2) **nFields = 표당 상수** (=raw[4]) → 레코드마다 다음 바이트가 NF 인지로 **경계 자기검증**.
 + string 은 marker `[-(len+1)][len][utf8]` 로 자기검증, list(_list/_data)=`[count]+중첩`.
이 조합으로 UnionRaid/SoloRaid Preset·Manager, Monster·MonsterModel·MonsterStatEnhance·
MonsterParts 를 off==len clean 디코드.

레이드 보스 체인:
  {Union,Solo}RaidManager (Id, Monster_preset[, Ranking_group_id])
    → {Union,Solo}RaidPreset (Preset_group_id, Difficulty_type, Monster_stage_lv, Wave,
       Wave_name, Monster_image=보스코드 "full_ecaXXX")
  MonsterTable (Id → Element_id, Monster_model_id, *_ratio, Statenhance_id)
  MonsterModelTable (Id → Mon_prefab=코드, Grade, Attribute, Class, Size)
  MonsterStatEnhanceTable (Group_id, Lv → Level_hp/attack/defence/broken_hp[int64])
  MonsterPartsTable (파츠 HP/파괴)

⚖️ 복호값=gitignore. 이 스크립트만 커밋. 산출 boss JSON 은 파생(필요분만).

사용: python staticdata_raid_decode.py <StaticData.zip> <all_records.json> [out_dir]
"""
import json
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# per-table int64 필드 (큰 HP 등, 고정 8B)
INT64 = {
    "MonsterStatEnhanceRecord": {"Level_hp", "Level_broken_hp"},
    "MonsterPartsRecord": {"Hp", "Broken_hp"},
}


def _printable(b):
    return len(b) >= 1 and all(32 <= c <= 126 for c in b)


def _is_bool(fn):
    l = fn.lower()
    return (l.endswith("autocontrol") or l.startswith("is_") or l.startswith("use_")
            or l.startswith("has_") or l.endswith("_enable") or l.endswith("_enabled")
            or l == "nonetarget" or l == "functionnonetarget")


def _is_float(fn):
    l = fn.lower()
    return ("ratio" in l or l.endswith("_rate") or "scale" in l or "speed" in l
            or l.endswith("_time") or l.endswith("_radius") or l.endswith("_center")
            or l.endswith("_generation"))


def _is_list(fn):
    l = fn.lower()
    return l.endswith("_list") or l.endswith("_data")


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
            if m == -(L + 1) and 0 < L < 4000 and off + 8 + L <= len(raw) and _printable(raw[off + 8:off + 8 + L]):
                rec[fn] = raw[off + 8:off + 8 + L].decode("utf-8", "replace"); off += 8 + L; continue
        if fn in i64:
            rec[fn] = struct.unpack_from("<q", raw, off)[0]; off += 8
        elif _is_bool(fn):
            rec[fn] = bool(raw[off]); off += 1
        elif _is_float(fn):
            rec[fn] = round(struct.unpack_from("<f", raw, off)[0], 5); off += 4
        else:
            rec[fn] = m; off += 4
    return rec, off


def decode_table(raw, schema, i64):
    """[u32 count] + count×record. NF 상수 경계검증."""
    n = struct.unpack_from("<I", raw, 0)[0]
    nf_const = raw[4]
    off = 4
    out = []
    for ri in range(n):
        if off >= len(raw) or raw[off] != nf_const:
            raise ValueError(f"NF boundary break @rec{ri} off={off} got={raw[off] if off < len(raw) else 'EOF'} want={nf_const}")
        rec, off = _decode_record(raw, off, schema, i64)
        out.append(rec)
    return out, (off == len(raw)), n, nf_const


def _read_exact(z, basename):
    """정확 basename 매칭 (endswith 오매칭 방지: MonsterTable vs EventFARMonsterTable)."""
    for n in z.namelist():
        if n.rsplit("/", 1)[-1] == basename:
            return z.read(n)
    return None


# 레이드 보스에 필요한 표 → Record 클래스
RAID_TABLES = {
    "UnionRaidManagerTable": "UnionRaidManagerRecord",
    "UnionRaidPresetTable": "UnionRaidPresetRecord",
    "SoloRaidManagerTable": "SoloRaidManagerRecord",
    "SoloRaidPresetTable": "SoloRaidPresetRecord",
    "MonsterTable": "MonsterRecord",
    "MonsterModelTable": "MonsterModelRecord",
    "MonsterStatEnhanceTable": "MonsterStatEnhanceRecord",
    "MonsterPartsTable": "MonsterPartsRecord",
}


def main():
    import zipfile
    zip_path = sys.argv[1] if len(sys.argv) > 1 else r"..\..\Database\raw\staticdata\StaticData.zip"
    schema_path = sys.argv[2] if len(sys.argv) > 2 else r"..\..\Database\raw\staticdata\all_records.json"
    out_dir = sys.argv[3] if len(sys.argv) > 3 else r"..\..\Database\raw\staticdata\raid"
    schemas = json.load(open(schema_path, encoding="utf-8"))
    z = zipfile.ZipFile(zip_path)
    os.makedirs(out_dir, exist_ok=True)
    decoded = {}
    for tbl, rc in RAID_TABLES.items():
        raw = _read_exact(z, tbl + ".mpk")
        if raw is None:
            print(f"⚠️ {tbl}.mpk 없음"); continue
        schema = schemas.get(rc, [])
        try:
            out, ok, n, nf = decode_table(raw, schema, INT64.get(rc, set()))
        except Exception as e:
            print(f"❌ {tbl}: NF={raw[4]} schema={len(schema)}필드 → {type(e).__name__}: {e}")
            continue
        decoded[tbl] = out
        json.dump(out, open(os.path.join(out_dir, tbl + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        flag = "✅" if ok else "⚠️MIS"
        print(f"{flag} {tbl}: n={n} NF={nf} schema={len(schema)} → {tbl}.json")
    return decoded


if __name__ == "__main__":
    main()
