"""MemoryPack(.mpk) 디코더 — 스키마 구동. NIKKE StaticData 표.

발견 (2026-07-07): `.mpk` = **MemoryPack**(Cysharp C# 직렬화), 커스텀 아님. 스키마 출처 =
`github.com/SharpnelXu/nikke-mpk-json-converter` 의 C# 모델(`[MemoryPackable]`, `[MemoryPackOrder]`).
→ 필드 순서/타입 확정 → il2cpp 런타임 타입(맥) 불필요.

MemoryPack 와이어포맷:
  Array<T>      = [i32 length] + length×element   (length=-1 → null)
  Object        = [u8 memberCount] + memberCount×member(선언/Order 순)   (0xFF=null object)
  int=<i4 long=<q8 float=<f4 double=<d8 bool=1B enum=<i4(기본)
  string(UTF8)  = [i32 h] : h==-1 null / h==0 empty / h<=-2 UTF8(byteCount=~h, [i32 utf16len], bytes)
                            / h>0 UTF16(h chars, 2h bytes)
  List<T>/T[]   = Array 와 동일.

⚖️ 복호값=gitignore. 이 스크립트/스키마만 커밋.
"""
import json
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class Reader:
    def __init__(self, buf):
        self.b = buf
        self.o = 0

    def i8(self):
        v = self.b[self.o]; self.o += 1; return v

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.o)[0]; self.o += 4; return v

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.o)[0]; self.o += 4; return v

    def i64(self):
        v = struct.unpack_from("<q", self.b, self.o)[0]; self.o += 8; return v

    def f32(self):
        v = struct.unpack_from("<f", self.b, self.o)[0]; self.o += 4; return round(v, 6)

    def f64(self):
        v = struct.unpack_from("<d", self.b, self.o)[0]; self.o += 8; return round(v, 6)

    def string(self):
        h = self.i32()
        if h == -1:
            return None
        if h == 0:
            return ""
        if h <= -2:  # UTF8: h = ~byteCount
            bc = ~h
            _utf16 = self.i32()
            s = self.b[self.o:self.o + bc].decode("utf-8", "replace"); self.o += bc
            return s
        # h > 0: UTF16
        s = self.b[self.o:self.o + 2 * h].decode("utf-16-le", "replace"); self.o += 2 * h
        return s

    def eof(self):
        return self.o >= len(self.b)


_SCALAR = {"int", "long", "float", "double", "bool", "enum", "string"}


def read_scalar(r, t):
    if t == "int" or t == "enum":
        return r.i32()
    if t == "long":
        return r.i64()
    if t == "bool":
        return bool(r.i8())
    if t == "float":
        return r.f32()
    if t == "double":
        return r.f64()
    if t == "string":
        return r.string()
    raise ValueError(f"bad scalar {t}")


def read_value(r, t, schemas):
    """t: 'int'|'long'|..|'string'|'T[]'(array of T)|'@Name'(nested object)."""
    if t.endswith("[]"):
        inner = t[:-2]
        n = r.i32()
        if n < 0:
            return None
        return [read_value(r, inner, schemas) for _ in range(n)]
    if t.startswith("@"):
        return read_object(r, schemas[t[1:]], schemas)
    return read_scalar(r, t)


def read_object(r, schema, schemas):
    """schema = [(name, type), ...] (MemoryPackOrder 순). 헤더 u8 memberCount."""
    mc = r.i8()
    if mc == 0xFF:
        return None
    rec = {}
    for i in range(mc):
        if i < len(schema):
            name, t = schema[i]
            rec[name] = read_value(r, t, schemas)
        else:  # writer 가 스키마보다 많은 멤버 → 알 수 없음(안전상 중단 불가). int 로 스킵 시도.
            rec[f"_extra{i}"] = r.i32()
    return rec


def decode_table(buf, schema_name, schemas):
    """최상위 = Array<Record>. [i32 length] + records."""
    r = Reader(buf)
    n = r.i32()
    schema = schemas[schema_name]
    out = []
    for _ in range(n):
        out.append(read_object(r, schema, schemas))
    return out, r.o == len(buf), n


def decode_table_resync(buf, schema_name, schemas, id_lo=1, id_hi=9_999_999):
    """버전-drift 표용: memberCount 상수를 경계로 삼아 스키마 앞부분(0..len-1)만 읽고
    다음 레코드 경계로 resync. 스키마보다 실제 멤버가 많아 tail 이 어긋나도 앞 필드는 신뢰.
    전제: 각 레코드 = [u8 memberCount(상수)] + members, 첫 멤버(id)가 [id_lo,id_hi]."""
    r = Reader(buf)
    n = r.i32()
    schema = schemas[schema_name]
    mc = buf[r.o]  # 상수 memberCount
    out = []
    for _ in range(n):
        if r.o >= len(buf) or buf[r.o] != mc:
            break
        r.o += 1  # memberCount 소비
        rec = {}
        try:
            for name, t in schema:
                rec[name] = read_value(r, t, schemas)
        except Exception:
            pass  # tail drift/EOF — 앞 필드까지만, resync 로 복구
        out.append(rec)
        # 다음 경계로 resync: buf[o]==mc && 다음 i32(id) in 범위
        o = r.o
        found = False
        while o < len(buf) - 5:
            if buf[o] == mc:
                idv = struct.unpack_from("<i", buf, o + 1)[0]
                if id_lo <= idv <= id_hi:
                    found = True
                    break
            o += 1
        if not found:
            break
        r.o = o
    return out, len(out) == n, n


# ── 스키마 (SharpnelXu/nikke-mpk-json-converter C# 모델, MemoryPackOrder 순) ──
SCHEMAS = {
    "MonsterSkillInfoData": [
        ("skill_id", "int"), ("use_function_id_skill", "int[]"), ("hurt_function_id_skill", "int[]"),
    ],
    # MonsterData: MemoryPackOrder 순 (attack=9 > defence=8 이므로 defence 먼저)
    "MonsterData": [
        ("id", "long"), ("element_id", "int[]"), ("monster_model_id", "int"), ("ui_grade", "enum"),
        ("name_localkey", "string"), ("appearance_localkey", "string"), ("description_localkey", "string"),
        ("is_irregular", "bool"), ("hp_ratio", "int"), ("defence_ratio", "int"), ("attack_ratio", "int"),
        ("energy_resist_ratio", "int"), ("metal_resist_ratio", "int"), ("bio_resist_ratio", "int"),
        ("detector_center", "int"), ("detector_radius", "int"), ("nonetarget", "enum"), ("functionnonetarget", "enum"),
        ("spot_ai", "string"), ("spot_ai_defense", "string"), ("spot_ai_basedefense", "string"),
        ("spot_move_speed", "int"), ("spot_acceleration_time", "int"), ("fixed_spawn_type", "enum"),
        ("spot_rand_ratio_normal", "int"), ("spot_rand_ratio_jump", "int"), ("spot_rand_ratio_drop", "int"),
        ("spot_rand_ratio_dash", "int"), ("spot_rand_ratio_teleport", "int"), ("passive_skill_id", "int"),
        ("skill_data", "@MonsterSkillInfoData[]"), ("statenhance_id", "int"),
    ],
    "MonsterStatEnhanceData": [
        ("id", "int"), ("group_id", "int"), ("lv", "int"), ("level_hp", "long"), ("level_attack", "int"),
        ("level_defence", "int"), ("level_statdamageratio", "int"), ("level_energy_resist", "int"),
        ("level_metal_resist", "int"), ("level_bio_resist", "int"), ("level_projectile_hp", "int"),
        ("level_broken_hp", "long"),
    ],
    # MonsterSkillData(MonsterSkillTable): MemoryPackOrder 0-43 순. 실제 memberCount=46(게임이 +2 tail
    # 추가) → decode_table_resync 로 앞 44필드만 신뢰 디코드. (repo 모델 order 32 중복 오타는 weapon_object_enum 채택.)
    "MonsterSkillData": [
        ("id", "int"), ("name_localkey", "string"), ("description_localkey", "string"), ("skill_icon", "string"),
        ("skill_ani_number", "enum"), ("weapon_type", "enum"), ("attack_type", "enum"), ("fire_type", "enum"),
        ("shot_count", "int"), ("shot_timing", "enum"), ("penetration", "int"), ("projectile_speed", "int"),
        ("projectile_hp_ratio", "int"), ("projectile_def_ratio", "int"), ("projectile_radius_object", "int"),
        ("projectile_radius", "int"), ("spot_explosion_range", "int"), ("is_destroyable_projectile", "bool"),
        ("relate_anim", "bool"), ("deceleration_rate", "int"), ("casting_time", "int"), ("break_object", "string[]"),
        ("break_object_hp_raito", "int"), ("move_object", "string[]"), ("delay_time", "int"),
        ("skill_value_type_01", "enum"), ("skill_value_01", "long"), ("skill_value_type_02", "enum"),
        ("skill_value_02", "long"), ("target_character_ratio", "int"), ("target_cover_ratio", "int"),
        ("target_nothing_ratio", "int"), ("weapon_object_enum", "enum"), ("prefer_target", "enum"),
        ("show_lock_on", "bool"), ("target_count", "int"), ("object_resource", "string[]"),
        ("object_position_type", "enum"), ("object_position", "double[]"), ("is_using_timeline", "bool"),
        ("control_gauge", "int"), ("control_parts", "int[]"), ("cancel_type", "enum"), ("linked_parts", "enum"),
    ],
    # MonsterPartData: 선언순 (public 모델의 Order(2) 중복은 오타 → 선언순이 실제 23필드와 일치)
    "MonsterPartData": [
        ("id", "int"), ("monster_model_id", "int"), ("parts_name_localkey", "string"),
        ("damage_hp_ratio", "int"), ("hp_ratio", "int"), ("defence_ratio", "int"),
        ("destroy_after_anim", "bool"), ("destroy_after_movable", "bool"), ("passive_skill_id", "int"),
        ("visible_hp", "bool"), ("linked_parts_id", "int"), ("weapon_object", "string[]"),
        ("weapon_object_enum", "int[]"), ("parts_type", "enum"), ("parts_object", "string[]"),
        ("energy_resist_ratio", "int"), ("metal_resist_ratio", "int"), ("bio_resist_ratio", "int"),
        ("attack_ratio", "int"), ("parts_skin", "string"), ("monster_destroy_anim_trigger", "enum"),
        ("is_main_part", "bool"), ("is_parts_damage_able", "bool"),
    ],
}

PARTS_TYPE = {-1: "Unknown", 0: "None", 1: "Arm_Left", 2: "Arm_Right", 3: "Head", 4: "Body_Lower",
              5: "Body_Upper", 6: "Body", 7: "Chest", 8: "Belly", 9: "Leg_Front_Left", 10: "Leg_Front_Right",
              11: "Leg_Back_Left", 12: "Leg_Back_Right", 13: "Weapon_01", 14: "Weapon_02", 15: "Weapon_03",
              16: "Weapon_04", 17: "Weapon_05", 18: "Weapon_06", 19: "Weapon_07", 20: "Weapon_08",
              21: "Weapon_09", 22: "Weapon_10"}


def main():
    import os
    import zipfile
    zip_path = sys.argv[1] if len(sys.argv) > 1 else r"..\..\Database\raw\staticdata\StaticData.zip"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else r"..\..\Database\raw\staticdata\mpk"
    os.makedirs(out_dir, exist_ok=True)
    z = zipfile.ZipFile(zip_path)

    def read_exact(bn):
        for n in z.namelist():
            if n.rsplit("/", 1)[-1] == bn:
                return z.read(n)
        return None

    tables = {"MonsterPartsTable.mpk": "MonsterPartData", "MonsterTable.mpk": "MonsterData",
              "MonsterStatEnhanceTable.mpk": "MonsterStatEnhanceData"}
    for fn, sc in tables.items():
        raw = read_exact(fn)
        if raw is None:
            print(f"⚠️ {fn} 없음"); continue
        try:
            recs, clean, n = decode_table(raw, sc, SCHEMAS)
        except Exception as e:
            print(f"❌ {fn}: {type(e).__name__}: {e}"); continue
        json.dump(recs, open(os.path.join(out_dir, fn.replace(".mpk", ".json")), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"{'✅' if clean else '⚠️MIS'} {fn}: n={n} clean={clean} → {fn.replace('.mpk','.json')}")


if __name__ == "__main__":
    main()
