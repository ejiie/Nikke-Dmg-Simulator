import asyncio
import httpx
import json
import os
import sys

# 현재 스크립트(getFromPrydwen.py)가 있는 위치를 기준으로 Database/raw/ 경로를 강제로 찾아낸다!
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True) # 폴더가 없으면 알아서 만들어줌

# ── 종료 코드 (automation 이 성공/실패를 구분할 수 있게 명시) ──
EXIT_OK = 0
EXIT_NO_SLUGS = 10    # 메인 캐릭터 목록(slug)을 못 가져옴
EXIT_NO_DETAILS = 11  # slug 는 있었지만 상세 데이터를 하나도 못 긁음

# ── 탐색기 (DFS 알고리즘) ──
def find_nikke_core(node):
    if isinstance(node, dict):
        keys = node.keys()
        if ("burstType" in keys and "manufacturer" in keys) or \
           ("weapon" in keys and "rarity" in keys) or \
           ("skills" in keys and "name" in keys) or \
           ("skill1" in keys and "class" in keys):
            return node
        
        for k, v in node.items():
            res = find_nikke_core(v)
            if res: return res  
            
    elif isinstance(node, list):
        for item in node:
            res = find_nikke_core(item)
            if res: return res
            
    return None 

def find_nodes(node, target_key="nodes"):
    """JSON 구조 안에서 특정 key(nodes)를 가진 배열을 찾아 반환하는 DFS 함수"""
    if isinstance(node, dict):
        if target_key in node and isinstance(node[target_key], list):
            if len(node[target_key]) > 0 and "slug" in node[target_key][0]:
                return node[target_key]
        for k, v in node.items():
            res = find_nodes(v, target_key)
            if res: return res
    elif isinstance(node, list):
        for item in node:
            res = find_nodes(item, target_key)
            if res: return res
    return None

async def fetch_main_characters(client):
    """메인 페이지의 page-data.json에서 캐릭터 slug 목록을 가져오고 저장함"""
    url = "https://www.prydwen.gg/page-data/nikke/characters/page-data.json"
    print("🌐 메인 캐릭터 목록 가져오는 중...")
    try:
        res = await client.get(url, timeout=15.0)
        res.raise_for_status()
        main_data = res.json()
        
        # 받아온 원본 데이터를 먼저 저장 (기존 의존성 파일 백업 역할)
        main_file_path = os.path.join(RAW_DIR, "prydwen_main_characters.json")
        with open(main_file_path, "w", encoding="utf-8") as f:
            json.dump(main_data, f, ensure_ascii=False, indent=2)
        print(f"💾 원본 목록 파일 저장 완료: '{main_file_path}'")
        
        # nodes 탐색
        nodes = find_nodes(main_data)
        if not nodes:
            return []
            
        slugs = [n["slug"] for n in nodes if "slug" in n]
        return slugs
    except Exception as e:
        print(f"❌ 메인 목록 가져오기 실패: {e}")
        return []

async def fetch_detail(client, slug):
    url = f"https://www.prydwen.gg/page-data/nikke/characters/{slug}/page-data.json"
    try:
        res = await client.get(url, timeout=15.0, follow_redirects=True)
        res.raise_for_status()
        return slug, res.json()
    except Exception as e:
        print(f"❌ {slug} 타격 실패: {e}")
        return slug, None

async def precision_strike_v3():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        # 1단계: 메인 페이지에서 실시간으로 slug 리스트 따오기
        slugs = await fetch_main_characters(client)
        
        if not slugs:
            print("❌ 타겟 리스트(slugs)를 추출하지 못해 중단합니다.")
            return EXIT_NO_SLUGS

        print(f"🎯 총 {len(slugs)}명의 실시간 타겟 확인!")

        # 2단계: 추출한 slug를 바탕으로 상세 페이지 순회 개시
        all_details = {}
        chunk_size = 10
        for i in range(0, len(slugs), chunk_size):
            chunk = slugs[i:i + chunk_size]
            tasks = [fetch_detail(client, slug) for slug in chunk]
            results = await asyncio.gather(*tasks)
            
            for slug, data in results:
                if data:
                    character_info = find_nikke_core(data)
                    if character_info:
                        all_details[slug] = character_info
                    else:
                        print(f"{slug}: 핵심 스탯이 안 보여!")
            
            print(f"   ⚡ {min(i + len(chunk), len(slugs))}/{len(slugs)}명 타격 완료...")
            await asyncio.sleep(0.5)

    # 0건이면 직전 정상 산출물을 빈 파일로 덮어쓰지 않도록 저장을 건너뛰고 실패 반환.
    if not all_details:
        print("❌ 상세 데이터를 하나도 수집하지 못함 → 저장 생략, 실패 종료.")
        return EXIT_NO_DETAILS

    # 3단계: 최종 상세 데이터 저장
    save_path = os.path.join(RAW_DIR, "prydwen_all_details_v3.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(all_details, f, ensure_ascii=False, indent=2)

    print(f"\n✅ [완벽] 총 {len(all_details)}명의 데이터 fetch 완료!")
    print(f"'{save_path}'에 완벽하게 꽂아넣었어")
    return EXIT_OK

if __name__ == "__main__":
    sys.exit(asyncio.run(precision_strike_v3()))