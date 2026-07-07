"""로컬 게임설치의 `sd.bin` → StaticData 부트스트랩 JSON 5표 추출.

발견 (2026-07-07, C:\\NIKKE 전수조사): 게임은 StaticData 대부분을 서버 .mpk 팩
(getFromNikkeStaticData.py)으로 받지만, 다운로드 前 필요한 **5개 표**는 클라 설치에
`nikke_Data/StreamingAssets/sd.bin` (ZIP, deflate) 안에 **평문 JSON**으로 동봉한다.
포맷 = `{ "version": ..., "records": [ {필드:값}, ... ] }` — 필드명·타입 self-describing
(il2cpp 타입 불필요!). 서버 .mpk 는 같은 데이터의 packed 바이너리.

동봉 5표:
  CampaignChapterTable   (43)   월드/챕터
  CampaignStageTable     (3825) 스테이지→field_monster_id·monster_stage_lv (보스 129 스테이지)
  CharacterReactionTable (2671) 로비 리액션(전투 무관)
  ConfigBattleTable      (139)  ⭐ 전역 전투상수 KV (core_damge_rate/BonusRangeRate/ulti_gauge_*)
  ConfigGameTable        (257)  전역 게임설정 KV

sd.bin 은 클라 **업데이트마다 갱신**. 나머지 표는 서버 .mpk 또는 암호화 dp 번들.

⚖️ sd.bin JSON = 게임 데이터 → 원본값 **커밋금지**(gitignore Database/raw/staticdata/).
이 스크립트만 커밋. ConfigBattle 등 필요상수는 파생 산출로 신중히 반영.

사용: python getFromLocalSdBin.py [sd.bin경로] [out_dir]
  기본 in  = C:\\NIKKE\\NIKKE\\game\\nikke_Data\\StreamingAssets\\sd.bin
  기본 out = ../../Database/raw/staticdata/sd_bin_json
"""
import json
import os
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 이모지 대응
except Exception:
    pass

DEFAULT_SD = r"C:\NIKKE\NIKKE\game\nikke_Data\StreamingAssets\sd.bin"
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(_HERE, "..", "..", "Database", "raw", "staticdata", "sd_bin_json"))


def extract(sd_path, out_dir):
    if not os.path.isfile(sd_path):
        sys.exit(f"❌ sd.bin 없음: {sd_path}  (게임 설치 경로 확인)")
    os.makedirs(out_dir, exist_ok=True)
    z = zipfile.ZipFile(sd_path)
    tables = {}
    for name in z.namelist():
        raw = z.read(name)
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(raw)
        try:
            d = json.loads(raw)
            recs = d.get("records", d) if isinstance(d, dict) else d
            tables[name] = len(recs) if isinstance(recs, list) else "?"
        except Exception:
            tables[name] = "(non-json)"
    print(f"✅ sd.bin → {len(tables)}표 추출 → {out_dir}")
    for n, c in sorted(tables.items()):
        print(f"   {n:<28} {c}행")

    # ConfigBattle/ConfigGame = {id,value} → 편의용 flat KV 도 저장
    for cfg in ("ConfigBattleTable", "ConfigGameTable"):
        p = os.path.join(out_dir, cfg + ".json")
        if not os.path.isfile(p):
            continue
        recs = json.load(open(p, encoding="utf-8"))["records"]
        kv = {r["id"]: r["value"] for r in recs}
        json.dump(kv, open(os.path.join(out_dir, cfg + "_kv.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"   ↳ {cfg}_kv.json ({len(kv)} 상수)")


if __name__ == "__main__":
    sd = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SD
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    extract(sd, out)
