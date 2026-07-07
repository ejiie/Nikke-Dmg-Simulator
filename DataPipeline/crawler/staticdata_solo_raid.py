"""Solo Raid 보스 종합 (MemoryPack 완전 디코드 기반) → solo_raid_boss.{json,md}.

전제: `memorypack_decode.py` 로 MonsterParts/MonsterTable/MonsterStatEnhance 를 clean 디코드
(mpk/*.json) + `staticdata_raid_decode.py` 로 SoloRaidPreset/Manager/MonsterModel 디코드(raid/*.json).

체인: SoloRaidManager(Ranking=시즌)→SoloRaidPreset(코드·Lv)→MonsterModel(Mon_prefab)→model_id
      →MonsterTable(statenhance=230000 변종=solo raid: element/skills) →MonsterStatEnhance[230000][Lv]
      →MonsterParts[model](파츠·코어).

코어 판정 (ground truth 검증: s37 파츠·무한 / s38 몸통 / s9·s22 파츠·재생):
  코어 = weapon_object/parts_object 에 core collider(core_col/core_bone/socket_core) 가진 파츠.
  - **파츠판정**: is_main=False 별도 파츠. hp_ratio=0=무한 / >0=유한(passive_skill_id≠0 면 재생).
  - **몸통판정(메인부착)**: is_main=True 메인바디에 코어 collider(바디HP). (s39)
  - **몸통판정(암묵)**: 코어 collider 파츠 없음. 코어=바디 기본 약점(prefab). (s38)

⚖️ 복호값=gitignore. 스크립트만 커밋. 사용: python staticdata_solo_raid.py
"""
import json
import os
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Database", "raw", "staticdata"))
RAID = os.path.join(BASE, "raid")
MPK = os.path.join(BASE, "mpk")
SOLO_GROUP = 230000  # solo raid 공유 stat group (사용자 확정, 커뮤 datamine 일치)
ELEM = {100001: "Fire", 200001: "Water", 300001: "Wind", 400001: "Electric", 500001: "Iron"}
PARTS_TYPE = {-1: "Unknown", 0: "None", 1: "Arm_L", 2: "Arm_R", 3: "Head", 4: "Body_Lower", 5: "Body_Upper",
              6: "Body", 7: "Chest", 8: "Belly", 9: "Leg_FL", 10: "Leg_FR", 11: "Leg_BL", 12: "Leg_BR",
              13: "Weapon_01", 14: "Weapon_02", 15: "Weapon_03", 16: "Weapon_04", 17: "Weapon_05",
              18: "Weapon_06", 19: "Weapon_07", 20: "Weapon_08", 21: "Weapon_09", 22: "Weapon_10"}


def load(path):
    return json.load(open(path, encoding="utf-8"))


def core_colliders(part):
    # 코어 지시자는 weapon_object/parts_object(collider) 또는 parts_skin(예 bba001_core_skin)에 등장
    ss = (part.get("weapon_object") or []) + (part.get("parts_object") or [])
    if part.get("parts_skin"):
        ss = ss + [part["parts_skin"]]
    return [s for s in ss if s and "core" in str(s).lower()]


def classify(parts):
    core_parts = [p for p in parts if core_colliders(p)]
    if not core_parts:
        return "몸통판정(암묵; 코어=바디 기본약점)", []
    info = []
    kind = None
    for cp in core_parts:
        hp = cp["hp_ratio"]; pas = cp["passive_skill_id"]
        # hp_ratio: 0=무한 / >=100000=초고HP(사실상무한) / else 유한. 재생여부=passive 스킬 heal function(FunctionTable) 확인필요.
        if hp == 0:
            beh = "무한(hp_ratio=0)"
        elif hp >= 100000:
            beh = f"초고HP({hp}=사실상무한)"
        else:
            beh = f"유한(hp_ratio={hp})"
        if pas:
            beh += f" +passive{pas}"
        info.append({"part_id": cp["id"], "parts_type": PARTS_TYPE.get(cp["parts_type"], cp["parts_type"]),
                     "is_main": cp["is_main_part"], "hp_ratio": hp, "damage_hp_ratio": cp["damage_hp_ratio"],
                     "is_damageable": cp["is_parts_damage_able"], "passive_skill_id": pas,
                     "colliders": core_colliders(cp), "behavior": beh})
        if not cp["is_main_part"]:
            kind = "파츠판정"
        elif kind is None:
            kind = "몸통판정(메인바디 부착)"
    return kind, info


def main():
    mgr = load(os.path.join(RAID, "SoloRaidManagerTable.json"))
    preset = load(os.path.join(RAID, "SoloRaidPresetTable.json"))
    model = {m["Id"]: m for m in load(os.path.join(RAID, "MonsterModelTable.json"))}
    prefab2model = {}
    for m in model.values():
        prefab2model.setdefault(m["Mon_prefab"], m["Id"])
    monsters = load(os.path.join(MPK, "MonsterTable.json"))
    mon_by_model = defaultdict(list)
    for mo in monsters:
        mon_by_model[mo["monster_model_id"]].append(mo)
    parts_all = load(os.path.join(MPK, "MonsterPartsTable.json"))
    parts_by_model = defaultdict(list)
    for pa in parts_all:
        parts_by_model[pa["monster_model_id"]].append(pa)
    se = load(os.path.join(MPK, "MonsterStatEnhanceTable.json"))
    grp = defaultdict(dict)
    for r in se:
        grp[r["group_id"]][r["lv"]] = r

    season_of = {m["Monster_preset"]: m["Ranking_group_id"] for m in mgr}

    # boss per preset_group (dedup)
    bosses = {}
    for p in preset:
        pg = p["Preset_group_id"]
        code = p.get("Monster_image", "").replace("full_", "").replace("si_", "")
        if not code:
            continue
        b = bosses.get(pg)
        if b is None:
            mid = prefab2model.get(code)
            mons = mon_by_model.get(mid, [])
            # solo raid 변종 = statenhance 230000
            raidmon = next((m for m in mons if m["statenhance_id"] == SOLO_GROUP), mons[0] if mons else None)
            elem = raidmon["element_id"] if raidmon else []
            parts = parts_by_model.get(mid, [])
            kind, cinfo = classify(parts)
            b = bosses[pg] = {
                "season": season_of.get(pg), "preset_group": pg, "code": code,
                "wave_name": p.get("Wave_name"), "model_id": mid,
                "grade": model.get(mid, {}).get("Grade"), "class": model.get(mid, {}).get("Class"),
                "size": model.get(mid, {}).get("Size"),
                "element_ids": elem, "elements": [ELEM.get(e, e) for e in elem],
                "monster_id": raidmon["id"] if raidmon else None,
                "n_skills": len(raidmon["skill_data"]) if raidmon else 0,
                # 보스 스킬 = skill_id + 효과 function_id (FunctionTable 링크). MonsterTable.skill_data(clean).
                "skills": [{"skill_id": s["skill_id"], "use_function_ids": s["use_function_id_skill"],
                            "hurt_function_ids": s["hurt_function_id_skill"]}
                           for s in (raidmon["skill_data"] if raidmon else [])],
                "core_type": kind, "core_parts": cinfo,
                "n_parts": len(parts),
                "parts": [{"id": pa["id"], "type": PARTS_TYPE.get(pa["parts_type"], pa["parts_type"]),
                           "is_main": pa["is_main_part"], "damageable": pa["is_parts_damage_able"],
                           "hp_ratio": pa["hp_ratio"], "damage_hp_ratio": pa["damage_hp_ratio"],
                           "passive_skill_id": pa["passive_skill_id"], "visible_hp": pa["visible_hp"],
                           "core": core_colliders(pa)} for pa in parts],
                "levels": set(),
            }
        b["levels"].add(p.get("Monster_stage_lv"))

    for b in bosses.values():
        lvs = sorted(b["levels"]); b["levels"] = lvs
        b["stat_group"] = SOLO_GROUP
        b["stats"] = {str(lv): {k: grp[SOLO_GROUP][lv][k] for k in
                      ("level_hp", "level_attack", "level_defence", "level_broken_hp", "level_projectile_hp")}
                      for lv in lvs if lv in grp.get(SOLO_GROUP, {})}

    out = sorted(bosses.values(), key=lambda b: b["season"] or 0)
    json.dump(out, open(os.path.join(RAID, "solo_raid_boss.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = ["# Solo Raid 보스 종합 (MemoryPack 완전 디코드)\n",
             f"stat group = {SOLO_GROUP} (전 시즌 공유). 코어판정 ground truth 검증됨(s37/s38/s9/s22/s39).\n",
             "\n| S | code | element | grade | 코어판정 | 코어파츠 상세 | 파츠수 | lv | HP@390 | DEF@390 |",
             "|--|--|--|--|--|--|--|--|--|--|"]
    for b in out:
        hi = b["stats"].get("390", {})
        cd = "; ".join(f"{c['parts_type']}/{c['behavior']}" for c in b["core_parts"]) or "-"
        lines.append(f"| {b['season']} | {b['code']} | {'/'.join(map(str,b['elements']))} | {b['grade']} | "
                     f"{b['core_type']} | {cd} | {b['n_parts']} | {min(b['levels'])}~{max(b['levels'])} | "
                     f"{hi.get('level_hp',0):,} | {hi.get('level_defence',0):,} |")
    open(os.path.join(RAID, "solo_raid_boss.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"✅ {len(out)} solo raid 보스 → solo_raid_boss.{{json,md}}")
    from collections import Counter
    print("   코어판정:", dict(Counter(b["core_type"].split("(")[0] for b in out)))
    print(f"   경로: {os.path.join(RAID, 'solo_raid_boss.md')}")


if __name__ == "__main__":
    main()
