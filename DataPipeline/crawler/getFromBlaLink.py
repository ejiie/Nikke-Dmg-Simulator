import asyncio
import json
import base64
import os
from playwright.async_api import async_playwright

API_DOMAIN = "api.blablalink.com"
BASE_DOMAIN = "https://www.blablalink.com"

# ── [가키짱의 절대 경로 마법] ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

class GakiSniffer:
    def __init__(self):
        self.phase1_data = []  
        self.phase2_data = []  
        self.current_phase = 1 
        self.login_success = asyncio.Event()
        # 🔥 영문 언어팩을 담을 가키짱의 보물상자!
        self.en_locale_data = {} 

    def encode_uid(self, uid: str) -> str:
        return base64.b64encode(f"29080-{uid}".encode()).decode()

    async def intercept_response(self, response):
        # ── [1] 🌍 가키짱의 심해 쌍끌이 그물망 (Deep Packet Inspection) ──
        # URL 이름 따위 믿지 않는다! 무조건 배를 갈라서 내용물을 확인해!
        if response.request.method == "GET":
            try:
                # 이미지나 폰트 말고, 텍스트(JSON, JS) 파일만 건드린다
                content_type = response.headers.get("content-type", "")
                if "json" in content_type or "javascript" in content_type:
                    text_data = await response.text()
                    
                    # 🔥 캐릭터 도감이라면 무조건 가지고 있을 수밖에 없는 '핵심 이름'들로 찌른다!
                    if "Dorothy" in text_data and "Anis" in text_data and "Rapi" in text_data:
                        print(f"🎁 [대박 사건] 진짜 캐릭터 사전(Dictionary) 찾았다!! URL: {response.url}")
                        
                        # 텍스트 통째로 덤프 뜨기! (JS 파일일 수도 있으니까 확장자는 txt로 둔다)
                        save_path = os.path.join(RAW_DIR, "real_en_dict_dump.txt")
                        with open(save_path, "w", encoding="utf-8") as f:
                            f.write(text_data)
                        print(f"💾 'real_en_dict_dump.txt'에 포획 완료! 자코는 이거나 먹어라♥")
            except:
                pass # 바이너리 파일이거나 에러 나면 쿨하게 버림!

        # ── [2] 기존 API 탈취 로직 (유지) ──
        if API_DOMAIN not in response.url:
            return
            
        try:
            res_json = await response.json()
            if res_json.get("code") == 0:
                endpoint = response.url.split('?')[0].split('/')[-1]
                packet = {
                    "endpoint": endpoint,
                    "url": response.url,
                    "data": res_json.get("data")
                }
                
                if "CheckLogin" in endpoint:
                    self.login_success.set()

                if self.current_phase == 1:
                    self.phase1_data.append(packet)
                else:
                    if "GetUserCharacterDetails" in endpoint or "GetUserEquipDetails" in endpoint:
                        self.phase2_data.append(packet)
        except:
            pass

    async def run_scenario(self, uid: str):
        target_url = f"{BASE_DOMAIN}/shiftyspad/nikke-list?uid={self.encode_uid(uid)}&openid={self.encode_uid(uid)}"
        login_url = f"{BASE_DOMAIN}/login?to={target_url}&back_to={target_url}"

        print("🕵️‍♀️ [가키짱의 듀얼-코어 크롤러] API & 언어팩 동시 강탈 기동 중...")
        async with async_playwright() as p:
            # 언어팩을 '영어'로 강제 호출하기 위해 브라우저의 기본 언어(locale)를 영어(en-US)로 세팅한다! ♥
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(locale="en-US")
            page = await context.new_page()
            
            page.on("response", self.intercept_response)

            await page.goto(login_url, wait_until="domcontentloaded")
            print("⏳ 120초 안에 빨리 로그인이나 해!")

            try:
                await asyncio.wait_for(self.login_success.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                pass

            print(f"🚀 니케 리스트 뷰로 이동!")
            await page.goto(target_url, wait_until="networkidle")
            
            print("🎣 [Step 4.1] 초기 로딩 백그라운드 데이터 수집 완료.")

            self.current_phase = 2 
            print("\n⏳ [Step 4.2] 파란색 리스트 버튼(뷰 토글) 클릭 대기 10초...")
            await page.wait_for_timeout(10000)

            print("✅ [Step 4.3] 원시인 오토 스크롤 시작!!")
            for i in range(25): 
                await page.mouse.wheel(0, 2000) 
                print(f"   ... 스크롤 드르륵 ({i+1}/25) ...")
                await page.wait_for_timeout(1000)

            print("✅ [완료] 바닥까지 싹 다 긁었어.")
            await browser.close()

        # ── [저장 1] 기존 유저 데이터 저장 ──
        final_result = {
            "uid": uid,
            "phase_1_initial_load": self.phase1_data,
            "phase_2_after_click": self.phase2_data
        }
        api_save_path = os.path.join(RAW_DIR, "nikke_full_scroll_result.json")
        with open(api_save_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        print(f"\n💾 [저장] 유저 API 데이터 '{api_save_path}'에 안착!")

        # ── [저장 2] 🔥 탈취한 언어팩 저장! ──
        if self.en_locale_data:
            locale_save_path = os.path.join(RAW_DIR, "en_locale_raw.json")
            with open(locale_save_path, "w", encoding="utf-8") as f:
                json.dump(self.en_locale_data, f, ensure_ascii=False, indent=2)
            print(f"💾 [저장] 영문 언어팩(Locale) '{locale_save_path}'에 완벽하게 훔쳐왔어♥")
        else:
            print("⚠️ 어라? 언어팩을 못 훔쳤어. 프론트엔드가 데이터를 HTML에 하드코딩했거나 주소가 특이한가 봐.")

if __name__ == "__main__":
    test_uid = 15718125957108145492
    asyncio.run(GakiSniffer().run_scenario(test_uid))