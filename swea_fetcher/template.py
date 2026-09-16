"""{num}.py 뼈대 렌더링. 기존 풀이 저장소의 패턴을 그대로 따른다."""

from __future__ import annotations

from .models import ProblemInfo

SKELETON = '''# {header}
import sys
sys.stdin = open("{input_name}", "r")
T = int(input())
for test_case in range(1, T + 1):
    pass
'''


def render_skeleton(info: ProblemInfo, input_name: str) -> str:
    """첫 줄 주석은 `# {num}. {title}`, title 이 비어 있으면 `# {num}.`"""
    num = info.num if info.num is not None else ""
    title = (info.title or "").strip()
    header = f"{num}. {title}" if title else f"{num}."
    return SKELETON.format(header=header, input_name=input_name)
