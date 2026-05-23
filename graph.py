from collections import defaultdict
from langgraph.graph import StateGraph, END
from state import ExamState
from agents import indexer, chair, professor, student, judge, answer_gen, compiler
import config
import logger


# ── 노드 함수 래퍼 ────────────────────────────────────────────────

def node_index(state: ExamState) -> dict:
    return indexer.run(state)


def node_blueprint(state: ExamState) -> dict:
    return chair.run_blueprint(state)


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
    """source_slides 범위로 블루프린트 단원 찾기. 안 되면 topic명 폴백."""
    source_slides = [int(s) for s in failed_q.get("source_slides", []) if s is not None]
    if source_slides:
        for t in blueprint_topics:
            r = t.get("slides", [])
            if len(r) >= 2:
                start, end = int(r[0]), int(r[1])
                if any(start <= s <= end for s in source_slides):
                    return t
    # 폴백: topic명 정확 매칭
    name = failed_q.get("topic", "")
    for t in blueprint_topics:
        if t.get("name", "") == name:
            return t
    return None


def node_retry_prepare(state: ExamState) -> dict:
    """재출제 전 상태 정리 + 실패 문제 기반 blueprint 필터링 (문제별 횟수 추적)."""
    retries = state.get("retry_count", 0)
    failed = state.get("failed_questions", [])
    blueprint_topics = state["blueprint"].get("topics", [])
    fail_counts = dict(state.get("question_fail_counts", {}))

    # 실패 횟수 업데이트
    for q in failed:
        key = f"{q.get('topic', '')}:{q.get('type', '')}"
        fail_counts[key] = fail_counts.get(key, 0) + 1

    # 재출제 가능 vs 영구 탈락 분리
    retryable = []
    permanent_fail = []
    for q in failed:
        key = f"{q.get('topic', '')}:{q.get('type', '')}"
        if fail_counts[key] <= config.MAX_RETRIES_PER_QUESTION:
            retryable.append(q)
        else:
            permanent_fail.append(q)

    if permanent_fail:
        logger.log("Graph", f"  ⚠️  최대 재출제 초과 — 영구 탈락: "
                            f"{[q.get('id', '?') for q in permanent_fail]}")

    logger.section(f"RETRY {retries + 1} — 재출제 준비")
    logger.log("Graph", f"실패 {len(failed)}개 중 재출제 {len(retryable)}개 / "
                        f"영구탈락 {len(permanent_fail)}개")

    # source_slides 기준으로 블루프린트 단원 찾아 재출제 수량 집계
    topic_counts: dict[str, dict] = defaultdict(
        lambda: {"concept_questions": 0, "case_questions": 0}
    )
    topic_by_name: dict[str, dict] = {}
    unmatched = []

    for q in retryable:
        matched = _find_blueprint_topic(q, blueprint_topics)
        if matched is None:
            unmatched.append(q.get("id", "?"))
            continue
        name = matched["name"]
        topic_by_name[name] = matched
        if q.get("type") == "concept":
            topic_counts[name]["concept_questions"] += 1
        else:
            topic_counts[name]["case_questions"] += 1

    if unmatched:
        logger.log("Graph", f"  ⚠️  블루프린트 매칭 실패 (건너뜀): {unmatched}")

    retry_topics = [
        {**topic_by_name[name], **counts}
        for name, counts in topic_counts.items()
    ]
    filtered_blueprint = {**state["blueprint"], "topics": retry_topics}

    for t in retry_topics:
        logger.log("Graph", f"  재출제: '{t.get('name','?')}' — "
                            f"개념 {t.get('concept_questions',0)}개 / 사례 {t.get('case_questions',0)}개")

    return {
        "retry_count": retries + 1,
        "question_fail_counts": fail_counts,
        "blueprint": filtered_blueprint,
        "_draft_a": [],
        "_draft_b": [],
        "questions": [],
        "judge_results": [],
    }


_MAX_FILL = 2  # Chair 부족분 보충 최대 시도 횟수


def node_fill_check(state: ExamState) -> dict:
    """Consensus 후 채택 문제 수가 부족하면 fill blueprint 생성."""
    blueprint = state["blueprint"]
    required_concept = sum(t.get("concept_questions", 0) for t in blueprint.get("topics", []))
    required_case    = sum(t.get("case_questions", 0)    for t in blueprint.get("topics", []))

    # 이번 consensus 결과 + 이전 fill 라운드 누적 문제 합산
    accumulated = list(state.get("_accepted_questions", []))
    new_questions = [q for q in state.get("questions", [])
                     if q["id"] not in {a["id"] for a in accumulated}]
    accumulated = accumulated + new_questions

    current_concept = sum(1 for q in accumulated if q.get("type") == "concept")
    current_case    = sum(1 for q in accumulated if q.get("type") == "case")
    short_concept   = max(0, required_concept - current_concept)
    short_case      = max(0, required_case    - current_case)

    logger.log("Graph", f"[Fill Check] 개념 {current_concept}/{required_concept}  "
                        f"사례 {current_case}/{required_case}")

    if (short_concept > 0 or short_case > 0) and state.get("fill_count", 0) < _MAX_FILL:
        # 부족분만 채우는 fill blueprint 생성
        fill_topics = []
        for t in blueprint.get("topics", []):
            need_c = min(t.get("concept_questions", 0),
                         short_concept) if short_concept > 0 else 0
            need_s = min(t.get("case_questions", 0),
                         short_case) if short_case > 0 else 0
            if need_c > 0 or need_s > 0:
                fill_topics.append({**t,
                                    "concept_questions": need_c,
                                    "case_questions": need_s})
                short_concept -= need_c
                short_case    -= need_s
        fill_blueprint = {**blueprint, "topics": fill_topics}
        logger.log("Graph", f"  → 부족분 보충: 개념 {sum(t['concept_questions'] for t in fill_topics)}개 "
                            f"/ 사례 {sum(t['case_questions'] for t in fill_topics)}개  "
                            f"(fill #{state.get('fill_count', 0) + 1})")
        return {
            "_accepted_questions": accumulated,
            "questions": accumulated,
            "blueprint": fill_blueprint,
            "_draft_a": [],
            "_draft_b": [],
            "fill_count": state.get("fill_count", 0) + 1,
        }

    # 충분하거나 최대 시도 초과 → 누적 문제로 확정
    if short_concept > 0 or short_case > 0:
        logger.log("Graph", f"  ⚠️  최대 fill 시도 도달 — 부족한 채로 진행 "
                            f"(개념 {short_concept}개, 사례 {short_case}개 부족)")
    return {
        "_accepted_questions": accumulated,
        "questions": accumulated,
    }


def after_fill_check(state: ExamState) -> str:
    """fill_count가 증가했으면 다시 professor로, 아니면 student로."""
    blueprint = state["blueprint"]
    required = sum(t.get("concept_questions", 0) + t.get("case_questions", 0)
                   for t in blueprint.get("topics", []))
    accumulated = state.get("_accepted_questions", [])

    # fill blueprint에 문제가 남아있으면(= 방금 fill_count 증가) 교수에게 재출제
    if required > 0 and len(accumulated) < (
        sum(t.get("concept_questions", 0) + t.get("case_questions", 0)
            for t in state.get("blueprint", {}).get("topics", []))
        + len(accumulated)
    ):
        pass  # 아래 조건으로 판단

    # 간단하게: fill_count 마지막 증가 여부는 blueprint topics 잔여량으로 판단
    fill_topics = state["blueprint"].get("topics", [])
    has_fill_work = any(
        t.get("concept_questions", 0) + t.get("case_questions", 0) > 0
        for t in fill_topics
    )
    if has_fill_work and state.get("fill_count", 0) <= _MAX_FILL:
        return "fill"
    return "student"


def node_answer_gen(state: ExamState) -> dict:
    return answer_gen.run(state)


def node_validate(state: ExamState) -> dict:
    """Compiler 진입 전 최종 검증 — 경고만 출력하고 진행."""
    passed   = state.get("passed_questions", [])
    answers  = {a["question_id"]: a for a in state.get("model_answers", [])}
    req      = state.get("requirements", {})
    required_total = req.get("total_questions", len(passed))
    required_score = req.get("total_score", 100)

    actual_score = sum(q.get("score", 0) for q in passed)
    missing_answers = [q["id"] for q in passed if q["id"] not in answers]

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
    if ok:
        logger.log("Validate", "✅ 모든 조건 충족")
    return {}


def node_compiler(state: ExamState) -> dict:
    return compiler.run(state)


# ── 조건부 엣지 ───────────────────────────────────────────────────

def after_judge(state: ExamState) -> str:
    failed = state.get("failed_questions", [])
    if not failed:
        return "proceed"

    fail_counts = state.get("question_fail_counts", {})
    # 재출제 여지가 남은 문제가 하나라도 있으면 재출제
    for q in failed:
        key = f"{q.get('topic', '')}:{q.get('type', '')}"
        if fail_counts.get(key, 0) < config.MAX_RETRIES_PER_QUESTION:
            return "retry"
    return "proceed"


# ── 그래프 조립 ───────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(ExamState)

    g.add_node("index",         node_index)
    g.add_node("blueprint",     node_blueprint)
    g.add_node("professor_a",   node_professor_a)
    g.add_node("professor_b",   node_professor_b)
    g.add_node("consensus",     node_consensus)
    g.add_node("fill_check",    node_fill_check)
    g.add_node("student",       node_student)
    g.add_node("judge",         node_judge)
    g.add_node("retry_prepare", node_retry_prepare)
    g.add_node("validate",      node_validate)
    g.add_node("answer_gen",    node_answer_gen)
    g.add_node("compiler",      node_compiler)

    # 초기 흐름
    g.set_entry_point("index")
    g.add_edge("index",       "blueprint")
    g.add_edge("blueprint",   "professor_a")
    g.add_edge("professor_a", "professor_b")
    g.add_edge("professor_b", "consensus")
    g.add_edge("consensus",   "fill_check")
    g.add_edge("student",     "judge")

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
    g.add_edge("answer_gen", "validate")
    g.add_edge("validate",   "compiler")
    g.add_edge("compiler",   END)

    # 조건부 엣지
    g.add_conditional_edges(
        "judge",
        after_judge,
        {
            "retry":   "retry_prepare",
            "proceed": "answer_gen",
        },
    )

    return g.compile()
