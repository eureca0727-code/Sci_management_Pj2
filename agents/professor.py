import json
import anthropic
from state import ExamState
from prompts.templates import PROFESSOR_A, PROFESSOR_B
from tools.rag import retrieve, format_context
from tools.web_search import search_cases, format_cases
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

    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=2000,
        system=prompt,
        messages=[{"role": "user", "content": f"강의자료 발췌:\n{context}"}],
    )
    logger.record_tokens("ProfA", response.usage)

    raw = json.loads(response.content[0].text)
    if isinstance(raw, dict):
        raw = [raw]
    for q in raw:
        q["professor"] = "A"
    return raw


def _generate_case(blueprint: dict, topic: dict, failure_patterns: list) -> list:
    # 1. 강의자료에서 방법론 추출
    methodology_slides = retrieve(f"{topic['name']} 방법론 절차 분석 framework", top_k=config.TOP_K)
    methodology_context = format_context(methodology_slides)

    # 2. 방법론 키워드를 뽑아서 웹 검색
    keyword_resp = _client.messages.create(
        model=config.MODEL,
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": (
                f"아래 강의 내용에서 핵심 방법론 이름 하나를 영어로 추출하시오. 단어만 반환.\n\n{methodology_context[:500]}"
            ),
        }],
    )
    logger.record_tokens("ProfB", keyword_resp.usage)
    methodology_keyword = keyword_resp.content[0].text.strip().split("\n")[0]
    logger.log("ProfB", f"  방법론 키워드: '{methodology_keyword}' → 웹 검색 중...")

    # 3. 실제 사례 검색
    search_results = search_cases(methodology_keyword, topic["name"], max_results=3)
    real_cases = format_cases(search_results)

    if search_results:
        logger.log("ProfB", f"  실제 사례 {len(search_results)}건 수집 완료")
        for r in search_results:
            logger.log("ProfB", f"    - {r.get('title', '')[:60]}")
    else:
        logger.log("ProfB", "  ⚠️  웹 검색 결과 없음 — 슬라이드 내 사례로 대체")

    # 4. 문제 생성
    prompt = PROFESSOR_B.format(
        methodology_context=methodology_context,
        real_cases=real_cases,
        blueprint_section=json.dumps(topic, ensure_ascii=False),
        failure_patterns=failure_patterns or "없음",
    )

    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=2000,
        system=prompt,
        messages=[{"role": "user", "content": "위 사례와 방법론을 바탕으로 문제를 작성하시오."}],
    )
    logger.record_tokens("ProfB", response.usage)

    raw = json.loads(response.content[0].text)
    if isinstance(raw, dict):
        raw = [raw]
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
                logger.log("ProfA", f"  → {q['content'][:70]}...")
            drafts.extend(questions)

    logger.log("ProfA", f"✅ 개념 문제 초안 {len(drafts)}개 완성")
    return {"_draft_a": drafts}


def run_professor_b(state: ExamState) -> dict:
    logger.section("STEP 3b — Professor B (응용 확장파 + 실제 사례 검색)")
    blueprint = state["blueprint"]
    failure_patterns = state.get("failure_patterns", [])
    drafts = []

    for topic in blueprint["topics"]:
        if topic["case_questions"] > 0:
            logger.log("ProfB", f"단원 '{topic['name']}' 사례 문제 {topic['case_questions']}개 출제 중...")
            questions = _generate_case(blueprint, topic, failure_patterns)
            for q in questions:
                logger.log("ProfB", f"  → {q['content'][:70]}...")
                logger.log("ProfB", f"     방법론: {q.get('methodology', '?')}")
            drafts.extend(questions)

    logger.log("ProfB", f"✅ 사례 문제 초안 {len(drafts)}개 완성 (실제 사례 기반)")
    return {"_draft_b": drafts}
