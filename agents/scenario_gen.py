import anthropic
from state import ExamState
from prompts.templates import SCENARIO_GENERATOR
from utils import cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


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

    group_config = state.get("group_config", [])
    if not group_config:
        logger.log("ScenarioGen", "그룹 설정 없음 — 스킵")
        return {}

    passed = state.get("passed_questions", [])
    topic_to_q: dict[str, list] = {}
    for q in passed:
        topic_to_q.setdefault(q.get("topic", ""), []).append(q)

    group_scenarios: dict[int, str] = {}

    for gc in group_config:
        gid = gc["group_id"]
        topic_names = gc["topic_names"]

        # 해당 그룹의 질문들 수집
        chunk = []
        for name in topic_names:
            chunk.extend(topic_to_q.get(name, []))

        if len(chunk) < 2:
            logger.log("ScenarioGen", f"  그룹 {gid+1}: 문제 {len(chunk)}개 → 시나리오 생략")
            continue

        logger.log("ScenarioGen", f"  그룹 {gid+1} 공통 시나리오 생성 중... "
                                  f"({', '.join(topic_names)})")
        scenario = _generate_scenario(chunk)
        group_scenarios[gid] = scenario
        logger.log("ScenarioGen", f"  ✅ 그룹 {gid+1}: {scenario[:60]}...")

    return {"group_scenarios": group_scenarios}
