import re
import json
import anthropic
from state import ExamState
from prompts.templates import PROFESSOR_SHORT_ANSWER, PROFESSOR_ESSAY, PROFESSOR_APPLICATION
from tools.rag import retrieve, format_context
from utils import parse_json, cached_create
import config
import logger

_MULTI_SUB = re.compile(r'\(문제\s*[1-9]|\(소\s*[1-9]|^문제\s*[1-9][).]\s', re.MULTILINE)


def _normalize(q: dict) -> dict:
    """LLM이 문자열 필드를 dict/list로 줄 경우 안전하게 변환."""
    for key in ("content", "intended_answer", "methodology", "topic", "scenario"):
        val = q.get(key)
        if val is not None and not isinstance(val, str):
            q[key] = json.dumps(val, ensure_ascii=False)
    return q


def _is_valid(q: dict) -> bool:
    """content가 비어있거나 JSON/편집용 메타 표현이 섞인 문제 거름."""
    content = q.get("content", "").strip()

    if not content:
        return False

    if content.startswith("{") or content.startswith("["):
        return False

    forbidden = ("【대문제", "[공통 시나리오]", "[소문항", "공통 시나리오", "소문항")
    if any(token in content for token in forbidden):
        return False

    if content.startswith("대문제"):
        return False

    # 복수 소문항 구조 금지: (문제 1), (문제 2), (소1) 등이 있으면 단일 문제가 아님
    if _MULTI_SUB.search(content):
        return False

    return True

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_INTERNAL_KEYS = {"group_id"}  # 교수에게 노출하지 않을 필드


def _topic_for_professor(topic: dict) -> dict:
    """group_id 등 편집 메타 필드를 제거하고 출제 지시용 topic 반환."""
    return {k: v for k, v in topic.items() if k not in _INTERNAL_KEYS}


def _adaptive_top_k(retry_count: int, fill_count: int = 0) -> int:
    """재출제·fill 횟수에 비례해 TOP_K를 늘림 (토큰 절약 + 근거 확장 + 캐시 키 변경)."""
    return min(config.TOP_K + (retry_count + fill_count) * 2, config.TOP_K_MAX)


def _generate_short_answer(blueprint: dict, topic: dict, failure_patterns: list,
                           additional_requirements: str = "",
                           retry_count: int = 0,
                           topic_failure_reason: str = "") -> list:
    slides = retrieve(topic["name"], top_k=_adaptive_top_k(retry_count))
    context = format_context(slides)

    prompt = PROFESSOR_SHORT_ANSWER.format(
        blueprint_section=json.dumps(_topic_for_professor(topic), ensure_ascii=False),
        failure_patterns=failure_patterns or "없음",
        additional_requirements=additional_requirements or "없음",
        topic_failure_reason=topic_failure_reason or "없음",
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
    raw = [_normalize(q) for q in raw if isinstance(q, dict) and _is_valid(q)]
    for q in raw:
        q["professor"] = "A"
        q["type"] = "short_answer"
    return raw


def _generate_essay(blueprint: dict, topic: dict, failure_patterns: list,
                    additional_requirements: str = "",
                    retry_count: int = 0,
                    topic_failure_reason: str = "") -> list:
    slides = retrieve(topic["name"], top_k=_adaptive_top_k(retry_count))
    context = format_context(slides)

    prompt = PROFESSOR_ESSAY.format(
        blueprint_section=json.dumps(_topic_for_professor(topic), ensure_ascii=False),
        failure_patterns=failure_patterns or "없음",
        additional_requirements=additional_requirements or "없음",
        topic_failure_reason=topic_failure_reason or "없음",
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
    raw = [_normalize(q) for q in raw if isinstance(q, dict) and _is_valid(q)]
    for q in raw:
        q["professor"] = "A"
        q["type"] = "essay"
    return raw


def _generate_application(blueprint: dict, topic: dict, failure_patterns: list,
                          additional_requirements: str = "",
                          retry_count: int = 0,
                          topic_failure_reason: str = "",
                          shared_scenario: str = "") -> list:
    top_k = _adaptive_top_k(retry_count)
    methodology_slides = retrieve(f"{topic['name']} 방법론 절차 분석 framework", top_k=top_k)
    methodology_context = format_context(methodology_slides)

    prompt = PROFESSOR_APPLICATION.format(
        methodology_context=methodology_context,
        blueprint_section=json.dumps(_topic_for_professor(topic), ensure_ascii=False),
        failure_patterns=failure_patterns or "없음",
        additional_requirements=additional_requirements or "없음",
        topic_failure_reason=topic_failure_reason or "없음",
        shared_scenario=shared_scenario or "없음",
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
    if raw is None:
        logger.log("ProfB", "  ⚠️  parse_json 실패 — LLM 응답을 JSON으로 파싱 불가")
        return []
    if isinstance(raw, dict):
        raw = [raw]
    before_valid = len([q for q in raw if isinstance(q, dict)])
    raw = [_normalize(q) for q in raw if isinstance(q, dict) and _is_valid(q)]
    if len(raw) < before_valid:
        logger.log("ProfB", f"  ⚠️  _is_valid 필터: {before_valid}개 → {len(raw)}개 (content 오류)")
    for q in raw:
        if not (q.get("methodology") and str(q["methodology"]).strip()):
            logger.log("ProfB", f"  ⚠️  methodology 누락 — 빈 값으로 통과: {q.get('content','')[:60]}")
            q["methodology"] = ""
    for q in raw:
        q["professor"] = "B"
        q["type"] = "application"
    return raw


def run_professor_a(state: ExamState) -> dict:
    logger.section("STEP 3a — Professor A (단답형 + 서술형)")
    blueprint = state["blueprint"]
    failure_patterns = state.get("failure_patterns", [])
    additional = state["requirements"].get("additional_requirements", "") or ""
    retry_count = state.get("retry_count", 0)
    fill_count = state.get("fill_count", 0)
    topic_failure_reasons = state.get("_topic_failure_reasons", {})
    top_k = _adaptive_top_k(retry_count, fill_count)
    if retry_count > 0 or fill_count > 0:
        logger.log("ProfA", f"재출제 {retry_count}회차 / fill {fill_count}회차 → TOP_K={top_k}")
    drafts = []

    for topic in blueprint["topics"]:
        sa_count = topic.get("short_answer_questions", 0)
        essay_count = topic.get("essay_questions", 0)

        if sa_count > 0:
            reason = topic_failure_reasons.get(f"{topic['name']}:short_answer", "")
            if reason:
                logger.log("ProfA", f"  📋 실패 피드백 적용: {reason[:80]}")
            logger.log("ProfA", f"단원 '{topic['name']}' 단답형 {sa_count}개 출제 중...")
            questions = _generate_short_answer(blueprint, topic, failure_patterns, additional, retry_count + fill_count, reason)
            if len(questions) > sa_count:
                logger.log("ProfA", f"  ✂️  단답형 {len(questions)}개 → {sa_count}개로 trim")
                questions = questions[:sa_count]
            for q in questions:
                q["topic"] = topic["name"]
                logger.log("ProfA", f"  → [단답형] {q.get('content','')[:70]}...")
            drafts.extend(questions)

        if essay_count > 0:
            reason = topic_failure_reasons.get(f"{topic['name']}:essay", "")
            if reason:
                logger.log("ProfA", f"  📋 실패 피드백 적용: {reason[:80]}")
            logger.log("ProfA", f"단원 '{topic['name']}' 서술형 {essay_count}개 출제 중...")
            questions = _generate_essay(blueprint, topic, failure_patterns, additional, retry_count + fill_count, reason)
            if len(questions) > essay_count:
                logger.log("ProfA", f"  ✂️  서술형 {len(questions)}개 → {essay_count}개로 trim")
                questions = questions[:essay_count]
            for q in questions:
                q["topic"] = topic["name"]
                logger.log("ProfA", f"  → [서술형] {q.get('content','')[:70]}...")
            drafts.extend(questions)

    logger.log("ProfA", f"✅ 단답형·서술형 초안 {len(drafts)}개 완성")
    return {"_draft_a": drafts}


def run_professor_b(state: ExamState) -> dict:
    logger.section("STEP 3b — Professor B (사례적용형)")
    blueprint = state["blueprint"]
    failure_patterns = state.get("failure_patterns", [])
    additional = state["requirements"].get("additional_requirements", "") or ""
    retry_count = state.get("retry_count", 0)
    fill_count = state.get("fill_count", 0)
    topic_failure_reasons = state.get("_topic_failure_reasons", {})
    group_scenarios = state.get("group_scenarios", {})
    top_k = _adaptive_top_k(retry_count, fill_count)
    if retry_count > 0 or fill_count > 0:
        logger.log("ProfB", f"재출제 {retry_count}회차 / fill {fill_count}회차 → TOP_K={top_k}")
    drafts = []

    for topic in blueprint["topics"]:
        app_count = topic.get("application_questions", 0)
        if app_count > 0:
            reason = topic_failure_reasons.get(f"{topic['name']}:application", "")
            if reason:
                logger.log("ProfB", f"  📋 실패 피드백 적용: {reason[:80]}")
            gid = topic.get("group_id")
            if gid is not None:
                gid = int(gid)  # LLM이 string "0"으로 반환해도 int 키와 매칭되게
            shared = group_scenarios.get(gid, "") if gid is not None else ""
            if shared:
                logger.log("ProfB", f"  📌 공통 시나리오 주입: {shared[:60]}...")
            logger.log("ProfB", f"단원 '{topic['name']}' 사례적용형 {app_count}개 출제 중...")
            questions = _generate_application(blueprint, topic, failure_patterns, additional,
                                              retry_count + fill_count, reason,
                                              shared_scenario=shared)
            if len(questions) > app_count:
                logger.log("ProfB", f"  ✂️  사례적용형 {len(questions)}개 → {app_count}개로 trim")
                questions = questions[:app_count]
            for q in questions:
                q["topic"] = topic["name"]
                logger.log("ProfB", f"  → [사례적용형] {q.get('content','')[:70]}...")
                logger.log("ProfB", f"     방법론: {q.get('methodology') or '(미제공)'}")
            drafts.extend(questions)

    logger.log("ProfB", f"✅ 사례적용형 초안 {len(drafts)}개 완성")
    return {"_draft_b": drafts}
