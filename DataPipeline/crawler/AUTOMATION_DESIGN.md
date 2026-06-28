# BlaBlaLink 크롤러 완전 자동화 — 설계 (작업 기준 문서)

> **목적**: `getFromBlaLink.py` 의 수동 3단계(로그인 / 뷰 토글 / 스크롤)를 전부 제거해
> BlaBlaLink 유저 데이터 수집을 **완전 자동화**한다.
> **지위**: 이 문서 = 이 자동화 작업의 단일 흐름 기준. 길어져도 여기로 복귀.
> **확정일**: 2026-06-28 (사용자 결정 반영). 실측 근거 = `Database/raw/nikke_full_scroll_result.json`.

---

## 0. 진행 체크리스트 (작업 재개용)

- [x] 실측 분석 (엔드포인트 shape / batch / 위치)
- [x] 설계 확정 (API replay + full id/pw + region 팝업)
- [x] secrets 배선 + `.gitignore`
      (`.env.example` 템플릿, `crawler/_secrets.py` 로더[dotenv 옵션+내장 폴백],
       `.gitignore` 에 `auth_state.json`, `requirements.txt` 에 `python-dotenv`)
- [x] 로그인 자동화 — **라이브 검증됨 2026-06-28** ("✅ 로그인 확인됨!"). region/이메일/비번/로그인 셀렉터 적중.
      ⚠ locale=en-US → UI 영어. region="JP/KR/NA/SEA/Global"(한국 포함, 부분일치 기본).
      쿠키 동의 팝업이 가리는 문제 발견 → `_dismiss_cookie_banner()` 선행 추가('Reject all optional' 우선).
      셀렉터(영어): 쿠키 `/reject|accept all optional/i`, region `get_by_text(region).last`,
      이메일 `get_by_placeholder("Email")`(폴백 input[type=email/text]), 비번 `input[type=password]`,
      로그인 `get_by_role("button", name=/log\s*in/i).first`. (쿠키 처리분만 재확인 권장.)
- [x] probe 계측 + 실행 — `--probe` 로 `GetUserCharacterDetails` body 확보(§3.2.1).
      배치 키=`name_codes` 리스트, 서명 헤더 없음(cookie+x-common-params 인증).
      덤프 `Database/raw/_probe_*.json`(gitignore), auth 헤더값 redact.
- [~] replay 루프 + 완결성 가드 — **코드 완료, 라이브 검증 대기**
      GetUserCharacters→roster+요청템플릿(헤더/area_id) 확보 → `context.request.post` 로
      name_codes 를 `--batch-size`(기본10) 단위 직접 호출(쿠키 자동, x-common-params 재사용).
      `EXIT_INCOMPLETE=12`(detail<roster 시 저장 생략).
- [x] 토글/25× 스크롤 제거(normal run) — `--probe` 시에만 UI 경로 유지(디버그)
- [ ] **라이브 수집 검증 (detail==roster) → 통과 시 커밋**  ← 다음

---

## 1. 확정 결정 (2026-06-28)

| 항목 | 결정 | 비고 |
|---|---|---|
| 데이터 수집 | **API replay** (스크롤 제거) | probe 먼저 → 서명 유무 확인 후 디테일 확정 |
| 로그인 | **full id/pw 자동입력** | CAPTCHA/2FA 없음 |
| 로그인 선행 | **region 선택 팝업** 처리 필요 | 이게 풀려야 id/pw 입력 활성화 |
| 비밀정보 | env / `.env` (커밋·하드코딩 금지) | `.env` 는 이미 `.gitignore` 처리됨 |

---

## 2. 실측 근거 (검증된 엔드포인트 shape)

`nikke_full_scroll_result.json` (178인 로스터 실측) 분석 결과:

| 엔드포인트 | 단계 | 스크롤 필요 | 반환 |
|---|---|---|---|
| `GetUserCharacters` | phase-1 (초기 로드) | ❌ | **전체 roster 178** (`name_code, lv, grade, core, combat, costume_id`) |
| `GetUserProfileOutpostInfo` | phase-1 | ❌ | `recycle_room_researches`(콘솔) + `synchro_level` |
| `GetUserCharacterDetails` | phase-2 | ✅ (lazy) | **10개씩 batch** (17×10 + 1×8 = 178). `character_details` **+** `state_effects`(오버로드 옵션 딕셔너리) 동시 포함 |

**핵심 결론:**
1. lazy-load anti-crawl 은 **`GetUserCharacterDetails` 만** 가린다. 로스터 전체 목록은 초기 로드에서 공짜로 온다.
2. `state_effects`(오버로드 해석용 딕셔너리)는 **오직 phase-2 details 안**에 있다 → replay 가 character_details + state_effects 를 한 번에 회수.
3. 콘솔/synchro 는 phase-1 에서 공짜 → replay 대상 아님.
4. batch param 은 POST **body** 에 있음 (URL query 아님 → 캡처 파일엔 없음). → **probe 필요.**

### 스크롤 anti-crawl 의 원인
리스트가 **IntersectionObserver lazy list**. 한 번에 맨 밑으로 점프(또는 빠른 25× wheel)하면 중간 행들이 viewport 에 머무는 시간이 없어 observer 가 안 터짐 → 해당 batch 의 detail POST 미발생. 위로 조금 올리면 건너뛴 행이 재진입 → observer 발화 → batch 로드. (사용자가 수동으로 위로 올리는 이유.)

### 서버 관점의 레버리지
서버는 body 의 name_code 만 보고 답한다. 스크롤은 프론트가 "어느 10개를 물을지" 고르는 수단일 뿐. 우리가 roster 전체를 직접 chunk 해서 물으면 lazy-load 자체가 무관해진다.

---

## 3. 설계

### 3.1 로그인 자동화 (수동 step 2 제거)

```
goto(login_url)
  → [쿠키 팝업] 'Reject all optional cookies' click (없으면 통과)  ← region/입력 가림, 선행 필수
  → [region 팝업] 대기 → 지정 지역 옵션 click   ← 풀려야 id/pw 활성화
  → id / pw fill (env/.env 에서 주입; 하드코딩·커밋 금지)
  → 로그인 버튼 click
  → CheckLogin 패킷 대기 (기존 self.login_success 이벤트 재사용)
```

- **비밀정보**: `NIKKE_BLABLA_ID` / `NIKKE_BLABLA_PW` 환경변수 (또는 `DataPipeline/.env`). `_secrets.py` 가 로드, 없으면 명확한 에러.
- **⚠ locale 제약**: 크롤러는 `locale="en-US"` 강제(영문 사전 캡처 필수 — 사전 sniff 가 "Dorothy/Anis/Rapi" 영문명에 의존). → **로그인 UI 전체가 영어**. 모든 셀렉터는 영어 기준이어야 함.
- **region**: `NIKKE_REGION` env (기본 `JP/KR/NA/SEA/Global` = 한국 포함). 팝업 옵션 텍스트와 **부분일치**. 영어 팝업 스크린샷 확인(2026-06-28): `Select Region` / `HK/MC/TW` / `JP/KR/NA/SEA/Global`✓.
- **셀렉터 취약성**: 남은 유일한 UI 의존 = region 팝업 + id/pw + 로그인 버튼. role/text 기반 견고 셀렉터로.
- **선택적 가속**: 최초 성공 후 Playwright `storage_state` → `auth_state.json` 저장 → 다음 런은 region+로그인 스킵. credential-fill 이 primary, storage_state 는 옵션/fallback. (`auth_state.json` 은 `.gitignore`.)

### 3.2 데이터 수집 — API replay (수동 step 4+5 제거)

```
로그인 후 nikke-list 이동
  → [phase-1 무료 sniff]  GetUserCharacters(178 roster)
                          GetUserProfileOutpostInfo(consoles+synchro) ...
  → [probe, 구현 중 1회]  GetUserCharacterDetails 의 request.method/headers/post_data 기록
                          → body 스키마 + 서명 헤더 유무 파악
  → [replay]  roster name_code 를 N개씩 chunk (관측 10; 더 키울 수 있는지 시험)
              → 각 chunk 를 page.evaluate(fetch) 로 POST (쿠키 + JS 서명 재사용)
              → 응답마다 character_details + state_effects 회수
  → [완결성 가드]  회수 detail 수 == roster 수 ? 아니면 저장 안 하고 실패 종료
  → 저장: phase_1(sniff) + phase_2(replay) 동일 shape → blabla_merger 무수정
```

### 3.2.1 probe 발견 (2026-06-28, 1차)
- `GetUserCharacters`: **POST** `/api/game/proxy/Game/GetUserCharacters`, `content-type: application/json`,
  body `{"intl_open_id":"<openid>","nikke_area_id":83}`. (전체 roster 반환, name_codes 불필요.)
- 인증 = **cookie + `x-common-params`** 헤더. **서명 헤더(`x-sign`/`sign`/`authorization`) 없음.**
  → replay 는 per-request HMAC 불필요. 같은 api 도메인 POST 의 헤더(cookie/x-common-params/x-channel-type/x-language)
  를 그대로 재사용해 호출 가능. (x-common-params 값은 런타임 메모리에서 재사용, 디스크 저장 X.)
- ✅ **`GetUserCharacterDetails` 확보 (2차 probe)**: **POST** `/api/game/proxy/Game/GetUserCharacterDetails`,
  `content-type: application/json`, body `{"intl_open_id":"<uid>","nikke_area_id":83,"name_codes":[...10개...]}`.
  → 배치 키 = **`name_codes` 리스트** (우리가 직접 chunk). 서명 없음.
  `intl_open_id`=uid, `nikke_area_id`=live GetUserCharacters 요청 body 에서 추출해 재사용.
  **replay 완전 확정 — 스크롤/토글 제거 가능.**

### 3.3 ETL 계약 보존 (중요)
`etl/blabla_merger.py` 는 `phase_1_initial_load` + `phase_2_after_click` 패킷을 deep_find 로 읽어
`characters / character_details / state_effects / recycle_room_researches / synchro_level` 를 뽑는다.
→ replay 산출물을 **같은 2-phase shape** 로 저장하면 ETL 은 **수정 불필요**.

---

## 4. 종료 코드 (task-2 연장)

현재 (`getFromBlaLink.py`):
- `EXIT_OK=0` / `EXIT_LOGIN_TIMEOUT=10`(제출후 CheckLogin 미확인) / `EXIT_NO_USER_DATA=11`
- `EXIT_LOGIN_FAIL=13` — 로그인 단계 실패(셀렉터 불일치·잘못된 계정·비밀정보 누락). **구현됨**
- argparse 사용법오류=2

신설 예정:
- `EXIT_INCOMPLETE` — detail 수 ≠ roster 수 → 부분 저장 방지 (replay 단계)
- `EXIT_SESSION_EXPIRED` — (storage_state 경로 쓸 때) 세션 만료 → 재-seed 안내

---

## 5. 리스크 / 미확정

- **서명(signing)**: probe 전 미확정. in-page `fetch` 라 JS 서명 자동 적용 → 대부분 해결 예상. 안 되면 §3.2 fallback = smart UI scroll.
- **headless**: region 팝업 + 봇탐지 때문에 처음엔 `headless=False` 유지. probe 후 headless 시도.
- **ToS**: 자동 로그인은 약관 리스크 존재. footprint 최소화(런당 1회), storage_state 재사용으로 로그인 빈도↓.
- **fallback (서명에 막힐 시)**: 기존 sniffer 유지 + 토글 자동 click + **content-driven scroll**(작은 step → batch count 증가 대기 → 아래-위 oscillate → count 안정 시 정지). reverse-eng 불필요하나 UI 의존.

---

## 6. 구현 순서

1. secrets 배선 + `.gitignore` (`.env.example`, `_secrets.py`, `auth_state.json` ignore)
2. 로그인 자동화 (region 팝업 → fill → submit, CheckLogin 확인)
3. probe 계측 → `GetUserCharacterDetails` 요청 body/서명 확보
4. replay 루프 + 완결성 가드
5. 토글 + 25× 스크롤 코드 제거
6. smoke + count assertion (detail 수 == roster 수)

---

## 7. 참조

- 대상 코드: `DataPipeline/crawler/getFromBlaLink.py`
- 다운스트림 ETL: `DataPipeline/etl/blabla_merger.py` (2-phase 계약)
- 실측 데이터: `Database/raw/nikke_full_scroll_result.json` (gitignored, 유저 로컬)
- URL: `login_url = {BASE}/login?to={target}&back_to={target}`, `target = {BASE}/shiftyspad/nikke-list?uid=&openid=` (uid = `base64("29080-{uid}")`)
