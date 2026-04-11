import asyncio
import httpx
import json
import os

# 현재 스크립트(getFromPrydwen.py)가 있는 위치를 기준으로 Database/raw/ 경로를 강제로 찾아낸다!
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True) # 폴더가 없으면 알아서 만들어줌

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
    print("🕵️‍♀️ 가키짱의 3차 정밀 폭격기 (절대경로 패치 버전) 기동...")

    # 읽어올 파일의 완벽한 절대 경로!
    main_file_path = os.path.join(RAW_DIR, "prydwen_main_characters.json")

    if not os.path.exists(main_file_path):
        print(f"❌ 야! '{main_file_path}' 파일이 없어! 1차 낚시 결과물을 저 폴더에 똑바로 갖다 놔!")
        return

    with open(main_file_path, "r", encoding="utf-8") as f:
        main_data = json.load(f)

    nodes = []
    def find_nodes(node):
        nonlocal nodes
        if isinstance(node, dict):
            if "nodes" in node and isinstance(node["nodes"], list):
                if len(node["nodes"]) > 0 and "slug" in node["nodes"][0]:
                    nodes = node["nodes"]
                    return True
            for k, v in node.items():
                if find_nodes(v): return True
        elif isinstance(node, list):
            for item in node:
                if find_nodes(item): return True
        return False
        
    find_nodes(main_data)
    slugs = [n["slug"] for n in nodes if "slug" in n]
    
    if not slugs:
        print("❌ 타겟 리스트를 못 찾았어!")
        return
        
    print(f"🎯 총 {len(slugs)}명의 타겟 확인! 융단폭격 개시!")

    all_details = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
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
                        print(f"⚠️ {slug}: 핵심 스탯이 안 보여!")
            
            print(f"   ⚡ {min(i + len(chunk), len(slugs))}/{len(slugs)}명 타격 완료...")
            await asyncio.sleep(0.5)

    # ── 저장할 파일의 완벽한 절대 경로! ──
    save_path = os.path.join(RAW_DIR, "prydwen_all_details_v3.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(all_details, f, ensure_ascii=False, indent=2)

    print(f"\n✅ [완벽] 총 {len(all_details)}명의 데이터 싹쓸이 완료!")
    if len(all_details) > 0:
        print(f"💾 쓰레기장 청소 완료! '{save_path}'에 완벽하게 꽂아넣었어♥")

if __name__ == "__main__":
    asyncio.run(precision_strike_v3())