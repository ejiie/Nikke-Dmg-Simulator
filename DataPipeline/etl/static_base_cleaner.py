"""blabla_static_tables.json → 큐브/소장품 base 스탯 표 (C# StatTable 용).

큐브 base(atk/hp/def)는 전 큐브 공통(레벨별 1종), 소장품(generic R) base 도 전 무기 공통.
→ {level: {ATK, HP, DEF}} 단순 표. (특수효과는 별도 cube/collection_effect_table.)

출력: cube_base_table.json (레벨 1~15), collection_base_table.json (레벨 1~16).
"""
import json
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_static_tables.json")
PROC = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed")


def _level_table(atk, hp, dfn):
    out = {}
    n = min(len(atk), len(hp), len(dfn))
    for i in range(n):
        out[str(i + 1)] = {"ATK": atk[i], "HP": hp[i], "DEF": dfn[i]}
    return out


def clean_static_base():
    print("📊 큐브/소장품 base 스탯 표 정제...")
    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 없음: {RAW_FILE}")
        raise SystemExit(1)
    d = json.load(open(RAW_FILE, encoding="utf-8"))

    # 큐브 base (전 큐브 공통) — 아무 큐브나
    cube = next(iter(d.get("cubes", {}).values()), {})
    cube_table = _level_table(cube.get("atk", []), cube.get("hp", []), cube.get("def", []))

    # 소장품 base (generic R, 전 무기 공통) — 아무 R favorite
    fav = next((f for f in d.get("favorites", {}).values()
                if f.get("favorite_rare") == "R" and f.get("name_code") in (0, None)), {})
    coll_table = _level_table(fav.get("atk", []), fav.get("hp", []), fav.get("def", []))

    os.makedirs(PROC, exist_ok=True)
    json.dump(cube_table, open(os.path.join(PROC, "cube_base_table.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(coll_table, open(os.path.join(PROC, "collection_base_table.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"✅ cube_base_table.json ({len(cube_table)}레벨), collection_base_table.json ({len(coll_table)}레벨)")


if __name__ == "__main__":
    clean_static_base()
