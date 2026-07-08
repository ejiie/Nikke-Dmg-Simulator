"""D3 — 니케/보스 skill→function 체인 조립 (K4 공식 스킬 로더의 입력).

입력 = memorypack_decode.py 산출 mpk/*.json (Function/CharacterSkill/StateEffect/SkillInfo/Character/Monster)
     + blabla_roledata.json (로스터 name_code 범위).
출력 = Database/raw/staticdata/assembled/skill_chains.json  ⚖️ gitignore (게임데이터 재배포 금지 —
     사용자 결정 2026-07-08: GitHub=gitignore 준수, 로컬 생성).

구조:
  characters[name_code].{skill1,skill2,burst}.levels[1..10] = {skill_id, function_ids[]}  (+CharacterSkill 이면 skill 요약)
  bosses[monster_id] = {passive(StateEffect 체인), skills[].{skill_id, use/hurt function_ids}}   (solo raid = statenhance 230000)
  functions[fid] = FunctionData (Fx/아이콘 등 시각 필드 제거 + enum 이름 주석) — connected_function BFS 포함
  state_effects[id] = use/hurt/functions id 목록

단위: function_value 등 = raw(×10000=100%). 시간류 = 1/100초 (einkk timeDataToFrame(t)=t×fps/100 검증).
스킬 레벨: lv k 레코드 id = base_id + (k-1)  (SkillInfo/CharacterSkill/StateEffect 공통, 검증 2026-07-08).
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from memorypack_decode import (
    FUNCTION_TYPE, TIMING_TRIGGER_TYPE, STATUS_TRIGGER_TYPE, STANDARD_TYPE,
    FUNCTION_TARGET_TYPE, DURATION_TYPE, VALUE_TYPE, BUFF_TYPE, SKILL_TABLE_TYPE,
)

CUR = os.path.dirname(os.path.abspath(__file__))
MPK_DIR = os.path.join(CUR, "..", "..", "Database", "raw", "staticdata", "mpk")
ROLEDATA = os.path.join(CUR, "..", "..", "Database", "raw", "blabla_roledata.json")
OUT = os.path.join(CUR, "..", "..", "Database", "raw", "staticdata", "assembled", "skill_chains.json")

MAX_SKILL_LV = 10
SOLO_RAID_STATENHANCE = 230000  # RAID_BOSS.md: solo raid 변종 공유 stat group

# FunctionData 에서 시뮬 무관(시각효과/아이콘/텍스트) 필드 — 조립본에서 제거
_FX_FIELDS = {
    "description_localkey", "buff_icon", "element_reaction_icon", "shot_fx_list_type",
} | {f"fx_prefab_{s}" for s in ("01", "02", "03", "full", "01_arena", "02_arena", "03_arena")} \
  | {f"fx_target_{s}" for s in ("01", "02", "03", "full", "01_arena", "02_arena", "03_arena")} \
  | {f"fx_socket_point_{s}" for s in ("01", "02", "03", "full", "01_arena", "02_arena", "03_arena")}


def _load(name):
    with open(os.path.join(MPK_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def _trim_function(f):
    """시각 필드 제거 + enum 이름 주석 추가 (원본 int 값은 유지 — K4 는 int 소비)."""
    out = {k: v for k, v in f.items() if k not in _FX_FIELDS}
    out["function_type_name"] = FUNCTION_TYPE.get(f["function_type"], f"?{f['function_type']}")
    out["timing_trigger_name"] = TIMING_TRIGGER_TYPE.get(f["timing_trigger_type"], f"?{f['timing_trigger_type']}")
    out["status_trigger_name"] = STATUS_TRIGGER_TYPE.get(f["status_trigger_type"], f"?{f['status_trigger_type']}")
    out["function_target_name"] = FUNCTION_TARGET_TYPE.get(f["function_target"], f"?{f['function_target']}")
    out["standard_name"] = STANDARD_TYPE.get(f["function_standard"], f"?{f['function_standard']}")
    out["duration_type_name"] = DURATION_TYPE.get(f["duration_type"], f"?{f['duration_type']}")
    out["value_type_name"] = VALUE_TYPE.get(f["function_value_type"], f"?{f['function_value_type']}")
    out["buff_name"] = BUFF_TYPE.get(f["buff"], f"?{f['buff']}")
    return out


def main():
    ft = {f["id"]: f for f in _load("FunctionTable") if f.get("id")}
    cs = {s["id"]: s for s in _load("CharacterSkillTable") if s.get("id")}
    se = {s["id"]: s for s in _load("StateEffectTable") if s.get("id")}
    ch_all = _load("CharacterTable")
    mon = _load("MonsterTable")
    with open(ROLEDATA, encoding="utf-8") as f:
        roster_codes = {int(nc) for nc in json.load(f)["roster"]}

    used_fids = set()
    used_seids = set()

    def collect_functions(fids):
        """connected_function BFS 로 실사용 함수 수집."""
        stack = [fid for fid in fids if fid]
        out = []
        while stack:
            fid = stack.pop()
            if fid in used_fids or fid not in ft:
                continue
            used_fids.add(fid)
            out.append(fid)
            stack.extend(c for c in ft[fid].get("connected_function") or [] if c)
        return out

    def state_effect_chain(seid):
        """StateEffect id → function id 목록 (use/hurt/functions 전부)."""
        s = se.get(seid)
        if not s:
            return None
        used_seids.add(seid)
        fids = [x for x in (s.get("use_function_id_list") or []) if x]
        fids += [x for x in (s.get("hurt_function_id_list") or []) if x]
        fids += [x["function"] for x in (s.get("functions") or []) if x and x.get("function")]
        collect_functions(fids)
        return fids

    def skill_levels(base_id, table_type):
        """레벨 1..10 체인. table_type: 1=StateEffect, 2=CharacterSkill."""
        levels = {}
        for lv in range(1, MAX_SKILL_LV + 1):
            sid = base_id + (lv - 1)
            if table_type == 1:
                fids = state_effect_chain(sid)
                if fids is None:
                    continue
                levels[lv] = {"skill_id": sid, "function_ids": fids}
            else:
                s = cs.get(sid)
                if s is None:
                    continue
                fids = []
                for lst in ("before_use_function_id_list", "before_hurt_function_id_list",
                            "after_use_function_id_list", "after_hurt_function_id_list"):
                    fids += [x for x in (s.get(lst) or []) if x]
                collect_functions(fids)
                levels[lv] = {
                    "skill_id": sid,
                    "function_ids": fids,
                    # CharacterSkill 본체 수치 (skill_value_data = 계수/시간/교체 shot_id 등)
                    "skill": {k: s[k] for k in (
                        "skill_type", "skill_cooltime", "duration_type", "duration_value",
                        "skill_value_data", "attack_type", "prefer_target", "prefer_target_condition",
                        "resource_name") if k in s},
                }
        return levels

    # ── 니케 (roledata 로스터 범위, 최고 grade 레코드) ──
    best = {}
    for c in ch_all:
        nc = c.get("name_code")
        if nc in roster_codes and (nc not in best or c["id"] > best[nc]["id"]):
            best[nc] = c
    characters = {}
    for nc, c in sorted(best.items()):
        entry = {"char_id": c["id"], "name_localkey": c["name_localkey"], "element_id": c["element_id"],
                 "shot_id": c["shot_id"], "use_burst_skill": c["use_burst_skill"],
                 "burst_duration": c["burst_duration"], "skills": {}}
        for slot, id_key, tbl_key in (("skill1", "skill1_id", "skill1_table"),
                                      ("skill2", "skill2_id", "skill2_table")):
            base, tbl = c[id_key], c[tbl_key]
            entry["skills"][slot] = {
                "table": SKILL_TABLE_TYPE.get(tbl, str(tbl)), "base_id": base,
                "levels": skill_levels(base, tbl),
            }
        # 버스트(ulti) = CharacterSkillTable 고정 (einkk: "probably default to CharacterSkillTable")
        entry["skills"]["burst"] = {
            "table": "CharacterSkill", "base_id": c["ulti_skill_id"],
            "levels": skill_levels(c["ulti_skill_id"], 2),
        }
        characters[nc] = entry

    # ── 보스 (solo raid 변종 = statenhance 230000) ──
    bosses = {}
    for m in mon:
        if m.get("statenhance_id") != SOLO_RAID_STATENHANCE:
            continue
        passive_fids = state_effect_chain(m["passive_skill_id"]) if m.get("passive_skill_id") else None
        skills = []
        for sd in m.get("skill_data") or []:
            use = [x for x in (sd.get("use_function_id_skill") or []) if x]
            hurt = [x for x in (sd.get("hurt_function_id_skill") or []) if x]
            collect_functions(use + hurt)
            skills.append({"skill_id": sd.get("skill_id"), "use_function_ids": use, "hurt_function_ids": hurt})
        bosses[m["id"]] = {
            "name_localkey": m.get("name_localkey"), "element_id": m.get("element_id"),
            "model_id": m.get("monster_model_id"),
            "passive_skill_id": m.get("passive_skill_id"), "passive_function_ids": passive_fids,
            "skills": skills,  # skill_id 수치 자체 = MonsterSkillTable(미디코드) — function 체인만
        }

    out = {
        "_source": "StaticData qa-260702 (memorypack_decode.py) — FUNCTIONTABLE_DECODE_PLAN.md §0",
        "_units": "function_value/status_trigger_value: raw ×10000=100% · 시간류: 1/100초 (einkk t×fps/100 검증) · duration_value: duration_type 참조",
        "_policy": "gitignore — 게임데이터 재배포 금지 (사용자 2026-07-08). 로컬 재생성 = memorypack_decode.py → 이 스크립트.",
        "characters": characters,
        "bosses": bosses,
        "state_effects": {sid: {k: se[sid][k] for k in ("use_function_id_list", "hurt_function_id_list", "functions")}
                          for sid in sorted(used_seids)},
        "functions": {fid: _trim_function(ft[fid]) for fid in sorted(used_fids)},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    n_lv = sum(len(s["levels"]) for c in characters.values() for s in c["skills"].values())
    print(f"✅ characters {len(characters)} (skill-levels {n_lv}) · bosses {len(bosses)} "
          f"· functions {len(used_fids)} · state_effects {len(used_seids)} → {OUT}")


if __name__ == "__main__":
    main()
