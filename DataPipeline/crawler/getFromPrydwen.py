import asyncio
import httpx
import json
import os

# ── 가키짱의 무자비한 심연 탐색기 (DFS 알고리즘) ──
def find_nikke_core(node):
    if isinstance(node, dict):
        keys = node.keys()
        
        # 1. 니케 데이터의 핵심 키워드들이 한 방에 모여있는 객체를 찾는다!
        # 프리드웬 데이터마이닝의 흔한 키워드 조합망을 다 던져두는 거야♥
        if ("burstType" in keys and "manufacturer" in keys) or \
           ("weapon" in keys and "rarity" in keys) or \
           ("skills" in keys and "name" in keys) or \
           ("skill1" in keys and "class" in keys):
            return node
        
        # 2. 이 폴더에 없으면? 하위 폴더(v)로 더 깊이 파고든다! (재귀 호출)
        for k, v in node.items():
            res = find_nikke_core(v)
            if res: return res  # 찾았으면 더 안 찾고 바로 끌고 올라옴!
            
    elif isinstance(node, list):
        # 배열 안에 숨겨둔 경우도 모조리 뒤진다!
        for item in node:
            res = find_nikke_core(item)
            if res: return res
            
    return None # 끝까지 뒤졌는데 없으면 빈손으로 리턴

async def fetch_detail(client, slug):
    url = f"https://www.prydwen.gg/page-data/nikke/characters/{slug}/page-data.json"
    try:
        # 도망가지 못하게 리다이렉트 추적(follow_redirects) 옵션 유지!
        res = await client.get(url, timeout=15.0, follow_redirects=True)
        res.raise_for_status()
        return slug, res.json()
    except Exception as e:
        print(f"❌ {slug} 타격 실패: {e}")
        return slug, None

async def precision_strike_v3():
    print("🕵️‍♀️ 가키짱의 3차 정밀 폭격기 (무한-Depth DFS 스캐너 탑재) 기동...")

    if not os.path.exists("prydwen_main_characters.json"):
        print("❌ 야! prydwen_main_characters.json 어딨어! 파일부터 구해와!")
        return

    with open("prydwen_main_characters.json", "r", encoding="utf-8") as f:
        main_data = json.load(f)

    # 메인 리스트의 slug도 DFS로 완벽하게 찾아낸다♥
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
        print("❌ 타겟 리스트를 못 찾았어! 1차 파일이 망가진 거 아냐?")
        return
        
    print(f"🎯 총 {len(slugs)}명의 타겟 확인! (예: {slugs[0]}, {slugs[1]}...) 융단폭격 개시!")

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
                    # ── [핵심] 1-Depth 검색을 버리고 무한-Depth (DFS) 검색을 쓴다! ──
                    character_info = find_nikke_core(data)
                    
                    if character_info:
                        all_details[slug] = character_info
                    else:
                        print(f"⚠️ {slug}: 지하 끝까지 뒤졌는데도 핵심 스탯이 안 보여!")
            
            print(f"   ⚡ {min(i + len(chunk), len(slugs))}/{len(slugs)}명 타격 완료...")
            await asyncio.sleep(0.5)

    with open("prydwen_all_details_v3.json", "w", encoding="utf-8") as f:
        json.dump(all_details, f, ensure_ascii=False, indent=2)

    print(f"\n✅ [완벽] 총 {len(all_details)}명의 심연 데이터 싹쓸이 완료!")
    if len(all_details) > 0:
        print("💾 'prydwen_all_details_v3.json' 까보고 내 완벽함에 전율이나 해, 바보야♥")

if __name__ == "__main__":
    asyncio.run(precision_strike_v3())