import asyncio
import json
import base64
from playwright.async_api import async_playwright

API_DOMAIN = "api.blablalink.com"
BASE_DOMAIN = "https://www.blablalink.com"

class GakiSniffer:
    def __init__(self):
        self.phase1_data = []  
        self.phase2_data = []  
        self.current_phase = 1 
        self.login_success = asyncio.Event()

    def encode_uid(self, uid: str) -> str:
        return base64.b64encode(f"29080-{uid}".encode()).decode()

    async def intercept_response(self, response):
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
                    # GetUserCharacterDetails 패킷만 쏙쏙 골라 담기!
                    if "GetUserCharacterDetails" in endpoint:
                        self.phase2_data.append(packet)
                        print(f"🎁 [Phase 2] {endpoint} 추가 데이터 강탈 완료!")
        except:
            pass

    async def run_scenario(self, uid: str):
        target_url = f"{BASE_DOMAIN}/shiftyspad/nikke-list?uid={self.encode_uid(uid)}&openid={self.encode_uid(uid)}"
        login_url = f"{BASE_DOMAIN}/login?to={target_url}&back_to={target_url}"

        print("🕵️‍♀️ [원시인 자코 전용] 무식한 휠 스크롤 크롤러 기동...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
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

            print("✅ [Step 4.3] 원시인 오토 스크롤 시작!! 브라우저 멀미 주의해♥")
            
            # 니케가 178명이니까 한 화면에 10명씩 보인다고 치면 20번 정도 굴려야겠지?
            for i in range(25): 
                # y축으로 2000픽셀씩 무자비하게 휠을 내려버려!
                await page.mouse.wheel(0, 2000) 
                print(f"   ... 스크롤 드르륵 ({i+1}/25) ...")
                
                # 시프트업 서버가 API 응답을 줄 때까지 1초 대기 (네트워크 느리면 1.5초로 늘리던가!)
                await page.wait_for_timeout(1000)

            print("✅ [완료] 바닥까지 싹 다 긁었어. 더 이상 숨길 데이터는 없을걸?")
            await browser.close()

        final_result = {
            "uid": uid,
            "phase_1_initial_load": self.phase1_data,
            "phase_2_after_click": self.phase2_data
        }

        with open("nikke_full_scroll_result.json", "w", encoding="utf-8") as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)

        print("\n💾 [저장] nikke_full_scroll_result.json에 저장 완료!")

if __name__ == "__main__":
    test_uid = input("Blabla UID 입력해, 허접군: ").strip()
    asyncio.run(GakiSniffer().run_scenario(test_uid))