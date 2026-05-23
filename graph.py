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
    """재출제 전 상태 정리 + 실패 문제 기반 blueprint 필터링."""
    retries = state.get("retry_count", 0)
    failed = state.get("failed_questions", [])
    blueprint_topics = state["blueprint"].get("topics", [])

    logger.section(f"RETRY {retries + 1}/{config.MAX_RETRIES} — 재출제 준비")
    logger.log("Graph", f"실패 문제 {len(failed)}개 → 해당 단원만 재출제")

    # source_slides 기준으로 블루프린트 단원 찾아 재출제 수량 집계
    topic_counts: dict[str, dict] = defaultdict(
        lambda: {"concept_questions": 0, "case_questions": 0}
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
        "blueprint": filtered_blueprint,
        "_draft_a": [],
        "_draft_b": [],
        "questions": [],
        "judge_results": [],
    }


def node_answer_gen(state: ExamState) -> dict:
    return answer_gen.run(state)


def node_compiler(state: ExamState) -> dict:
    return compiler.run(state)


# ── 조건부 엣지 ───────────────────────────────────────────────────

def after_judge(state: ExamState) -> str:
    failed = state.get("failed_questions", [])
    retries = state.get("retry_count", 0)

    if failed and retries < config.MAX_RETRIES:
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
    g.add_node("student",       node_student)
    g.add_node("judge",         node_judge)
    g.add_node("retry_prepare", node_retry_prepare)
    g.add_node("answer_gen",    node_answer_gen)
    g.add_node("compiler",      node_compiler)

    # 초기 흐름
    g.set_entry_point("index")
    g.add_edge("index",       "blueprint")
    g.add_edge("blueprint",   "professor_a")
    g.add_edge("professor_a", "professor_b")   # A 완료 후 B 순차 실행
    g.add_edge("professor_b", "consensus")
    g.add_edge("consensus",   "student")
    g.add_edge("student",     "judge")

    # 재출제 흐름: retry_prepare → A → B → consensus → student → judge
    g.add_edge("retry_prepare", "professor_a")

    # 완료 흐름
    g.add_edge("answer_gen", "compiler")
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
