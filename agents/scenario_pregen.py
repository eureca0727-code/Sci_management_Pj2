import anthropic
from state import ExamState
from tools.rag import retrieve, format_context
from utils import cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_PREGEN_PROMPT = """
당신은 시험 문제 시나리오 설계 전문가입니다.
다음 단원들의 방법론을 모두 적용할 수 있는 공통 기업 시나리오를 작성하십시오.

묶을 단원: {topic_names}

[강의자료 발췌 — 방법론 파악용]
{context}

조건:
- 실제 기업명·팀명·상황을 포함한 구체적이고 현실감 있는 시나리오
- 위 단원들의 방법론이 모두 자연스럽게 적용될 수 있는 하나의 상황
- 배경 맥락만 제공 — 질문 없음, 정답 힌트 없음
- 150~250자 평문으로만 작성 (JSON·항목 나열 금지)
- 시나리오 텍스트만 반환, 다른 설명 일절 금지
""".strip()


def run(state: ExamState) -> dict:
    """Generate one shared scenario per question group BEFORE Professor B writes sub-questions.
    This ensures all sub-questions in a group are grounded in the same realistic context."""
    logger.section("STEP 2.6 — Scenario Pre-Generation")

    group_config = state.get("group_config", [])
    if not group_config:
        logger.log("ScenarioPregen", "그룹 설정 없음 — 스킵")
        return {}

    blueprint = state.get("blueprint", {})
    group_scenarios: dict[int, str] = {}

    for gc in group_config:
        gid = gc["group_id"]
        topic_names = gc["topic_names"]

        # Retrieve methodology slides for all topics in the group to inform scenario creation
        search_query = " ".join(topic_names) + " 방법론 절차 분석 적용"
        slides = retrieve(search_query, top_k=config.TOP_K)
        context = format_context(slides)

        logger.log("ScenarioPregen",
                   f"  그룹 {gid + 1} 시나리오 생성 중: {', '.join(topic_names)}")

        response = cached_create(
            _client,
            model=config.MODEL,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": _PREGEN_PROMPT.format(
                    topic_names=", ".join(topic_names),
                    context=context,
                ),
            }],
        )
        logger.record_tokens("ScenarioPregen", response.usage)
        scenario = response.content[0].text.strip()
        group_scenarios[gid] = scenario
        logger.log("ScenarioPregen", f"  ✅ 그룹 {gid + 1}: {scenario[:80]}...")

    return {"group_scenarios": group_scenarios}
