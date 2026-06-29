import argparse
import asyncio
import json
import base64
import os
import re
import sys
from playwright.async_api import async_playwright

import _secrets  # 같은 폴더의 자격증명 로더 (env / .env)

API_DOMAIN = "api.blablalink.com"
API_BASE = "https://api.blablalink.com"
BASE_DOMAIN = "https://www.blablalink.com"

# ── 종료 코드 (automation 이 성공/실패를 구분할 수 있게 명시) ──
# 0=성공 / 2=CLI 사용법 오류(argparse 가 자동 사용) / 10~ = 런타임 실패
EXIT_OK = 0
EXIT_LOGIN_TIMEOUT = 10   # 제출은 했지만 제한 시간 안에 CheckLogin 확인 안 됨
EXIT_NO_USER_DATA = 11    # 로그인은 됐지만 유저 데이터를 하나도 못 긁음
EXIT_INCOMPLETE = 12      # replay 디테일 수 < roster 수 (부분 수집) → 저장 생략
EXIT_LOGIN_FAIL = 13      # 로그인 단계 실패 (셀렉터 불일치·잘못된 계정·비밀정보 누락)

# ── [가키짱의 절대 경로 마법] ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True)


def _extract_json_payload(text):
    """응답 본문에서 첫 JSON 값(배열/객체)을 뽑아 파싱한다.

    사전 응답은 순수 JSON 이지만, JS 번들(`var X = [...];`)로 올 가능성도 있어
    앞뒤 래퍼를 견딘다. 실패하면 None.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # JS 래퍼가 감싼 경우: 첫 '[' 또는 '{' 부터 한 개의 JSON 값만 디코드
    decoder = json.JSONDecoder()
    for opener in ("[", "{"):
        idx = text.find(opener)
        if idx != -1:
            try:
                payload, _ = decoder.raw_decode(text[idx:])
                return payload
            except json.JSONDecodeError:
                continue
    return None


# probe 덤프에서 값을 그대로 남겨도 안전한 헤더(나머지는 redact). 키 이름은 전부 보존.
_SAFE_HEADER_VALUES = {
    "content-type", "accept", "accept-encoding", "accept-language",
    "x-language", "x-channel-type", "x-platform",
}


def _redact_headers(headers):
    """헤더 키는 전부 남기되(서명 헤더 존재 파악용), 민감 값은 마스킹한다."""
    out = {}
    for k, v in headers.items():
        out[k] = v if k.lower() in _SAFE_HEADER_VALUES else f"<redacted len={len(v)}>"
    return out


# replay 시 재사용하면 안 되는 헤더(쿠키는 context 가 자동, 길이/인코딩/host 는 클라가 재계산).
_DROP_REPLAY_HEADERS = {"cookie", "content-length", "host", "accept-encoding"}


def _clean_request_headers(headers):
    """live 요청 헤더에서 replay 에 그대로 쓸 수 있는 것만 남긴다(HTTP/2 pseudo-header 제거)."""
    return {k: v for k, v in headers.items()
            if not k.startswith(":") and k.lower() not in _DROP_REPLAY_HEADERS}


class GakiSniffer:
    def __init__(self):
        self.phase1_data = []  
        self.phase2_data = []  
        self.current_phase = 1
        self.login_success = asyncio.Event()
        # 🔥 영문 캐릭터 사전(name_code → 이름). 스니핑으로 1회 확보. None = 미확보.
        self.en_dict = None
        # probe 모드: GetUserCharacterDetails/Characters 의 요청 shape(method/header/body) 캡처
        self.probe = False
        self.probe_requests = []
        # replay: GetUserCharacters 에서 확보하는 roster + 요청 템플릿(헤더/공통 body)
        self.batch_size = 10
        self._roster_name_codes = []
        self._api_template = None   # {"intl_open_id","nikke_area_id","headers"}
        # CDN 디스커버리: sg-tools-cdn 의 정적 데이터 JSON(manifest/테이블) URL 수집
        self.discover_cdn = False
        self.cdn_dump = []

    def encode_uid(self, uid: str) -> str:
        return base64.b64encode(f"29080-{uid}".encode()).decode()

    async def intercept_response(self, response):
        # ── [0] CDN 디스커버리: sg-tools-cdn 정적 데이터 JSON 전부 기록 ──
        if self.discover_cdn and "sg-tools-cdn.blablalink.com" in response.url:
            await self._capture_cdn(response)

        # ── [1] 🌍 캐릭터 사전(영문 로케일) 심해 스니핑 ──
        # URL 이름은 못 믿는다. 응답 본문을 직접 갈라서 사전인지 확인한다.
        # (한 번만 확보하면 충분 — 이미 잡았으면 건너뜀)
        if response.request.method == "GET" and self.en_dict is None:
            try:
                # 이미지/폰트 제외, 텍스트(JSON, JS) 응답만 검사
                content_type = response.headers.get("content-type", "")
                if "json" in content_type or "javascript" in content_type:
                    text_data = await response.text()

                    # 캐릭터 도감이면 반드시 들어있는 핵심 이름으로 후보를 거른다
                    if "Dorothy" in text_data and "Anis" in text_data and "Rapi" in text_data:
                        payload = _extract_json_payload(text_data)
                        # 사전은 name_code 를 가진 dict 들의 리스트여야 한다 (JS 래퍼/오탐 방지)
                        if (isinstance(payload, list) and payload
                                and any(isinstance(e, dict) and "name_code" in e for e in payload[:5])):
                            self.en_dict = payload
                            print(f"🎁 [캐릭터 사전 확보] {len(payload)}개 엔트리 / URL: {response.url}")
                        else:
                            print(f"⚠️ 사전 후보였지만 JSON 형식/스키마 불일치 → 무시: {response.url}")
            except Exception as e:
                # 바이너리이거나 본문 읽기 실패 — 스니핑은 best-effort 라 치명적 아님
                print(f"⚠️ 사전 스니핑 중 오류 무시: {type(e).__name__}: {e}")

        # ── [2] 기존 API 탈취 로직 (유지) ──
        if API_DOMAIN not in response.url:
            return
            
        try:
            res_json = await response.json()
            if res_json.get("code") == 0:
                endpoint = response.url.split('?')[0].split('/')[-1]

                # probe: replay 설계용으로 요청 shape 캡처 (auth 헤더값은 redact)
                if self.probe and endpoint in ("GetUserCharacterDetails", "GetUserCharacters"):
                    await self._maybe_capture_probe(response, endpoint)

                # replay: roster 전체 + 요청 템플릿(헤더/공통 body) 1회 확보
                if endpoint == "GetUserCharacters" and self._api_template is None:
                    await self._capture_replay_template(response, res_json)

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
        except Exception:
            # api 도메인이지만 JSON 이 아닌 응답(이미지/리다이렉트 등) — 정상적으로 무시
            pass

    async def _maybe_capture_probe(self, response, endpoint):
        """엔드포인트별 최대 3건의 요청 shape(method/header/body)을 모은다."""
        if sum(1 for r in self.probe_requests if r["endpoint"] == endpoint) >= 3:
            return
        req = response.request
        try:
            headers = await req.all_headers()
        except Exception:
            headers = {}
        self.probe_requests.append({
            "endpoint": endpoint,
            "method": req.method,
            "url": req.url,
            "headers": _redact_headers(headers),
            "post_data": req.post_data,   # body 원본 (name_codes/서명필드 파악용)
        })
        print(f"🔬 [probe] {endpoint} 요청 캡처")

    async def _capture_cdn(self, response):
        """sg-tools-cdn JSON 1건의 URL + 형태(키/길이/preview)를 기록 (manifest/테이블 식별용)."""
        try:
            if "json" not in response.headers.get("content-type", ""):
                return
            if any(e["url"] == response.url for e in self.cdn_dump):
                return
            text = await response.text()
            payload = _extract_json_payload(text)
            entry = {"url": response.url, "bytes": len(text)}
            if isinstance(payload, dict):
                entry["kind"] = "dict"
                entry["keys"] = list(payload.keys())[:40]
            elif isinstance(payload, list):
                entry["kind"] = "list"
                entry["len"] = len(payload)
                if payload and isinstance(payload[0], dict):
                    entry["item_keys"] = list(payload[0].keys())[:25]
            else:
                entry["kind"] = "other"
                entry["preview"] = text[:200]
            self.cdn_dump.append(entry)
            print(f"🛰️ [cdn] {entry['kind']:5} {entry['bytes']:>8}B  …/{response.url.split('/')[-1]}")
        except Exception:
            pass

    def _write_cdn_dump(self):
        path = os.path.join(RAW_DIR, "_probe_cdn_dump.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.cdn_dump, f, ensure_ascii=False, indent=2)
        print(f"🛰️ [cdn] {len(self.cdn_dump)}개 CDN JSON 기록 → '{path}'")

    def _write_probe_dump(self):
        """모은 요청 shape 을 gitignore 된 파일로 기록한다(auth 헤더값 redact 됨)."""
        path = os.path.join(RAW_DIR, "_probe_request_dump.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.probe_requests, f, ensure_ascii=False, indent=2)
        print(f"🔬 [probe] 요청 덤프 저장: '{path}' ({len(self.probe_requests)}건). "
              f"⚠ auth 헤더값 redact, body 는 원본.")

    async def _capture_replay_template(self, response, res_json):
        """GetUserCharacters 응답/요청에서 replay 재료를 1회 확보.

        - 응답 data.characters → 전체 roster name_codes
        - 요청 body → intl_open_id / nikke_area_id
        - 요청 headers → 재사용 헤더(쿠키 제외; context 가 자동 부착)
        """
        chars = (res_json.get("data") or {}).get("characters") or []
        self._roster_name_codes = [c["name_code"] for c in chars if "name_code" in c]
        try:
            req = response.request
            body = json.loads(req.post_data or "{}")
            headers = await req.all_headers()
            self._api_template = {
                "intl_open_id": body.get("intl_open_id"),
                "nikke_area_id": body.get("nikke_area_id"),
                "headers": _clean_request_headers(headers),
            }
            print(f"📋 [replay] roster {len(self._roster_name_codes)}명 + 요청 템플릿 확보 "
                  f"(area_id={self._api_template['nikke_area_id']}).")
        except Exception as e:
            print(f"⚠️ [replay] 요청 템플릿 캡처 실패: {type(e).__name__}: {e}")

    async def _replay_character_details(self, context):
        """roster name_codes 를 직접 batch POST 해 디테일을 수집(토글/스크롤 없이).

        반환: 수집한 character_details 총 개수.
        """
        tmpl = self._api_template
        roster = self._roster_name_codes
        if not tmpl or tmpl.get("intl_open_id") is None or tmpl.get("nikke_area_id") is None:
            print("❌ [replay] GetUserCharacters 요청 정보를 못 잡음 → replay 불가.")
            return 0
        if not roster:
            print("❌ [replay] roster 가 비어있음 → replay 불가.")
            return 0

        detail_url = f"{API_BASE}/api/game/proxy/Game/GetUserCharacterDetails"
        collected = 0
        n = len(roster)
        for i in range(0, n, self.batch_size):
            chunk = roster[i:i + self.batch_size]
            body = {
                "intl_open_id": tmpl["intl_open_id"],
                "nikke_area_id": tmpl["nikke_area_id"],
                "name_codes": chunk,
            }
            try:
                resp = await context.request.post(
                    detail_url, headers=tmpl["headers"], data=json.dumps(body))
                rj = await resp.json()
            except Exception as e:
                print(f"⚠️ [replay] 배치 {i // self.batch_size} 요청 실패: {type(e).__name__}: {e}")
                continue
            if rj.get("code") != 0:
                print(f"⚠️ [replay] 배치 {i // self.batch_size} code={rj.get('code')} → 건너뜀")
                continue
            self.phase2_data.append({
                "endpoint": "GetUserCharacterDetails",
                "url": detail_url,
                "data": rj.get("data"),
            })
            cd = (rj.get("data") or {}).get("character_details") or []
            collected += len(cd)
            print(f"   ⚡ {min(i + self.batch_size, n)}/{n} (배치 {len(chunk)}개)")
        return collected

    async def _dismiss_cookie_banner(self, page):
        """쿠키 동의 팝업('YOUR COOKIE PREFERENCES')이 떠 있으면 닫는다.

        이 팝업이 region 선택/로그인 입력을 가리므로 **선행** 처리 필요.
        'Reject all optional cookies' 우선(불필요 쿠키 최소화), 실패 시 Accept.
        팝업이 없으면 조용히 통과(비치명적) — 각 후보는 짧은 timeout.
        """
        candidates = [
            page.get_by_role("button", name=re.compile(r"reject all optional", re.I)),
            page.get_by_role("button", name=re.compile(r"accept all optional", re.I)),
            page.get_by_text("Reject all optional cookies", exact=False),
            page.get_by_text("Accept all optional cookies", exact=False),
        ]
        for loc in candidates:
            try:
                await loc.first.click(timeout=4000)
                print("🍪 쿠키 팝업 처리 완료.")
                return
            except Exception:
                continue
        print("🍪 쿠키 팝업 없음(또는 이미 처리됨) — 통과.")

    async def _auto_login(self, page, login_id: str, password: str, region: str):
        """region 팝업 선택 → 이메일/비밀번호 입력 → 로그인 버튼 클릭.

        ⚠ 브라우저 locale=en-US 강제(영문 사전 캡처용) → 로그인 UI 가 **영어**.
        따라서 셀렉터도 영어 기준. region 도 'JP/KR/NA/SEA/Global' 같은 영어 표기.
        비밀번호/버튼은 가능한 한 언어 독립(input type / regex)으로 잡는다.
        실패 시 예외를 올려 호출부가 EXIT_LOGIN_FAIL 로 처리하게 한다.
        """
        # 0) 쿠키 동의 팝업이 region/입력을 가리므로 먼저 닫는다.
        await self._dismiss_cookie_banner(page)

        # 1) region 선택 팝업 (영어: 'Select Region' / 'JP/KR/NA/SEA/Global').
        #    region 문자열(부분일치) 옵션 클릭. 안 떴으면 'Select Region' 드롭다운으로 연다.
        print(f"🌏 region 선택: '{region}' …")
        region_opt = page.get_by_text(region, exact=False)
        try:
            await region_opt.last.click(timeout=15000)
        except Exception:
            print("   ↳ 옵션이 안 보임 → 'Select Region' 드롭다운 여는 중...")
            await page.get_by_text("Select Region", exact=False).first.click(timeout=10000)
            await region_opt.last.click(timeout=10000)

        # 2) 이메일 입력 (placeholder 'Email' 우선, 실패 시 input type 폴백).
        print("✍️ 이메일/비밀번호 입력...")
        try:
            await page.get_by_placeholder("Email").fill(login_id, timeout=15000)
        except Exception:
            await page.locator('input[type="email"], input[type="text"]').first.fill(
                login_id, timeout=10000)
        #    비밀번호는 input[type=password] 로 언어 독립.
        await page.locator('input[type="password"]').first.fill(password, timeout=15000)

        # 3) 로그인 버튼: 'Log In' 변형(대소문자/공백) regex + role=button → 'Email Login' 링크 배제.
        print("🔐 로그인 클릭...")
        await page.get_by_role("button", name=re.compile(r"log\s*in", re.I)).first.click(timeout=15000)

    async def run_scenario(self, uid: str, login_id: str, password: str,
                           region: str, login_timeout: float = 120.0,
                           probe: bool = False, batch_size: int = 10,
                           discover_cdn: bool = False) -> int:
        self.probe = probe
        self.batch_size = batch_size
        self.discover_cdn = discover_cdn
        target_url = f"{BASE_DOMAIN}/shiftyspad/nikke-list?uid={self.encode_uid(uid)}&openid={self.encode_uid(uid)}"
        login_url = f"{BASE_DOMAIN}/login?to={target_url}&back_to={target_url}"

        print("🕵️‍♀️ [가키짱의 듀얼-코어 크롤러] API & 언어팩 동시 강탈 기동 중...")
        logged_in = False
        async with async_playwright() as p:
            # 언어팩을 '영어'로 강제 호출하기 위해 브라우저의 기본 언어(locale)를 영어(en-US)로 세팅한다! ♥
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(locale="en-US")
            page = await context.new_page()

            page.on("response", self.intercept_response)

            await page.goto(login_url, wait_until="domcontentloaded")

            # ── 자동 로그인: region 팝업 → 자격증명 입력 → 로그인 ──
            try:
                await self._auto_login(page, login_id, password, region)
            except Exception as e:
                print(f"❌ 자동 로그인 단계 실패: {type(e).__name__}: {e}")
                await browser.close()
                return EXIT_LOGIN_FAIL

            # 로그인 성공은 CheckLogin 패킷으로 확인 (제출 후 응답까지 대기)
            print(f"⏳ 로그인 확인(CheckLogin) 대기 (최대 {login_timeout:.0f}초)...")
            try:
                await asyncio.wait_for(self.login_success.wait(), timeout=login_timeout)
                logged_in = True
                print("✅ 로그인 확인됨!")
            except asyncio.TimeoutError:
                print(f"❌ {login_timeout:.0f}초 안에 로그인이 확인되지 않음 (자격증명·셀렉터 점검) → 중단.")

            if logged_in:
                print("🚀 니케 리스트 뷰로 이동!")
                await page.goto(target_url, wait_until="networkidle")
                # 여기서 GetUserCharacters 발생 → roster + 요청 템플릿 확보됨.
                self.current_phase = 2

                if self.discover_cdn:
                    # CDN 정적 데이터(manifest/테이블)가 로드되도록 잠시 대기하며 캡처.
                    print("🛰️ [cdn] CDN 정적 데이터 로드 대기 (15초)...")
                    await page.wait_for_timeout(15000)
                elif self.probe:
                    # probe: UI 가 실제 디테일 요청을 쏘게 토글+스크롤 (요청 shape 캡처용).
                    print("\n👉 [probe] '리스트 뷰 토글'(파란 버튼) 클릭해줘! 20초 대기...")
                    await page.wait_for_timeout(20000)
                    for i in range(25):
                        await page.mouse.wheel(0, 2000)
                        await page.wait_for_timeout(1000)
                    print("✅ [probe] UI 스크롤 종료.")
                else:
                    # 수집: replay 로 디테일 직접 배치 호출 (토글/스크롤 불필요).
                    print("⚡ [replay] GetUserCharacterDetails 직접 배치 호출 (스크롤 없음)...")
                    got = await self._replay_character_details(context)
                    print(f"✅ [replay] 디테일 {got}/{len(self._roster_name_codes)} 수집 완료.")

            await browser.close()

        # CDN 디스커버리 모드: 수집한 CDN JSON 목록만 남기고 종료(유저데이터 저장 안 함).
        if self.discover_cdn:
            if self.cdn_dump:
                self._write_cdn_dump()
            else:
                print("⚠️ [cdn] sg-tools-cdn JSON 을 하나도 못 잡음 (페이지가 다르게 로드?).")
            return EXIT_OK if logged_in else EXIT_LOGIN_TIMEOUT

        # probe 덤프는 로그인만 되면(데이터 수집 성패 무관) 남긴다.
        if self.probe and self.probe_requests:
            self._write_probe_dump()

        if not logged_in:
            return EXIT_LOGIN_TIMEOUT

        # 수집량 0 이면 직전 정상 산출물을 빈 데이터로 덮어쓰지 않도록 저장을 건너뛴다.
        captured = len(self.phase1_data) + len(self.phase2_data)
        if captured == 0:
            print("❌ 유저 캐릭터/장비 데이터를 하나도 수집하지 못함 → 저장 생략, 실패 종료.")
            return EXIT_NO_USER_DATA

        # replay 완결성: roster 대비 디테일이 모자라면 부분 결과를 저장하지 않는다. (probe 제외)
        if not self.probe:
            roster_n = len(self._roster_name_codes)
            detail_n = sum(len((pk.get("data") or {}).get("character_details") or [])
                           for pk in self.phase2_data)
            if roster_n and detail_n < roster_n:
                print(f"❌ [불완전] 디테일 {detail_n}/{roster_n} 만 수집 → 저장 생략, 실패 종료.")
                return EXIT_INCOMPLETE

        # ── [저장 1] 기존 유저 데이터 저장 ──
        final_result = {
            "uid": uid,
            "phase_1_initial_load": self.phase1_data,
            "phase_2_after_click": self.phase2_data
        }
        api_save_path = os.path.join(RAW_DIR, "nikke_full_scroll_result.json")
        with open(api_save_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        print(f"\n💾 [저장] 유저 API 데이터 '{api_save_path}'에 안착! (패킷 {captured}개)")

        # ── [저장 2] 🔥 영문 캐릭터 사전 저장 (검증된 JSON 으로) ──
        # 스니핑 시점에 이미 JSON 파싱·스키마 검증을 마쳤으므로, 여기서는 .json 으로 1회 기록.
        if self.en_dict:
            dict_save_path = os.path.join(RAW_DIR, "real_en_dict_dump.json")
            with open(dict_save_path, "w", encoding="utf-8") as f:
                json.dump(self.en_dict, f, ensure_ascii=False, indent=2)
            print(f"💾 [저장] 영문 캐릭터 사전 '{dict_save_path}' ({len(self.en_dict)}개 엔트리)")
        else:
            # 사전 미확보는 비치명적: 기존 real_en_dict_dump.json 을 덮어쓰지 않고 유지한다.
            print("⚠️ 캐릭터 사전을 캡처하지 못했어. 기존 사전 파일을 그대로 유지한다.")

        return EXIT_OK


def main():
    parser = argparse.ArgumentParser(
        description="BlaBlaLink 유저 데이터 + 영문 캐릭터 사전 크롤러"
    )
    parser.add_argument(
        "uid", nargs="?", default=os.environ.get("NIKKE_UID"),
        help="유저 UID(숫자). 생략 시 .env/NIKKE_UID 사용. 인자는 per-run override 용(매번 칠 필요 없음)"
    )
    parser.add_argument(
        "--login-timeout", type=float, default=120.0,
        help="로그인 제출 후 CheckLogin 확인 대기 시간(초). 기본 120"
    )
    parser.add_argument(
        "--probe", action="store_true",
        help="GetUserCharacterDetails/Characters 요청 shape 을 _probe_request_dump.json 에 캡처 (디버그용)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="replay 시 GetUserCharacterDetails 배치당 name_codes 수. 기본 10(관측치)"
    )
    parser.add_argument(
        "--discover-cdn", action="store_true",
        help="로그인 후 sg-tools-cdn 정적 데이터 JSON(manifest/테이블) URL 을 _probe_cdn_dump.json 에 수집"
    )
    args = parser.parse_args()

    if not args.uid:
        # argparse 사용법 오류로 처리 → 종료 코드 2
        parser.error("UID 가 필요해: 인자로 전달하거나 NIKKE_UID 환경변수를 설정해.")

    # 자격증명 로드 (env / DataPipeline/.env). 누락 시 브라우저 띄우기 전에 즉시 실패.
    try:
        login_id = _secrets.get("NIKKE_BLABLA_ID")
        password = _secrets.get("NIKKE_BLABLA_PW")
        # locale=en-US → region 팝업도 영어. 한국 포함 옵션 = 'JP/KR/NA/SEA/Global'.
        region = _secrets.get("NIKKE_REGION", required=False,
                              default="JP/KR/NA/SEA/Global")
    except _secrets.SecretMissingError as e:
        print(f"❌ {e}")
        return EXIT_LOGIN_FAIL

    return asyncio.run(
        GakiSniffer().run_scenario(
            args.uid, login_id, password, region,
            login_timeout=args.login_timeout,
            probe=args.probe, batch_size=args.batch_size,
            discover_cdn=args.discover_cdn,
        )
    )


if __name__ == "__main__":
    sys.exit(main())