import json
import anthropic
from state import ExamState, Question
from prompts.templates import CHAIR_BLUEPRINT, CHAIR_CONSENSUS
from tools.rag import retrieve, retrieve_per_source, format_context
from utils import parse_json, cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def run_blueprint(state: ExamState) -> dict:
    logger.section("STEP 2 — Blueprint Generation (Chair)")
    logger.log("Chair", "강의자료 분석 중...")

    req = state["requirements"]
    slides = retrieve_per_source("목차 단원 주요 개념 핵심 내용", chunks_per_source=2)
    context = format_context(slides)

    logger.log("Chair", f"전체 PDF {len(set(s for s,_ in slides))}개 소스 × 2청크 = {len(slides)}개 슬라이드 검색 완료 → LLM 블루프린트 생성 중...")

    user_topics = req.get("user_topics")
    if user_topics:
        constraint_text = (
            "\n\n[사용자 지정 단원 구성 — 반드시 준수]\n"
            + json.dumps(user_topics, ensure_ascii=False)
            + "\n위 단원명과 concept_questions/case_questions 수를 그대로 사용하십시오."
            " slides 범위·weight·difficulty만 강의자료에서 추론하십시오."
        )
    else:
        constraint_text = ""

    additional = req.get("additional_requirements")
    if additional:
        constraint_text += f"\n\n[추가 요구사항 — 반드시 반영]\n{additional}"

    response = cached_create(
        _client,
        model=config.MODEL,
        max_tokens=1500,
        system=CHAIR_BLUEPRINT,
        messages=[{
            "role": "user",
            "content": (
                f"강의자료 발췌:\n{context}\n\n"
                f"출제 요구사항:\n{json.dumps(req, ensure_ascii=False)}"
                + constraint_text
            ),
        }],
    )

    logger.record_tokens("Chair", response.usage)
    blueprint = parse_json(response.content[0].text)

    topics = blueprint.get("topics", [])
    logger.log("Chair", f"✅ 블루프린트 확정: {len(topics)}개 단원")
    for t in topics:
        weight = t.get("weight", 0)
        print(f"         단원: {t.get('name','?')}  "
              f"배점비율={weight:.0%}  "
              f"개념{t.get('concept_questions',0)}문항 / 사례{t.get('case_questions',0)}문항  "
              f"난이도={t.get('difficulty','?')}")

    return {"blueprint": blueprint}


def run_consensus(state: ExamState) -> dict:
    logger.section("STEP 5 — Chair Consensus (교수 회의 합의)")
    prof_a = state.get("_draft_a", [])
    prof_b = state.get("_draft_b", [])
    failure_patterns = state.get("failure_patterns", [])

    # Combine drafts and assign sequential indices for index-based selection
    all_drafts = list(prof_a) + list(prof_b)
    logger.log("Chair", f"A 초안 {len(prof_a)}개 + B 초안 {len(prof_b)}개 검토 중...")
    if not all_drafts:
        logger.log("Chair", "⚠️  초안이 없어 합의 생략")
        return {"questions": [], "_draft_a": [], "_draft_b": []}

    if failure_patterns:
        logger.log("Chair", f"⚠️  회피 패턴 {len(failure_patterns)}개 적용 중")

    # Send numbered draft list so Claude can reference by index
    numbered_drafts = [
        {"index": i, **{k: v for k, v in q.items()}}
        for i, q in enumerate(all_drafts)
    ]

    response = cached_create(
        _client,
        model=config.MODEL,
        max_tokens=3000,
        system=CHAIR_CONSENSUS,
        messages=[{
            "role": "user",
            "content": (
                f"블루프린트:\n{json.dumps(state['blueprint'], ensure_ascii=False)}\n\n"
                f"문제 초안 목록 (index 기준으로 채택/탈락 결정):\n"
                f"{json.dumps(numbered_drafts, ensure_ascii=False)}\n\n"
                f"회피 실패 패턴:\n{failure_patterns}"
            ),
        }],
    )

    logger.record_tokens("Chair", response.usage)
    raw = parse_json(response.content[0].text)

    kept_entries = []
    rejected_entries = []
    if isinstance(raw, dict):
        kept_entries = raw.get("kept", [])
        rejected_entries = raw.get("rejected", [])
    elif isinstance(raw, list):
        kept_entries = raw

    # Offset IDs so retried questions never collide with previously-passed IDs
    id_offset = len(state.get("passed_questions", []))

    # Select original draft questions by index
    questions: list[Question] = []
    for entry in kept_entries:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        reason = entry.get("reason", "")
        if idx is None or not isinstance(idx, int) or idx >= len(all_drafts):
            continue
        q = dict(all_drafts[idx])
        q["id"] = f"Q{id_offset + len(questions) + 1:02d}"
        q.setdefault("methodology", None)
        questions.append(q)
        logger.show_question(q)
        if reason:
            logger.log("Chair", f"  ✅ 채택: {reason}")

    if rejected_entries:
        logger.log("Chair", f"\n  [탈락 문제]")
        for r in rejected_entries:
            if not isinstance(r, dict):
                continue
            idx = r.get("index")
            reason = r.get("reason", "?")
            label = all_drafts[idx].get("content", "?")[:50] if isinstance(idx, int) and idx < len(all_drafts) else "?"
            logger.log("Chair", f"  ❌ [{idx}] {label}... — {reason}")

    logger.log("Chair", f"✅ 합의 완료: 채택 {len(questions)}개 / 탈락 {len(rejected_entries)}개")

    return {"questions": questions, "_draft_a": [], "_draft_b": []}
