"""blablalink 공개 CDN 접근 — URL 난독화 재현 + JSON fetch (로그인 불필요).

frontend `createNormalObfuscatedPath` (index-*.js) 재현:
  - 파일명 = md5(논리경로) + 확장자  (path 기반 → URL 안정)
  - 디렉토리 = djb2(path, LARGE_PRIMES[i]) → 2글자-2숫자
공개 CDN(sg-tools-cdn.blablalink.com)이라 인증 불필요. curl_cffi 로 Cloudflare 통과.
"""
import hashlib
import time

from curl_cffi import requests as creq

CDN = "https://sg-tools-cdn.blablalink.com"
LOCALE = "en"
IMPERSONATE = "chrome"
LARGE_PRIMES = [224737, 1000639, 2654435761, 2654435769, 1000621, 4294967291]

# 알고리즘 self-check 기준 (영문 캐릭터 사전의 알려진 난독화 경로)
_KNOWN_LOGICAL = "character/en/nikke_list_en_v2.json"
_KNOWN_OBFUSCATED = "yl-57/hd-03/1bf030193826e243c2e195f951a4be00.json"


def _to_int32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x


def _djb2(s, seed):
    ie = seed
    for ch in s:
        ie = _to_int32(ie * 33 + ord(ch))
    return ie


def _two_letter(path, prime):
    re = ((_djb2(path, prime) % prime) + prime) % prime
    return chr(97 + (re // 26) % 26) + chr(97 + re % 26)


def _two_number(path, prime):
    re = ((_djb2(path, prime) % prime) + prime) % prime
    return str(re % 99).zfill(2)


def obfuscated_path(logical):
    """논리경로 → 난독화 CDN 경로."""
    logical = logical.lstrip("/")
    segs = [s for s in logical.split("/") if s]
    out = []
    last = len(segs) - 1
    for i, seg in enumerate(segs):
        if i == last:
            parts = seg.split(".")
            parts.pop(0)  # 이름 토막 제거, 확장자만 유지
            out.append(f"{hashlib.md5(logical.encode()).hexdigest()}." + ".".join(parts))
        else:
            out.append(f"{_two_letter(logical, LARGE_PRIMES[i])}-{_two_number(logical, LARGE_PRIMES[i])}")
    return "/".join(out)


def cdn_url(logical):
    return f"{CDN}/{obfuscated_path(logical)}"


def self_check():
    """난독화 알고리즘이 여전히 유효한지(블라블라링크가 규칙 안 바꿨는지) 확인."""
    return obfuscated_path(_KNOWN_LOGICAL) == _KNOWN_OBFUSCATED


def fetch_json(logical, retries=3, required=True):
    """CDN 에서 JSON 1개를 가져온다. 실패 시 None (required 면 호출부가 처리)."""
    url = cdn_url(logical)
    last = None
    for attempt in range(retries):
        try:
            r = creq.get(url, impersonate=IMPERSONATE, timeout=20)
            if r.status_code == 200:
                return r.json()
            last = f"status {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(0.5 * (attempt + 1))
    if required:
        print(f"   ❌ fetch 실패: {logical} ({last})")
    return None
