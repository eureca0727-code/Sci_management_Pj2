from collections import defaultdict
from langgraph.graph import StateGraph, END
from state import ExamState
from agents import indexer, chair, professor, student, judge, answer_gen, human_review, scenario_gen, blueprint_review, compiler
import config
import logger


# ── 노드 함수 래퍼 ────────────────────────────────────────────────

def node_index(state: ExamState) -> dict:
    return indexer.run(state)


def node_blueprint(state: ExamState) -> dict:
    return chair.run_blueprint(state)


def node_blueprint_review(state: ExamState) -> dict:
    return blueprint_review.run(state)


def node_professor_a(state: ExamState) -> dict:
    return professor.run_professor_a(state)


def node_professor_b(state: ExamState) -> dict:
    return professor.run_professor_b(state)


def node_consensus(state: ExamState) -> dict:
    return chair.run_consensus(state)


def node_student(state: ExamState) -> dict:
    return student.run(state)


def node_judge(state: ExamState) -> dict:
    return judge.run(state)


def _find_blueprint_topic(failed_q: dict, blueprint_topics: list) -> dict | None:
    """topic명 우선으로 블루프린트 단원 찾기. 실패 시 source_slides 범위 폴백."""
    name = failed_q.get("topic", "")
    for t in blueprint_topics:
        if t.get("name", "") == name:
            return t

    # source_slides는 PDF별 슬라이드 번호 충돌 가능성이 있어 폴백으로만 사용
    source_slides = [int(s) for s in failed_q.get("source_slides", []) if s is not None]
    if source_slides:
        for t in blueprint_topics:
            r = t.get("slide_range", [])
            if len(r) >= 2:
                start, end = int(r[0]), int(r[1])
                if any(start <= s <= end for s in source_slides):
                    return t
    return None
    
def _full_blueprint(state: ExamState) -> dict:
    """fill/retry로 state['blueprint']가 부분 blueprint로 바뀌어도 원본 blueprint를 보존."""
    return state.get("_full_blueprint") or state.get("blueprint") or {"topics": []}

def node_retry_prepare(state: ExamState) -> dict:
    """재출제 전 상태 정리 + 실패 문제 기반 blueprint 필터링 (문제별 횟수 추적)."""
    retries = state.get("retry_count", 0)
    failed = state.get("failed_questions", [])
    blueprint_topics = state["blueprint"].get("topics", [])
    fail_counts = dict(state.get("question_fail_counts", {}))

    # 실패 횟수 누적 (로깅용)
    for q in failed:
        key = f"{q.get('topic', '')}:{q.get('type', '')}"
        fail_counts[key] = fail_counts.get(key, 0) + 1

    logger.section(f"RETRY {retries + 1}/{config.MAX_RETRIES} — 재출제 준비")
    logger.log("Graph", f"실패 문제 {len(failed)}개 전부 재출제")

    # source_slides 기준으로 블루프린트 단원 찾아 재출제 수량 집계
    topic_counts: dict[str, dict] = defaultdict(
        lambda: {"short_answer_questions": 0, "essay_questions": 0, "application_questions": 0}
    )
    topic_by_name: dict[str, dict] = {}
    unmatched = []

    for q in failed:
        matched = _find_blueprint_topic(q, blueprint_topics)
        if matched is None:
            unmatched.append(q.get("id", "?"))
            continue
        name = matched["name"]
        topic_by_name[name] = matched
        qtype = q.get("type", "")
        if qtype == "short_answer":
            topic_counts[name]["short_answer_questions"] += 1
        elif qtype == "essay":
            topic_counts[name]["essay_questions"] += 1
        else:
            topic_counts[name]["application_questions"] += 1

    if unmatched:
        logger.log("Graph", f"  ⚠️  블루프린트 매칭 실패 (건너뜀): {unmatched}")

    retry_topics = [
        {**topic_by_name[name], **counts}
        for name, counts in topic_counts.items()
    ]
    filtered_blueprint = {**state["blueprint"], "topics": retry_topics}

    for t in retry_topics:
        logger.log("Graph", f"  재출제: '{t.get('name','?')}' — "
                            f"단답형 {t.get('short_answer_questions',0)}개 / "
                            f"서술형 {t.get('essay_questions',0)}개 / "
                            f"사례적용형 {t.get('application_questions',0)}개")

    return {
        "retry_count": retries + 1,
        "question_fail_counts": fail_counts,
        "blueprint": filtered_blueprint,
        "_draft_a": [],
        "_draft_b": [],
        "questions": [],
        "judge_results": [],
    }


_MAX_FILL = config.MAX_FILL  # Chair 부족분 보충 최대 시도 횟수

def _topic_type_counts(questions: list[dict]) -> dict[tuple[str, str], int]:
    counts = defaultdict(int)
    for q in questions:
        counts[(q.get("topic", ""), q.get("type", ""))] += 1
    return counts

def node_fill_check(state: ExamState) -> dict:
    """부족한 '문항 수'가 아니라 부족한 '단원+유형'을 기준으로 fill blueprint 생성."""
    blueprint = _full_blueprint(state)

    accumulated = list(state.get("_accepted_questions", []))
    existing_ids = {q.get("id") for q in accumulated}

    for q in state.get("questions", []):
        if q.get("id") not in existing_ids:
            accumulated.append(q)
            existing_ids.add(q.get("id"))

    counts = _topic_type_counts(accumulated)
    fill_topics = []

    total_required = 0
    total_current = 0

    for t in blueprint.get("topics", []):
        topic_name = t.get("name", "")
        need_sa    = int(t.get("short_answer_questions", 0))
        need_essay = int(t.get("essay_questions", 0))
        need_app   = int(t.get("application_questions", 0))

        have_sa    = counts.get((topic_name, "short_answer"), 0)
        have_essay = counts.get((topic_name, "essay"), 0)
        have_app   = counts.get((topic_name, "application"), 0)

        total_required += need_sa + need_essay + need_app
        total_current  += (min(have_sa, need_sa)
                           + min(have_essay, need_essay)
                           + min(have_app, need_app))

        short_sa    = max(0, need_sa - have_sa)
        short_essay = max(0, need_essay - have_essay)
        short_app   = max(0, need_app - have_app)

        if short_sa > 0 or short_essay > 0 or short_app > 0:
            fill_topics.append({
                **t,
                "short_answer_questions": short_sa,
                "essay_questions": short_essay,
                "application_questions": short_app,
            })

    logger.log(
        "Graph",
        f"[Fill Check] {total_current}/{total_required} 문항 확보"
    )

    if fill_topics and state.get("fill_count", 0) < _MAX_FILL:
        fill_blueprint = {**blueprint, "topics": fill_topics}

        sa_short    = sum(t["short_answer_questions"] for t in fill_topics)
        essay_short = sum(t["essay_questions"] for t in fill_topics)
        app_short   = sum(t["application_questions"] for t in fill_topics)
        logger.log(
            "Graph",
            f"  → 부족분 보충: 단답형 {sa_short}개 / 서술형 {essay_short}개 / "
            f"사례적용형 {app_short}개  (fill #{state.get('fill_count', 0) + 1})"
        )

        for t in fill_topics:
            logger.log(
                "Graph",
                f"     부족 단원: {t.get('name','?')} "
                f"단답형 {t.get('short_answer_questions',0)} / "
                f"서술형 {t.get('essay_questions',0)} / "
                f"사례적용형 {t.get('application_questions',0)}"
            )

        return {
            "_accepted_questions": accumulated,
            "questions": accumulated,
            "blueprint": fill_blueprint,
            "_draft_a": [],
            "_draft_b": [],
            "fill_count": state.get("fill_count", 0) + 1,
            "_needs_fill": True,
        }

    if fill_topics:
        logger.log("Graph", "  ⚠️  최대 fill 시도 도달 — rescue pool에서 부족분 보충 시도")
        rescue_pool = state.get("_rescue_pool", [])
        passed_ids = {q["id"] for q in accumulated}
        still_needed = sum(
            t.get("short_answer_questions", 0)
            + t.get("essay_questions", 0)
            + t.get("application_questions", 0)
            for t in fill_topics
        )
        candidates = sorted(
            [r for r in rescue_pool if r["question"]["id"] not in passed_ids],
            key=lambda x: x["answer_match"],
            reverse=True,
        )[:still_needed]
        for r in candidates:
            accumulated.append(r["question"])
            logger.log(
                "Graph",
                f"  🔄 rescue 통과 [{r['question']['id']}] "
                f"answer_match={r['answer_match']:.2f} — 문제 수 보장",
            )
        if not candidates:
            logger.log("Graph", "  ⚠️  rescue pool에도 후보 없음 — 부족한 채로 진행")

    return {
        "_accepted_questions": accumulated,
        "questions": accumulated,
        "blueprint": blueprint,
        "_needs_fill": False,
    }

def after_fill_check(state: ExamState) -> str:
    """fill_check에서 부족분 생성이 필요하다고 표시했으면 다시 professor로."""
    return "fill" if state.get("_needs_fill", False) else "student"

def _normalize_question_scores(questions: list[dict], total_score: int) -> list[dict]:
    """최종 문제 수 기준으로 총점을 정확히 total_score에 맞춤."""
    if not questions:
        return questions

    n = len(questions)
    base = total_score // n
    remainder = total_score % n

    normalized = []
    for i, q in enumerate(questions):
        q = dict(q)
        q["score"] = base + (1 if i < remainder else 0)
        normalized.append(q)

    return normalized


def node_score_normalize(state: ExamState) -> dict:
    """AnswerGen 전에 문항 점수를 총점에 맞게 확정."""
    passed = list(state.get("passed_questions", []))
    req = state.get("requirements", {})

    required_total = int(req.get("total_questions", len(passed)))
    required_score = int(req.get("total_score", 100))

    if len(passed) != required_total:
        logger.log("Score", f"⚠️  점수 보정 보류: 문제 수 {len(passed)}/{required_total}")
        return {"questions": passed}

    before = sum(int(q.get("score", 0)) for q in passed)
    normalized = _normalize_question_scores(passed, required_score)
    after = sum(int(q.get("score", 0)) for q in normalized)

    if before != after:
        logger.log("Score", f"총점 보정: {before}점 → {after}점")

    return {
        "passed_questions": normalized,
        "questions": normalized,
        "_accepted_questions": normalized,
        "model_answers": [],
    }
    
def node_answer_gen(state: ExamState) -> dict:
    return answer_gen.run(state)


def node_human_review(state: ExamState) -> dict:
    return human_review.run(state)


def node_scenario_gen(state: ExamState) -> dict:
    return scenario_gen.run(state)


def node_validate(state: ExamState) -> dict:
    """Compiler 진입 전 최종 검증. 실패하면 compiler로 보내지 않음."""
    passed = state.get("passed_questions", [])
    answers = {a["question_id"]: a for a in state.get("model_answers", [])}
    req = state.get("requirements", {})

    required_total = int(req.get("total_questions", len(passed)))
    required_score = int(req.get("total_score", 100))

    actual_score = sum(int(q.get("score", 0)) for q in passed)
    missing_answers = [q["id"] for q in passed if q["id"] not in answers]

    forbidden_tokens = ("【대문제", "[공통 시나리오]", "[소문항", "공통 시나리오", "소문항")
    bad_format = [
        q["id"] for q in passed
        if any(token in q.get("content", "") for token in forbidden_tokens)
    ]

    logger.section("STEP 8.5 — Pre-Compiler Validation")
    ok = True

    if len(passed) != required_total:
        logger.log("Validate", f"⚠️  문제 수 불일치: {len(passed)}개 (요구 {required_total}개)")
        ok = False

    if actual_score != required_score:
        logger.log("Validate", f"⚠️  총점 불일치: {actual_score}점 (요구 {required_score}점)")
        ok = False

    if missing_answers:
        logger.log("Validate", f"⚠️  모범답안 누락: {missing_answers}")
        ok = False

    if bad_format:
        logger.log("Validate", f"⚠️  편집용 표현 포함 문제: {bad_format}")
        ok = False

    if ok:
        logger.log("Validate", "✅ 모든 조건 충족")
    else:
        logger.log("Validate", "⛔ 검증 실패 — Compiler로 진행하지 않습니다.")

    return {"_validation_ok": ok}

def node_compiler(state: ExamState) -> dict:
    return compiler.run(state)


# ── 조건부 엣지 ───────────────────────────────────────────────────

def after_judge(state: ExamState) -> str:
    failed = state.get("failed_questions", [])
    retries = state.get("retry_count", 0)

    if failed and retries < config.MAX_RETRIES:
        return "retry"

    required_total = int(state.get("requirements", {}).get("total_questions", 0))
    passed_count = len(state.get("passed_questions", []))

    if required_total and passed_count < required_total:
        if state.get("fill_count", 0) < _MAX_FILL:
            logger.log(
                "Graph",
                f"Judge PASS 후에도 문제 수 부족: {passed_count}/{required_total} → Fill로 복귀"
            )
            return "fill"
        else:
            logger.log(
                "Graph",
                f"⚠️  Fill 한도 소진 — 문제 수 부족({passed_count}/{required_total})인 채로 진행"
            )

    return "proceed"

def after_validate(state: ExamState) -> str:
    if state.get("_validation_ok", False):
        return "compiler"

    required_total = int(state.get("requirements", {}).get("total_questions", 0))
    passed_count = len(state.get("passed_questions", []))

    # fill 여력이 있고 문제 수가 부족하면 fill로
    if required_total and passed_count < required_total and state.get("fill_count", 0) < _MAX_FILL:
        return "fill"

    # fill 한도 소진 or 점수 불일치 — 더 이상 루프하지 않고 compiler로 강제 진행
    logger.log("Validate", "⚠️  조건 미충족이지만 더 이상 보정 불가 → 현재 상태로 compiler 진행")
    return "compiler"


# ── 그래프 조립 ───────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(ExamState)

    g.add_node("index",         node_index)
    g.add_node("blueprint",         node_blueprint)
    g.add_node("blueprint_review",  node_blueprint_review)
    g.add_node("professor_a",       node_professor_a)
    g.add_node("professor_b",   node_professor_b)
    g.add_node("consensus",     node_consensus)
    g.add_node("fill_check",    node_fill_check)
    g.add_node("student",       node_student)
    g.add_node("judge",         node_judge)
    g.add_node("retry_prepare", node_retry_prepare)
    g.add_node("score_normalize", node_score_normalize)
    g.add_node("validate",      node_validate)
    g.add_node("answer_gen",    node_answer_gen)
    g.add_node("human_review",  node_human_review)
    g.add_node("scenario_gen",  node_scenario_gen)
    g.add_node("compiler",      node_compiler)

    # 초기 흐름
    g.set_entry_point("index")
    g.add_edge("index",            "blueprint")
    g.add_edge("blueprint",        "blueprint_review")
    g.add_edge("blueprint_review", "professor_a")
    g.add_edge("professor_a", "professor_b")
    g.add_edge("professor_b", "consensus")
    g.add_edge("consensus",   "fill_check")
    g.add_edge("student",     "judge")
    g.add_edge("score_normalize", "answer_gen")

    # fill_check 조건부 엣지: 부족하면 교수 재출제, 충분하면 학생으로
    g.add_conditional_edges(
        "fill_check",
        after_fill_check,
        {
            "fill":    "professor_a",
            "student": "student",
        },
    )

    # Judge 재출제 흐름
    g.add_edge("retry_prepare", "professor_a")

    # 완료 흐름
    g.add_edge("answer_gen",    "human_review")
    g.add_edge("human_review",  "scenario_gen")
    g.add_edge("scenario_gen",  "validate")
    g.add_edge("compiler",   END)

    # 조건부 엣지
    g.add_conditional_edges(
        "judge",
        after_judge,
        {
            "retry":   "retry_prepare",
            "fill": "fill_check",
            "proceed": "score_normalize",
        },
    )

    g.add_conditional_edges(
         "validate",
         after_validate,
        {
            "compiler": "compiler",
            "fill": "fill_check",
            "score": "score_normalize",
        },
    )

    return g.compile()
