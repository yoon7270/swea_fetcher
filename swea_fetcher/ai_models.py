"""풀이 유형 분류에 쓸 AI 엔진·모델 고르기 (M24.2). Qt·네트워크·subprocess 없음 (파일 읽기만 — 워커에서 부른다).

- 분류는 문제 수백 개를 읽히는 일이라 가벼운 모델을 쓴다. AI 코치의 엔진 설정(SWEA_AI_ENGINE)과는 **독립**이다
  (분류 모델은 SWEA_TYPE_MODEL: auto | codex:<slug> | claude:haiku). 전송 동의는 엔진별이라 동의한 엔진만 쓴다.
- Codex 모델 목록은 Codex CLI 가 만들어 두는 `<CODEX_HOME 또는 ~/.codex>/models_cache.json` (공개 모델 이름뿐) 에서만 읽는다.
  같은 폴더의 로그인 정보 파일은 열지 않는다. 파일이 없거나 깨져 있으면 빈 목록 — 자동 선택은 Codex 기본 모델(-m 없음)로 돌아간다.
- 자동 = 목록에서 "list" 로 보이는 모델 중 slug 에 `luna` 가 들어 있고 priority 숫자가 가장 작은 것. Claude 는 `haiku`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

log = logging.getLogger("swea_fetcher.ai_models")

MODELS_CACHE_NAME = "models_cache.json"  # 이 파일만 읽는다 (auth.json 등 다른 파일은 열지 않는다)
MAX_CACHE_BYTES = 2_000_000  # 이보다 크면 엉뚱한 파일로 보고 무시
LIGHT_KEYWORD = "luna"
CLAUDE_LIGHT = "haiku"
EFFORT = "low"  # 분류는 추론 강도 낮음으로 충분하다
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")  # 모델 slug 로 허용하는 모양 (argv 에 그대로 들어간다)
AUTO = "auto"
CODEX_PREFIX = "codex:"
CLAUDE_VALUE = f"claude:{CLAUDE_LIGHT}"
AUTO_LABEL = "자동 (가벼운 모델)"
CLAUDE_LABEL = "Claude Haiku"


@dataclass(frozen=True)
class CodexModel:
    slug: str
    name: str  # display_name (없으면 slug)
    priority: int = 999
    efforts: tuple[str, ...] = ()  # 지원하는 추론 강도 (비어 있으면 모름)


@dataclass(frozen=True)
class ClassifyModel:
    """분류 호출에 쓸 엔진과 모델. model/effort 가 빈 문자열이면 CLI 기본값을 쓴다 (옵션을 붙이지 않는다)."""

    engine: str  # "codex" | "claude"
    model: str = ""
    effort: str = ""

    @property
    def label(self) -> str:
        if self.engine == "claude":
            return CLAUDE_LABEL
        return self.model or "Codex 기본 모델"


def codex_home() -> Path:
    """Codex CLI 설정 폴더: 환경변수 CODEX_HOME, 없으면 ~/.codex."""
    env = os.environ.get("CODEX_HOME", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".codex"


def load_codex_models(home: Path | None = None) -> list[CodexModel]:
    """Codex 가 캐시해 둔 모델 목록 (보이는 것만, priority 순). 없거나 깨졌으면 [] — 예외 없음."""
    path = (Path(home) if home is not None else codex_home()) / MODELS_CACHE_NAME
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[CodexModel] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("visibility") != "list":
            continue
        slug = row.get("slug")
        if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug.strip()):
            continue
        prio = row.get("priority")
        levels = row.get("supported_reasoning_levels")
        efforts = tuple(
            e for e in ((lv.get("effort") if isinstance(lv, dict) else lv) for lv in (levels if isinstance(levels, list) else []))
            if isinstance(e, str)
        )
        name = row.get("display_name")
        out.append(CodexModel(
            slug.strip(), name.strip() if isinstance(name, str) and name.strip() else slug.strip(),
            prio if isinstance(prio, int) and not isinstance(prio, bool) else 999, efforts,
        ))
    return sorted(out, key=lambda m: (m.priority, m.slug))


def light_model(models: Sequence[CodexModel]) -> CodexModel | None:
    """자동 선택: slug 에 luna 가 든 모델 중 priority 가 가장 작은 것. 없으면 None (Codex 기본 모델)."""
    hits = [m for m in models if LIGHT_KEYWORD in m.slug.lower()]
    return min(hits, key=lambda m: (m.priority, m.slug)) if hits else None


def parse_pref(value: str) -> tuple[str, str]:
    """SWEA_TYPE_MODEL → (엔진, 모델). 알 수 없는 값은 ("", "") = 자동."""
    v = (value or "").strip()
    if v.startswith(CODEX_PREFIX) and _SLUG_RE.fullmatch(v[len(CODEX_PREFIX):].strip()):
        return "codex", v[len(CODEX_PREFIX):].strip()
    if v == CLAUDE_VALUE:
        return "claude", CLAUDE_LIGHT
    return "", ""


def choose(pref: str, available: Sequence[str], models: Sequence[CodexModel]) -> ClassifyModel | None:
    """분류에 쓸 엔진·모델. available 은 설치돼 있고 전송에 동의한 엔진 이름 (없으면 None).

    고른 엔진이 없으면 다른 쪽 가벼운 모델로 (동의한 엔진 안에서만). 고른 Codex 모델이 목록에서 사라졌으면 자동 선택으로.
    """
    want_engine, want_model = parse_pref(pref)
    order = [n for n in ("codex", "claude") if n in available]
    if want_engine in order:
        order.remove(want_engine)
        order.insert(0, want_engine)
    if not order:
        return None
    if order[0] == "claude":
        return ClassifyModel("claude", CLAUDE_LIGHT)
    picked = None
    if want_engine == "codex":
        known = next((m for m in models if m.slug == want_model), None)
        picked = known or (CodexModel(want_model, want_model) if not models else None)
    picked = picked or light_model(models)
    if picked is None:
        return ClassifyModel("codex", "", EFFORT)  # 기본 모델 (-m 없음)
    effort = EFFORT if (not picked.efforts or EFFORT in picked.efforts) else ""
    return ClassifyModel("codex", picked.slug, effort)


def options(models: Sequence[CodexModel], *, claude_found: bool, current: str = AUTO) -> list[tuple[str, str]]:
    """설정 콤보 항목 [(값, 표시 이름)]: 자동 · Codex 목록 모델 · (Claude 가 있으면) Claude Haiku.
    저장된 값이 목록에 없으면 (모델이 사라졌거나 Claude 미설치) 그 값도 뒤에 남겨 설정이 조용히 바뀌지 않게 한다."""
    out = [(AUTO, AUTO_LABEL)] + [(f"{CODEX_PREFIX}{m.slug}", m.name) for m in models]
    if claude_found:
        out.append((CLAUDE_VALUE, CLAUDE_LABEL))
    if current and current != AUTO and current not in {v for v, _t in out}:
        eng, model = parse_pref(current)
        if eng:
            out.append((current, f"{CLAUDE_LABEL} (설치 안 됨)" if eng == "claude" else f"{model} (목록에 없음)"))
    return out
