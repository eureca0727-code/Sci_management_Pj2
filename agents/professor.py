import json
import anthropic
from state import ExamState
from prompts.templates import PROFESSOR_A, PROFESSOR_B
from tools.rag import retrieve, format_context
from utils import parse_json, cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _generate_concept(blueprint: dict, topic: dict, failure_patterns: list) -> list:
    slides = retrieve(topic["name"], top_k=config.TOP_K)
    context = format_context(slides)

    prompt = PROFESSOR_A.format(
        blueprint_section=json.dumps(topic, ensure_ascii=False),
        failure_patterns=failure_patterns or "없음",
    )

    response = cached_create(
        _client,
        model=config.MODEL,
        max_tokens=4000,
        system=prompt,
        messages=[{"role": "user", "content": f"강의자료 발췌:\n{context}"}],
    )
    logger.record_tokens("ProfA", response.usage)

    raw = parse_json(response.content[0].text)
    if isinstance(raw, dict):
        raw = [raw]
    raw = [q for q in raw if isinstance(q, dict)]
    for q in raw:
        q["professor"] = "A"
    return raw


def _generate_case(blueprint: dict, topic: dict, failure_patterns: list) -> list:
    methodology_slides = retrieve(f"{topic['name']} 방법론 절차 분석 framework", top_k=config.TOP_K)
    methodology_context = format_context(methodology_slides)

    prompt = PROFESSOR_B.format(
        methodology_context=methodology_context,
        blueprint_section=json.dumps(topic, ensure_ascii=False),
        failure_patterns=failure_patterns or "없음",
    )

    response = cached_create(
        _client,
        model=config.MODEL,
        max_tokens=4000,
        system=prompt,
        messages=[{"role": "user", "content": "위 사례와 방법론을 바탕으로 문제를 작성하시오."}],
    )
    logger.record_tokens("ProfB", response.usage)

    raw = parse_json(response.content[0].text)
    if isinstance(raw, dict):
        raw = [raw]
    raw = [q for q in raw if isinstance(q, dict)]
    for q in raw:
        q["professor"] = "B"
    return raw


def run_professor_a(state: ExamState) -> dict:
    logger.section("STEP 3a — Professor A (교과서 충실파)")
    blueprint = state["blueprint"]
    failure_patterns = state.get("failure_patterns", [])
    drafts = []

    for topic in blueprint["topics"]:
        if topic["concept_questions"] > 0:
            logger.log("ProfA", f"단원 '{topic['name']}' 개념 문제 {topic['concept_questions']}개 출제 중...")
            questions = _generate_concept(blueprint, topic, failure_patterns)
            for q in questions:
                logger.log("ProfA", f"  → {q.get('content','')[:70]}...")
            drafts.extend(questions)

    logger.log("ProfA", f"✅ 개념 문제 초안 {len(drafts)}개 완성")
    return {"_draft_a": drafts}


def run_professor_b(state: ExamState) -> dict:
    logger.section("STEP 3b — Professor B (응용 확장파)")
    blueprint = state["blueprint"]
    failure_patterns = state.get("failure_patterns", [])
    drafts = []

    for topic in blueprint["topics"]:
        if topic["case_questions"] > 0:
            logger.log("ProfB", f"단원 '{topic['name']}' 사례 문제 {topic['case_questions']}개 출제 중...")
            questions = _generate_case(blueprint, topic, failure_patterns)
            for q in questions:
                logger.log("ProfB", f"  → {q.get('content','')[:70]}...")
                logger.log("ProfB", f"     방법론: {q.get('methodology', '?')}")
            drafts.extend(questions)

    logger.log("ProfB", f"✅ 사례 문제 초안 {len(drafts)}개 완성 (실제 사례 기반)")
    return {"_draft_b": drafts}
