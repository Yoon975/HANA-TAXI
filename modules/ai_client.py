"""
생성형 AI 클라이언트 — Google Gemini 전용.
API 키는 문서\\택시자동화\\_config\\gemini_api_key.txt 에 저장.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.paths import CONFIG_DIR, ensure_storage

PROVIDER_GEMINI = "gemini"
PROVIDERS = [PROVIDER_GEMINI]
PROVIDER_LABELS = {PROVIDER_GEMINI: "Google Gemini"}
DEFAULT_PROVIDER = PROVIDER_GEMINI

# 사이드바 선택 목록 (Google AI Studio / Gemini API 기준)
MODEL_CHOICES = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
]
DEFAULT_MODEL = "gemini-3.5-flash"

MODELS = {PROVIDER_GEMINI: MODEL_CHOICES}
DEFAULT_MODELS = {PROVIDER_GEMINI: DEFAULT_MODEL}

API_KEY_URL = "https://aistudio.google.com/apikey"
GEMINI_HOME = "https://aistudio.google.com/"
API_KEY_URLS = {PROVIDER_GEMINI: API_KEY_URL}
HOME_URLS = {PROVIDER_GEMINI: GEMINI_HOME}

KEY_FILE = "gemini_api_key.txt"
PROVIDER_FILE = "ai_provider.txt"


def _ensure_gemini_provider() -> None:
    """이전 Groq 설정이 남아 있어도 Gemini로 고정."""
    try:
        ensure_storage()
        path = CONFIG_DIR / PROVIDER_FILE
        path.write_text(PROVIDER_GEMINI, encoding="utf-8")
    except OSError:
        pass


def load_provider() -> str:
    _ensure_gemini_provider()
    return PROVIDER_GEMINI


def save_provider(provider: str) -> None:
    _ensure_gemini_provider()


def api_key_path(provider: str | None = None) -> Path:
    ensure_storage()
    return CONFIG_DIR / KEY_FILE


def load_api_key(provider: str | None = None) -> str:
    path = api_key_path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_api_key(key: str, provider: str | None = None) -> Path:
    path = api_key_path()
    path.write_text(key.strip(), encoding="utf-8")
    return path


def clear_api_key(provider: str | None = None) -> None:
    path = api_key_path()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            path.write_text("", encoding="utf-8")


def has_api_key(provider: str | None = None) -> bool:
    return bool(load_api_key())


def models_for(provider: str | None = None) -> list[str]:
    return list(MODEL_CHOICES)


def default_model_for(provider: str | None = None) -> str:
    return DEFAULT_MODEL


def setup_guide_markdown(provider: str | None = None) -> str:
    return f"""
**AI(요약·자동 수정)를 쓰려면 Google Gemini API 키가 필요합니다.**  
(키가 없어도 공문 저장·엑셀·분석은 그대로 사용할 수 있습니다.)

### 1) API 키 발급 (무료 할당량)
1. [{API_KEY_URL}]({API_KEY_URL}) 에 Google 계정으로 로그인합니다.
2. **Create API key** 를 누릅니다.
3. 가능하면 **선불(prepaid) 결제가 없는 프로젝트**에서 키를 만드세요.  
   선불 크레딧이 0이면 오류가 납니다 → **새 무료 프로젝트/다른 계정**으로 키를 다시 발급하세요.

### 2) 이 앱에 입력
1. 왼쪽 사이드바에 API 키를 붙여 넣고 **키 저장**.
2. 모델은 **`gemini-3.5-flash`**(권장) 또는 목록에 있는 모델을 선택.
3. **연결 테스트**가 성공하면 요약·AI 수정을 사용할 수 있습니다.

### 3) 참고
- 인터넷이 필요합니다.
- 무료 한도 초과 시 잠시 후 다시 시도하세요.
- 키는 이 PC `문서\\택시자동화\\_config` 에만 저장됩니다.

공식: [{GEMINI_HOME}]({GEMINI_HOME})
"""


def setup_guide_plain(provider: str | None = None) -> str:
    return (
        "AI: Google Gemini\n"
        f"키 발급: {API_KEY_URL}\n"
        "사이드바에 키 저장 → 연결 테스트 → 요약/AI 수정\n"
        "권장 모델: gemini-3.5-flash\n"
        "선불 크레딧 소진 시: 무료 프로젝트로 새 키 발급\n"
        "(키 없이도 공문 저장·엑셀·분석 가능)"
    )


def ensure_guide_file(provider: str | None = None) -> Path | None:
    try:
        ensure_storage()
        path = CONFIG_DIR / "Gemini_API_키_안내.txt"
        path.write_text(setup_guide_plain(), encoding="utf-8")
        return path
    except Exception:
        return None


def _extract_error_code(exc: BaseException) -> str:
    """HTTP/gRPC 상태·코드명을 최대한 뽑아 개발용으로 표시."""
    parts: list[str] = []
    msg = str(exc)

    for attr in ("status_code", "code", "grpc_status_code"):
        val = getattr(exc, attr, None)
        if val is None:
            continue
        # google.api_core: code 가 enum (name=RESOURCE_EXHAUSTED, value=8)
        name = getattr(val, "name", None)
        if name:
            parts.append(str(name))
        num = getattr(val, "value", val)
        if num is not None and str(num) not in parts and str(name or "") != str(num):
            parts.append(str(num))

    # 메시지에 흔한 HTTP 코드가 있으면 보조로 포함
    for http in ("429", "404", "401", "403", "400", "500", "503"):
        if http in msg and http not in parts:
            parts.append(http)
            break

    if "resource_exhausted" in msg.lower() and "RESOURCE_EXHAUSTED" not in parts:
        parts.insert(0, "RESOURCE_EXHAUSTED")

    # 중복 제거(순서 유지)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return " / ".join(uniq) if uniq else "UNKNOWN"


def friendly_error(exc: BaseException) -> str:
    """한글 안내 + [에러코드] + 원문 (개발 중 디버깅용)."""
    msg = str(exc)
    low = msg.lower()
    code = _extract_error_code(exc)
    prefix = f"[{code}]"

    if "prepayment" in low or "credits are depleted" in low or "billing" in low:
        return (
            f"{prefix} 결제/선불 크레딧이 소진되었습니다.\n"
            "→ AI Studio에서 선불 없는(무료) 프로젝트로 새 API 키를 발급하세요.\n"
            f"원문: {msg}"
        )
    if "429" in msg or "rate limit" in low or "quota" in low or "resource_exhausted" in low:
        return (
            f"{prefix} 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.\n"
            f"원문: {msg}"
        )
    if "404" in msg or "no longer available" in low or "not found" in low:
        return (
            f"{prefix} 선택한 모델을 사용할 수 없습니다.\n"
            "→ 사이드바에서 gemini-3.5-flash 등 다른 모델을 고르세요.\n"
            f"원문: {msg}"
        )
    if (
        "api key" in low
        or ("invalid" in low and "key" in low)
        or "401" in msg
        or "403" in msg
        or "unauthorized" in low
    ):
        return (
            f"{prefix} API 키가 없거나 올바르지 않습니다.\n"
            "→ 사이드바에서 키를 다시 저장하세요.\n"
            f"원문: {msg}"
        )
    return f"{prefix} Gemini 호출 실패\n원문: {msg}"


CHAT_SYSTEM_PROMPT = """당신은 택시 사업 업무 도우미입니다.
기사·차량 등록/수정/삭제, 배차일지(월별·차량 기준·일자 기입), 공문, 장부 관련 질문에 한국어로 짧고 명확히 답하세요.
배차일지 양식 열: 순서, 차번, 차종, 성명, 1~31일, 근무일수.
기사명·담당 차량은 한 달 안에도 바뀔 수 있다고 가정합니다.
지금은 대화·초안만 합니다. 공문 저장은 앱에서 사용자가 수정 후 「공문으로 저장」할 때 이루어집니다.
마스터·배차일지 변경도 미리보기 후 적용됩니다. 이미 적용됐다고 단정하지 마세요.
모르는 사실·법률·세무는 추측하지 말고, 확인이 필요하다고 말하세요.
표를 제안할 때는 날짜/차량번호/기사명 중심으로 보여 주세요.
"""


def chat_llm(
    messages: list[dict[str, str]],
    model: str | None = None,
    api_key: str | None = None,
    system: str | None = None,
) -> str:
    """멀티턴 채팅. messages: [{role: user|assistant, content: str}, ...] (마지막은 user)."""
    key = (api_key if api_key is not None else load_api_key()).strip()
    if not key:
        raise RuntimeError("Gemini API 키가 없습니다. 사이드바에서 키를 저장하세요.")
    if not messages:
        raise RuntimeError("메시지가 비어 있습니다.")
    m = model or DEFAULT_MODEL
    sys_prompt = (system or CHAT_SYSTEM_PROMPT).strip()

    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError(
            "google-generativeai 패키지가 없습니다. requirements 설치가 필요합니다."
        ) from e

    history: list[dict[str, Any]] = []
    for item in messages[:-1]:
        role = item.get("role", "user")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        gem_role = "user" if role == "user" else "model"
        history.append({"role": gem_role, "parts": [content]})

    last = messages[-1]
    if last.get("role") != "user":
        raise RuntimeError("마지막 메시지는 user 여야 합니다.")
    user_text = (last.get("content") or "").strip()
    if not user_text:
        raise RuntimeError("빈 메시지는 보낼 수 없습니다.")

    try:
        genai.configure(api_key=key)
        try:
            gm = genai.GenerativeModel(m, system_instruction=sys_prompt)
        except TypeError:
            # 구버전 SDK: 시스템 문구를 첫 컨텍스트로 주입
            gm = genai.GenerativeModel(m)
            if not history:
                user_text = f"{sys_prompt}\n\n사용자: {user_text}"
            else:
                history = [
                    {"role": "user", "parts": [sys_prompt]},
                    {
                        "role": "model",
                        "parts": ["알겠습니다. 택시 업무 도우미로 도와드리겠습니다."],
                    },
                    *history,
                ]
        chat = gm.start_chat(history=history)
        resp = chat.send_message(
            user_text,
            generation_config={"temperature": 0.5},
        )
        text = getattr(resp, "text", None)
        if not text:
            raise RuntimeError(f"Gemini 응답이 비어 있습니다: {resp}")
        return str(text).strip()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(friendly_error(e)) from e


def invoke_llm(
    prompt: str,
    model: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
) -> str:
    key = (api_key if api_key is not None else load_api_key()).strip()
    if not key:
        raise RuntimeError("Gemini API 키가 없습니다. 사이드바에서 키를 저장하세요.")
    m = model or DEFAULT_MODEL

    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError(
            "google-generativeai 패키지가 없습니다. requirements 설치가 필요합니다."
        ) from e

    try:
        genai.configure(api_key=key)
        gm = genai.GenerativeModel(m)
        resp = gm.generate_content(prompt, generation_config={"temperature": 0.2})
        text = getattr(resp, "text", None)
        if not text:
            raise RuntimeError(f"Gemini 응답이 비어 있습니다: {resp}")
        return str(text).strip()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(friendly_error(e)) from e


def test_connection(
    model: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
) -> tuple[bool, str]:
    m = model or DEFAULT_MODEL
    try:
        out = invoke_llm("Reply with exactly: OK", model=m, api_key=api_key)
        return True, f"연결 성공 (Gemini / {m}): {out[:80]}"
    except Exception as e:
        return False, str(e)


def gemini_status(model: str | None = None) -> dict[str, Any]:
    key = load_api_key()
    m = model or DEFAULT_MODEL
    return {
        "has_key": bool(key),
        "model": m,
        "provider": PROVIDER_GEMINI,
        "ready": bool(key),
        "message": "API 키 저장됨" if key else "API 키 없음",
    }
