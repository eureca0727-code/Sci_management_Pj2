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


def node_retry_prepare(state: ExamState) -> dict:
    """재출제 전 상태 정리 + 실패 문제 기반 blueprint 필터링."""
    retries = state.get("retry_count", 0)
    failed = state.get("failed_questions", [])

    logger.section(f"RETRY {retries + 1}/{config.MAX_RETRIES} — 재출제 준비")
    logger.log("Graph", f"실패 문제 {len(failed)}개 → 해당 단원만 재출제")

    # 실패 문제에서 단원별 재출제 수량 집계
    topic_counts: dict[str, dict] = defaultdict(
        lambda: {"concept_questions": 0, "case_questions": 0}
    )
    for q in failed:
        if q["type"] == "concept":
            topic_counts[q["topic"]]["concept_questions"] += 1
        else:
            topic_counts[q["topic"]]["case_questions"] += 1

    # 원본 blueprint에서 실패 단원만 추출해 필터링된 blueprint 생성
    topic_map = {t["name"]: t for t in state["blueprint"]["topics"]}
    retry_topics = [
        {**topic_map[name], **counts}
        for name, counts in topic_counts.items()
        if name in topic_map
    ]
    filtered_blueprint = {**state["blueprint"], "topics": retry_topics}

    for t in retry_topics:
        logger.log("Graph", f"  재출제: '{t['name']}' — "
                            f"개념 {t['concept_questions']}개 / 사례 {t['case_questions']}개")

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
    g.add_edge("blueprint",   "professor_b")   # A/B 병렬 실행
    g.add_edge("professor_a", "consensus")
    g.add_edge("professor_b", "consensus")
    g.add_edge("consensus",   "student")
    g.add_edge("student",     "judge")

    # 재출제 흐름: retry_prepare → A/B 병렬 → consensus → student → judge
    g.add_edge("retry_prepare", "professor_a")
    g.add_edge("retry_prepare", "professor_b")

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
