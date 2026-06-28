"""DataPipeline 비밀/설정 로더.

우선순위: 실제 프로세스 환경변수 > DataPipeline/.env (있으면).
python-dotenv 가 설치돼 있으면 .env 를 표준 파서로 로드하고, 없으면 내장 최소
파서로 직접 읽는다 (추가 의존성 없이도 동작). 최종 소스는 항상 os.environ.

자격증명은 코드/깃에 절대 넣지 않는다 — env 또는 .gitignore 처리된 .env 에서만.
"""
import os

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# crawler/ 의 부모 = DataPipeline/ 에 위치한 .env
_ENV_PATH = os.path.join(_CURRENT_DIR, "..", ".env")


class SecretMissingError(RuntimeError):
    """필수 비밀/설정 누락."""


def _load_env_file(path):
    """.env 의 KEY=VALUE 를 os.environ 에 주입한다 (기존 env 값이 우선)."""
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv  # 설치돼 있으면 표준 파서 사용
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    # python-dotenv 미설치 시 내장 최소 파서 (KEY=VALUE, # 주석, 따옴표 제거)
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env_file(_ENV_PATH)


def get(name, required=True, default=None):
    """환경변수 1개 조회. required 인데 비어있으면 SecretMissingError."""
    val = os.environ.get(name, default)
    if required and not val:
        raise SecretMissingError(
            f"필수 환경변수 '{name}' 가 비어있음. DataPipeline/.env 에 채우거나 "
            f"환경변수로 설정해. (템플릿: DataPipeline/.env.example)"
        )
    return val


def blabla_credentials():
    """BlaBlaLink 로그인 자동화에 필요한 (uid, login_id, password, region) 반환.

    누락된 항목이 있으면 어떤 키들이 비었는지 모아서 한 번에 알려준다.
    """
    keys = ("NIKKE_UID", "NIKKE_BLABLA_ID", "NIKKE_BLABLA_PW", "NIKKE_REGION")
    values = {k: os.environ.get(k) for k in keys}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise SecretMissingError(
            "BlaBlaLink 자격증명 누락: " + ", ".join(missing) +
            " - DataPipeline/.env 채우기 (템플릿: DataPipeline/.env.example)"
        )
    return tuple(values[k] for k in keys)
