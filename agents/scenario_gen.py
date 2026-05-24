import re
import anthropic
from state import ExamState
from prompts.templates import SCENARIO_GENERATOR
from utils import cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_KR_NUM = {
    "한": 1, "하나": 1, "일": 1,
    "두": 2, "둘": 2, "이": 2,
    "세": 3, "셋": 3, "삼": 3,
    "네": 4, "넷": 4, "사": 4,
    "다섯": 5, "오": 5,
    "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7,
    "여덟": 8, "팔": 8,
    "아홉": 9, "구": 9,
    "열": 10, "십": 10,
}


def _parse_group_config(additional: str):
    if not additional or "대문제" not in additional:
        return None, None

    def _to_int(token):
        return int(token) if token.isdigit() else _KR_NUM.get(token)

    size_m  = re.search(r'(\d+|\w+)\s*문제씩', additional)
    count_m = re.search(r'(\d+|\w+)\s*개(?:의)?\s*대문제', additional)
    group_size  = _to_int(size_m.group(1))  if size_m  else 2
    group_count = _to_int(count_m.group(1)) if count_m else None
    return group_size, group_count


def _generate_scenario(questions: list[dict]) -> str:
    subq_text = "\n".join(
        f"{i+1}. [{q.get('type','?')}] {q.get('content', '')[:200]}"
        for i, q in enumerate(questions)
    )
    response = cached_create(
        _client,
        model=config.MODEL,
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": SCENARIO_GENERATOR.format(subquestions=subq_text),
        }],
    )
    logger.record_tokens("ScenarioGen", response.usage)
    return response.content[0].text.strip()


def run(state: ExamState) -> dict:
    logger.section("STEP 8.6 — Shared Scenario Generation")

    requirements = state.get("requirements", {})
    additional   = requirements.get("additional_requirements", "") or ""
    group_size, group_count = _parse_group_config(additional)

    if not group_size or not group_count:
        logger.log("ScenarioGen", "대문제 설정 없음 — 스킵")
        return {}

    passed = state.get("passed_questions", [])
    ordered = (
        [q for q in passed if q.get("type") == "concept"] +
        [q for q in passed if q.get("type") == "case"]
    )

    group_scenarios: dict[int, str] = {}

    for g in range(group_count):
        chunk = ordered[g * group_size:(g + 1) * group_size]
        if not chunk:
            break

        if len(chunk) < 2:
            logger.log("ScenarioGen", f"  대문제 {g+1}: 소문항 1개 → 공통 시나리오 생략")
            continue

        logger.log("ScenarioGen", f"  대문제 {g+1} 공통 시나리오 생성 중... "
                                  f"({', '.join(q.get('topic','?') for q in chunk)})")
        scenario = _generate_scenario(chunk)
        group_scenarios[g] = scenario
        logger.log("ScenarioGen", f"  ✅ 대문제 {g+1} 시나리오: {scenario[:60]}...")

    return {"group_scenarios": group_scenarios}
