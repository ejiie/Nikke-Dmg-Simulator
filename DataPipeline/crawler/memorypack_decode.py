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
    def __init__(self, buf, *, strict_strings=False):
        self.b = buf
        self.o = 0
        self.strict_strings = strict_strings

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
            errors = "strict" if self.strict_strings else "replace"
            s = self.b[self.o:self.o + bc].decode("utf-8", errors); self.o += bc
            return s
        # h > 0: UTF16
        errors = "strict" if self.strict_strings else "replace"
        s = self.b[self.o:self.o + 2 * h].decode("utf-16-le", errors); self.o += 2 * h
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


def decode_table(buf, schema_name, schemas, *, strict_strings=False):
    """최상위 = Array<Record>. [i32 length] + records."""
    r = Reader(buf, strict_strings=strict_strings)
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
    "SoloRaidManagerData": [
        ("Id", "int"), ("Monster_preset", "int"), ("Ranking_group_id", "int"),
    ],
    "SoloRaidPresetData": [
        ("Id", "int"), ("Preset_group_id", "int"), ("Difficulty_type", "enum"),
        ("Quick_battle_type", "enum"), ("Character_lv", "int"),
        ("Wave_open_condition", "int"), ("Wave_order", "int"), ("Wave", "int"),
        ("Monster_stage_lv", "int"), ("Monster_stage_lv_change_group", "int"),
        ("Dynamic_object_stage_lv", "int"), ("Cover_stage_lv", "int"),
        ("Spot_autocontrol", "bool"), ("Wave_name", "string"),
        ("Wave_description", "string"), ("Monster_image_si", "string"),
        ("Monster_image", "string"), ("First_clear_reward_id", "int"),
        ("Reward_id", "int"),
    ],
    # WaveDataTable.*: Stages.cs 선언 순서. 공개 모델의 일부 MemoryPackOrder 중복
    # annotation은 오타이며, 아래 선언 순서로 현재 wave_Intercept_001 전체 286개
    # 레코드와 nested object를 EOF까지 정확히 소비한다.
    "WaveMonster": [
        ("wave_monster_id", "long"), ("spawn_type", "enum"),
    ],
    "WavePathData": [
        ("wave_path", "string"), ("private_monster_count", "int"),
        ("wave_monster_list", "@WaveMonster[]"),
    ],
    "WaveData": [
        ("stage_id", "int"), ("group_id", "string"), ("spot_mod", "enum"),
        ("ui_theme", "enum"), ("battle_time", "int"), ("mod_value", "string"),
        ("monster_count", "int"), ("use_intro_scene", "bool"), ("wave_repeat", "bool"),
        ("point_data", "string"), ("point_data_fly", "string"),
        ("background_name", "string"), ("theme", "enum"), ("theme_time", "enum"),
        ("stage_info_bg", "string"), ("target_list", "long[]"),
        ("wave_data", "@WavePathData[]"), ("close_monster_count", "int"),
        ("mid_monster_count", "int"), ("far_monster_count", "int"),
    ],
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
    # MonsterModelTable: exact 13-member wire schema.  mon_prefab is the
    # authoritative SpotMonster addressable stem used by the timeline stage.
    "MonsterModelData": [
        ("id", "int"), ("resource_id", "int"), ("mon_prefab", "string"),
        ("grade", "enum"), ("monster_generation", "float"), ("size", "enum"),
        ("dissolve_type", "enum"), ("attribute", "enum"), ("move_type", "enum"),
        ("category_type_1", "enum"), ("category_type_2", "enum"),
        ("category_type_3", "enum"), ("monster_class", "enum"),
    ],
    # MonsterSkillData(MonsterSkillTable): current wire memberCount=46 exact.
    # 공개 모델의 Order(32) 중복 중 두 필드는 모두 존재하며 calling_group_id가 뒤따른다.
    # current build가 추가한 show_breakable_time(bool)까지 포함하면 4703/4703 off==len.
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
        ("target_nothing_ratio", "int"), ("weapon_object_enum", "enum"), ("calling_group_id", "int"),
        ("prefer_target", "enum"), ("show_lock_on", "bool"), ("target_count", "int"),
        ("object_resource", "string[]"),
        ("object_position_type", "enum"), ("object_position", "double[]"), ("is_using_timeline", "bool"),
        ("control_gauge", "int"), ("show_breakable_time", "bool"), ("control_parts", "int[]"),
        ("cancel_type", "enum"), ("linked_parts", "enum"),
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

    # ── 스킬 계층 (2026-07-08, Skills.cs / CharacterData.cs — 스킬 런타임 THE GAP 데이터원) ──
    # ⚠ MemoryPackOrder ≠ 선언순인 필드 존재 (FunctionData 9↔10, SkillData 1..5↔0.., 15↔16) — 아래는 Order 정렬 완료본.
    "SkillValueData": [
        ("skill_value_type", "enum"), ("skill_value", "long"),
    ],
    # SkillData = CharacterSkillTable.mpk 레코드 (버스트/액티브 스킬 구조)
    "SkillData": [
        ("id", "int"), ("attack_type", "enum"), ("counter_type", "enum"), ("prefer_target", "enum"),
        ("prefer_target_condition", "enum"), ("skill_cooltime", "int"), ("skill_type", "enum"),
        ("skill_value_data", "@SkillValueData[]"), ("duration_type", "enum"), ("duration_value", "int"),
        ("before_use_function_id_list", "int[]"), ("before_hurt_function_id_list", "int[]"),
        ("after_use_function_id_list", "int[]"), ("after_hurt_function_id_list", "int[]"),
        ("resource_name", "string"), ("shake_id", "int"), ("icon", "string"),
    ],
    "SkillFunction": [
        ("function", "int"),
    ],
    # StateEffectData = StateEffectTable.mpk (패시브 스킬 → function 다발)
    "StateEffectData": [
        ("id", "int"), ("use_function_id_list", "int[]"), ("hurt_function_id_list", "int[]"),
        ("functions", "@SkillFunction[]"), ("icon", "string"),
    ],
    # FunctionData = FunctionTable.mpk (효과 원자 단위 — what/when/who/how much/duration).
    # 과거 RE 실패 원인 규명: long 3개(function_value/status_trigger_value/status_trigger2_value) 를
    # int 로 읽어 member index 가 +3 밀렸었음(관측 Buff_icon@33 = Order 30 + 3).
    "FunctionData": [
        ("id", "int"), ("group_id", "int"), ("level", "int"), ("function_battlepower", "int"),
        ("name_localkey", "string"), ("description_localkey", "string"), ("buff", "enum"),
        ("buff_remove", "enum"), ("function_type", "enum"), ("function_standard", "enum"),
        ("function_value_type", "enum"), ("function_value", "long"), ("full_count", "int"),
        ("is_cancel", "bool"), ("delay_type", "enum"), ("delay_value", "int"),
        ("duration_type", "enum"), ("duration_value", "int"), ("limit_value", "int"),
        ("function_target", "enum"), ("timing_trigger_type", "enum"), ("timing_trigger_standard", "enum"),
        ("timing_trigger_value", "int"), ("status_trigger_type", "enum"), ("status_trigger_standard", "enum"),
        ("status_trigger_value", "long"), ("status_trigger2_type", "enum"), ("status_trigger2_standard", "enum"),
        ("status_trigger2_value", "long"), ("keeping_type", "enum"), ("buff_icon", "string"),
        ("element_reaction_icon", "string"), ("shot_fx_list_type", "enum"),
        ("fx_prefab_01", "string"), ("fx_target_01", "enum"), ("fx_socket_point_01", "enum"),
        ("fx_prefab_02", "string"), ("fx_target_02", "enum"), ("fx_socket_point_02", "enum"),
        ("fx_prefab_03", "string"), ("fx_target_03", "enum"), ("fx_socket_point_03", "enum"),
        ("fx_prefab_full", "string"), ("fx_target_full", "enum"), ("fx_socket_point_full", "enum"),
        ("fx_prefab_01_arena", "string"), ("fx_target_01_arena", "enum"), ("fx_socket_point_01_arena", "enum"),
        ("fx_prefab_02_arena", "string"), ("fx_target_02_arena", "enum"), ("fx_socket_point_02_arena", "enum"),
        ("fx_prefab_03_arena", "string"), ("fx_target_03_arena", "enum"), ("fx_socket_point_03_arena", "enum"),
        ("connected_function", "int[]"),
    ],
    "SkillDescriptionValue": [
        ("description_value", "string"),
    ],
    # SkillInfoData = SkillInfoTable.mpk (스킬 레벨별 설명/수치 — roledata skills 와 동일 계열)
    "SkillInfoData": [
        ("id", "int"), ("group_id", "int"), ("skill_level", "int"), ("next_level_id", "int"),
        ("level_up_cost_id", "int"), ("icon", "string"), ("name_localkey", "string"),
        ("description_localkey", "string"), ("info_description_localkey", "string"),
        ("description_value_list", "@SkillDescriptionValue[]"),
    ],
    # NikkeCharacterData = CharacterTable.mpk — 니케 → skill1/skill2/ulti(버스트) 링크 (+ crit/shot/bonusrange).
    # ⚠ 빌드 drift: qa-260702 실직렬화 = 40멤버 — 컨버터 모델의 `surface_category`(Order14) 가 **부재**.
    #   판별 = 의미 배제(대안 drop 은 class=0 등 불능) + roledata 192캐릭 전수 교차검증 mismatch 0
    #   (element/bonusrange/critical/burst_duration/apply_delay). LOCAL_GAME_DATA §3 필드셋 drift 사례 추가.
    "NikkeCharacterData": [
        ("id", "int"), ("name_localkey", "string"), ("description_localkey", "string"), ("resource_id", "int"),
        ("additional_skins", "string[]"), ("name_code", "int"), ("order", "int"), ("original_rare", "enum"),
        ("grade_core_id", "int"), ("grow_grade", "int"), ("stat_enhance_id", "int"), ("corporation", "enum"),
        ("corporation_sub_type", "enum"), ("character_class", "enum"),
        ("element_id", "int[]"), ("critical_ratio", "int"), ("critical_damage", "int"), ("shot_id", "int"),
        ("bonusrange_min", "int"), ("bonusrange_max", "int"), ("use_burst_skill", "enum"),
        ("change_burst_step", "enum"), ("burst_apply_delay", "int"), ("burst_duration", "int"),
        ("ulti_skill_id", "int"), ("skill1_id", "int"), ("skill1_table", "enum"), ("skill2_id", "int"),
        ("skill2_table", "enum"), ("eff_category_type", "enum"), ("eff_category_value", "int"),
        ("category_type_1", "enum"), ("category_type_2", "enum"), ("category_type_3", "enum"),
        ("cv_localkey", "string"), ("squad", "enum"), ("piece_id", "int"), ("is_visible", "bool"),
        ("prism_is_active", "bool"), ("is_detail_close", "bool"),
    ],
}

# ── enum 값 → 이름 (Skills.cs / CharacterData.cs 발췌; 조립(ETL)·엔진 K4 매핑용) ──
FUNCTION_TYPE = {-1: "Unknown", 0: "None", 1: "StatAtk", 2: "HealCharacter", 3: "HealCover", 4: "Attention", 5: "AllAmmo", 6: "Stun", 7: "AutoTargeting", 8: "StatAccuracyCircle", 9: "StatCritical", 10: "StatShotCount", 11: "StatChargeDamage", 12: "StatExplosion", 13: "StatReloadTime", 14: "StatAmmo", 15: "StatDef", 16: "StatRateOfFire", 17: "SkillCooltime", 18: "ImmuneStun", 19: "StatUltiGaugeSec", 20: "StatUltiGaugeKill", 21: "StatUltiGaugeUseSkill", 22: "StatUltiGaugeSkillHit", 23: "StatUltiGaugeShotHit", 24: "StatUltiGaugeHurt", 25: "StatUltiGaugeEmptyAmmo", 26: "GainUltiGauge", 27: "GainAmmo", 28: "DamageEnergy", 29: "DamageMetal", 30: "DamageBio", 31: "Taunt", 32: "DrainHp", 33: "DrainUltiGauge", 34: "ImmuneEnergy", 35: "ImmuneMetal", 36: "ImmuneBio", 37: "ImmuneDamage", 38: "ImmuneDamage_MainHP", 39: "IgnoreDamage", 40: "Immortal", 41: "GravityBomb", 42: "DamageReduction", 43: "DamageShare", 44: "DamageRatioEnergy", 45: "DamageRatioMetal", 46: "DamageRatioBio", 47: "GaugeShield", 48: "StatProjectileSpeed", 49: "UseSkill1", 50: "UseSkill2", 51: "StatCriticalDamage", 52: "HealVariation", 53: "HealShare", 54: "StatPenetration", 55: "LinkAtk", 56: "LinkDef", 57: "StatFirstDelay", 58: "StatEnergyResist", 59: "StatMetalResist", 60: "StatBioResist", 61: "StatChargeTime", 62: "DrainHpBuff", 63: "StatHp", 64: "DefIgnoreDamage", 65: "AtkChangHpRate", 66: "DefChangHpRate", 67: "ForcedStop", 68: "DamageRecoverHeal", 69: "FullBurstDamage", 70: "Infection", 71: "Resurrection", 72: "UseCharacterSkillId", 73: "ImmuneForcedStop", 74: "ImmuneGravityBomb", 75: "Damage", 76: "DamageRatioUp", 77: "BuffRemove", 78: "DebuffRemove", 79: "IncReactTime", 80: "IncElementDmg", 81: "ChangeCoolTimeSkill1", 82: "ChangeCoolTimeSkill2", 83: "ChangeCoolTimeUlti", 84: "ChangeCoolTimeAll", 85: "StatEndRateOfFire", 86: "StatRateOfFirePerShot", 87: "CoreShotDamageChange", 88: "CoreShotDamageRateChange", 89: "DebuffImmune", 90: "IncBurstDuration", 91: "ChangeHp", 92: "PlusBuffCount", 93: "PlusDebuffCount", 94: "StatHpHeal", 95: "AddDamage", 96: "BreakDamage", 97: "HpProportionDamage", 98: "NormalStatCritical", 99: "CopyAtk", 100: "CopyDef", 101: "CopyHp", 102: "FirstBurstGaugeSpeedUp", 103: "InstantDeath", 104: "ImmuneInstantDeath", 105: "ChangeCurrentHpValue", 106: "SingleBurstDamage", 107: "Hide", 108: "StatAmmoLoad", 109: "CoverResurrection", 110: "ImmuneOtherElement", 111: "BurstGaugeCharge", 112: "PartsDamage", 113: "ProjectileDamage", 114: "Silence", 115: "WindReduction", 116: "ElectronicReduction", 117: "FireReduction", 118: "WaterReduction", 119: "IronReduction", 120: "ChangeMaxSkillCoolTime1", 121: "ChangeMaxSkillCoolTime2", 122: "ChangeMaxSkillCoolTimeUlti", 123: "HealDecoy", 124: "Transformation", 125: "Immortal_value", 126: "StatMaintainFireStance", 127: "AtkChangeMaxHpRate", 128: "OverHealSave", 129: "ChargeTimeChangetoDamage", 130: "TimingTriggerValueChange", 131: "TargetGroupid", 132: "FinalStatHp", 133: "FinalStatHpHeal", 134: "CycleUse", 135: "DamageShareInstant", 136: "TargetPartsId", 137: "PartsHpChangeUIOff", 138: "PartsHpChangeUIOn", 139: "StatBonusRangeMax", 140: "StatBonusRangeMin", 141: "Uncoverable", 142: "CallingMonster", 143: "StatBurstSkillCoolTime", 144: "ImmuneChangeCoolTimeUlti", 145: "ShareDamageIncrease", 146: "FullChargeHitDamageRepeat", 147: "ChargeDamageChangeMaxStatAmmo", 148: "StatSpotRadius", 149: "PenetrationDamage", 150: "DamageShareInstantUnable", 151: "DamageFunctionUnable", 152: "StatChargeTimeImmune", 153: "AllStepBurstKeepStep", 154: "AllStepBurstNextStep", 155: "IncBarrierHp", 156: "HealBarrier", 157: "ExplosiveCircuitAccrueDamageRatio", 158: "AtkReplaceMaxHpRate", 159: "FixStatReloadTime", 160: "DefIgnoreDamageRatio", 161: "ChangeNormalDefIgnoreDamage", 162: "BonusRangeDamageChange", 163: "GivingHealVariation", 164: "RemoveFunctionGroup", 165: "NormalDamageRatioChange", 166: "NormalStatCriticalDamage", 167: "FunctionOverlapChange", 168: "DurationValueChange", 169: "DurationDamageRatio", 170: "RepeatUseBurstStep", 171: "PartsImmuneDamage", 172: "BarrierDamage", 173: "CurrentHpRatioDamage", 174: "StatReloadBulletRatio", 175: "ImmuneAttention", 176: "ImmuneInstallBarrier", 177: "ImmuneTaunt", 178: "FullCountDamageRatio", 179: "AddIncElementDmgType", 180: "ChangeUseBurstSkill", 181: "ChangeChangeBurstStep", 182: "StickyProjectileExplosion", 183: "StickyProjectileCollisionDamage", 184: "ProjectileExplosionDamage", 185: "StickyProjectileInstantExplosion", 186: "MinusDebuffCount", 187: "AtkBuffChange", 188: "OutBonusRangeDamageChange", 189: "InstantAllBurstDamage", 190: "PlusInstantSkillTargetNum", 191: "StatInstantSkillRange", 192: "DamageFunctionTargetGroupId", 193: "DamageFunctionValueChange", 194: "DmgReductionExcludingBreakCol", 195: "ChangeHurtFxExcludingBreakCol", 196: "FocusAttack", 197: "ImmediatelyBuffCheckImmune", 198: "DurationBuffCheckImmune", 199: "ImmediatelyDebuffCheckImmune", 200: "DurationDebuffCheckImmune", 201: "NoOverlapStatAmmo", 202: "DurationDamage", 203: "DefIgnoreSkillDamageInstant", 204: "EmptyFunction", 205: "DamageShareLowestPriority", 206: "ForcedReload", 207: "StatDefNoneBreakCol", 208: "ChangeHealChargeValue", 209: "FixStatChargeTime", 210: "GrayScale", 211: "ChangeMaxTargetingCount", 212: "InstantSequentialAttackDamageRatio", 213: "BarrierImmuneDamage"}
TIMING_TRIGGER_TYPE = {-1: "Unknown", 0: "None", 1: "OnStart", 2: "OnShotRatio", 3: "OnUseAmmo", 4: "OnUseBurstSkill", 5: "OnHitNumberOver", 6: "OnFullChargeShot", 7: "OnHurtRatio", 8: "OnHurtCount", 9: "OnFunctionBuffCheck", 10: "OnFunctionDebuffCheck", 11: "OnSquadHurtRatio", 12: "OnSquadHurtCount", 13: "OnCoverHurtRatio", 14: "OnCoverHurtCount", 15: "OnHpRatioUnder", 16: "OnHpRatioUp", 17: "OnAmmoRatioUnder", 18: "OnAmmoRatioUp", 19: "OnShooterCount", 20: "OnKillRatio", 21: "OnFunctionOn", 22: "OnEnterBurstStep", 23: "OnFullCount", 24: "OnCoverDestroyRatio", 25: "OnBurstSkillStep", 26: "OnSpawnMonster", 27: "OnFullChargeHit", 28: "OnAttackRatio", 29: "OnLastShotHit", 30: "OnSkillUse", 31: "OnHitNum", 32: "OnFullBurstTimeOverRatio", 33: "OnPartsHitNum", 34: "OnPartsHitRatio", 35: "OnPartsHitNumOnce", 36: "OnPartsHitRatioOnce", 37: "OnLastAmmoUse", 38: "OnSpawnTarget", 39: "OnHitRatio", 40: "OnDead", 41: "OnTeamHpRatioUnder", 42: "OnResurrection", 43: "OnEndFullBurst", 44: "OnNikkeDead", 45: "OnCriticalHitNum", 46: "OnCriticalHitRatio", 47: "OnCriticalHitNumOnce", 48: "OnCriticalHitRatioOnce", 49: "OnHealedBy", 50: "OnMonsterDead", 51: "OnFullCharge", 52: "OnInstallBarrier", 53: "OnHealCover", 54: "OnInstantDeath", 55: "OnCoreHitRatioOnce", 56: "OnCoreHitNumOnce", 57: "OnCoreHitRatio", 58: "OnCoreHitNum", 59: "OnFullChargeNum", 60: "OnFullChargeShotNum", 61: "OnFullChargeHitNum", 62: "OnSummonMonster", 63: "OnAfterTimeSec", 64: "OnPelletHitNum", 65: "OnPelletHitPerShot", 66: "OnPartsBrokenNum", 67: "OnCheckTime", 68: "OnPartsHurtCount", 69: "OnPartsHurtRatio", 70: "OnUserPartsDestroy", 71: "OnEnemyDead", 72: "OnBurstSkillUseNum", 73: "OnFullChargePartsHitNum", 74: "OnKeepFullcharge", 75: "OnEndReload", 76: "OnTeamHpRatioUp", 77: "OnHurtDecoyNum", 78: "OnFunctionOff", 79: "OnHitNumExceptCore", 80: "OnShotNotFullCharge", 81: "OnKeepFullChargeShotUnder", 82: "OnSpawnEnemy", 83: "OnUseTeamAmmo", 84: "OnPelletCriticalHitNum", 85: "OnSpawnMonsterExcludeNoneType", 86: "OnFunctionDamageCriticalHit", 87: "OnFullChargeBonusRangeHitNum", 88: "OnKeepFullChargeShot", 89: "OnDeadComplete", 90: "OnFullChargeCoreHitNum"}
STATUS_TRIGGER_TYPE = {-1: "Unknown", 0: "None", 1: "IsAmmoRatioUnder", 2: "IsAmmoRatioUp", 3: "IsAmmoCount", 4: "IsAmmoCountUnder", 5: "IsAmmoCountUp", 6: "IsShooterCount", 7: "IsShooterUnder", 8: "IsShooterUp", 9: "IsSameSqaudCount", 10: "IsSameSqaudUnder", 11: "IsSameSqaudUp", 12: "IsHpRatioUnder", 13: "IsHpRatioUp", 14: "IsStun", 15: "IsFunctionBuffCheck", 16: "IsFunctionDebuffCheck", 17: "IsForcedStop", 18: "IsFunctionOn", 19: "IsFullCount", 20: "IsFunctionCount", 21: "IsBurstStepState", 22: "AlwaysRecursive", 23: "IsUseAmmo", 24: "IsPhase", 25: "IsPhaseUp", 26: "IsPhaseUnder", 27: "IsBurstSkillStep", 28: "IsCheckMonster", 29: "IsCover", 30: "IsSearchElementId", 31: "IsWeaponType", 32: "IsClassType", 33: "IsCheckTarget", 34: "IsCheckDebuff", 35: "IsHaveDecoy", 36: "IsFullCharge", 37: "IsHaveBarrier", 38: "IsBurstMember", 39: "IsNotBurstMember", 40: "IsHighHpValue", 41: "IsNotHaveBarrier", 42: "IsExplosiveCircuitOff", 43: "IsAlive", 44: "IsHighMaxHpValue", 45: "IsFunctionOff", 46: "IsCheckFunctionOverlapUp", 47: "IsCheckPartsId", 48: "IsCheckPosition", 49: "IsCheckMonsterType", 50: "IsCheckTeamBurstNextStep", 51: "IsNotCheckTeamBurstNextStep", 52: "IsCharacter", 53: "IsFunctionTypeOffCheck", 54: "IsCheckEnemyNikke", 55: "IsBurstStepCheck", 56: "IsCheckMonsterExcludeNoneType", 57: "IsNotHaveCover", 58: "IsHaveCover", 59: "IsSameSqaud", 60: "IsCheckGradeUnder", 61: "IsCheckCharacter", 62: "IsCheckNotTarget", 63: "IsCheckFunctionOverlap", 64: "IsFirstBurstMember", 65: "IsNotFirstBurstMember", 66: "IsCharging"}
STANDARD_TYPE = {-1: "Unknown", 0: "None", 1: "User", 2: "FunctionTarget", 3: "TriggerTarget"}
FUNCTION_TARGET_TYPE = {-1: "Unknown", 0: "None", 1: "Self", 2: "AllCharacter", 3: "AllMonster", 4: "Target", 5: "UserCover", 6: "TargetCover", 7: "AllCharacterCover"}
DURATION_TYPE = {-1: "Unknown", 0: "None", 1: "TimeSec", 2: "Shots", 3: "Battles", 4: "Hits", 5: "SkillShots", 6: "TimeSecBattles", 7: "OnStun", 8: "OnRemoveFunction", 9: "Hits_Ver2", 10: "TimeSec_Ver2", 11: "TimeSec_Ver3", 12: "ReloadAllAmmoCount", 13: "UncoverableCount", 14: "ChangeWeaponUseCount"}
VALUE_TYPE = {-1: "Unknown", 0: "None", 1: "Integer", 2: "Percent"}
BUFF_TYPE = {-1: "Unknown", 0: "Buff", 1: "DeBuff", 2: "Etc", 3: "BuffEtc", 4: "DebuffEtc"}
SKILL_TABLE_TYPE = {-1: "Unknown", 0: "None", 1: "StateEffect", 2: "CharacterSkill"}  # NikkeCharacterData.skill1/2_table

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
              "MonsterStatEnhanceTable.mpk": "MonsterStatEnhanceData",
              "MonsterModelTable.mpk": "MonsterModelData",
              "MonsterSkillTable.mpk": "MonsterSkillData",
              # 스킬 계층 (2026-07-08 D1): 니케 링크 → 스킬 → function 원자
              "CharacterTable.mpk": "NikkeCharacterData",
              "CharacterSkillTable.mpk": "SkillData",
              "StateEffectTable.mpk": "StateEffectData",
              "SkillInfoTable.mpk": "SkillInfoData",
              "FunctionTable.mpk": "FunctionData"}
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
