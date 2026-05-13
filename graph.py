from langgraph.graph import StateGraph, END
from state import ExamState
from agents import indexer, chair, professor, student, judge, answer_gen, compiler
import config


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
    result = judge.run(state)
    result["retry_count"] = state.get("retry_count", 0) + 1
    return result


def node_answer_gen(state: ExamState) -> dict:
    return answer_gen.run(state)


def node_compiler(state: ExamState) -> dict:
    return compiler.run(state)


# ── 조건부 엣지 ───────────────────────────────────────────────────

def should_retry(state: ExamState) -> str:
    """Judge 실패 문제가 있고 재시도 한도 내면 professor_a로 루프."""
    failed = state.get("failed_questions", [])
    retries = state.get("retry_count", 0)

    if failed and retries < config.MAX_RETRIES:
        print(f"[Graph] {len(failed)}개 실패 → 재출제 (retry {retries}/{config.MAX_RETRIES})")
        # failed questions만 다음 라운드의 questions로 교체
        return "retry"
    return "proceed"


def after_judge(state: ExamState) -> str:
    return should_retry(state)


# ── 그래프 조립 ───────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(ExamState)

    g.add_node("index", node_index)
    g.add_node("blueprint", node_blueprint)
    g.add_node("professor_a", node_professor_a)
    g.add_node("professor_b", node_professor_b)
    g.add_node("consensus", node_consensus)
    g.add_node("student", node_student)
    g.add_node("judge", node_judge)
    g.add_node("answer_gen", node_answer_gen)
    g.add_node("compiler", node_compiler)

    # 고정 엣지
    g.set_entry_point("index")
    g.add_edge("index", "blueprint")
    g.add_edge("blueprint", "professor_a")
    g.add_edge("blueprint", "professor_b")   # professor_a/b 병렬 실행
    g.add_edge("professor_a", "consensus")
    g.add_edge("professor_b", "consensus")
    g.add_edge("consensus", "student")
    g.add_edge("student", "judge")
    g.add_edge("answer_gen", "compiler")
    g.add_edge("compiler", END)

    # 조건부 엣지: judge → retry or proceed
    g.add_conditional_edges(
        "judge",
        after_judge,
        {
            "retry": "professor_a",   # 실패 문제 재출제
            "proceed": "answer_gen",  # 전부 통과
        },
    )

    return g.compile()
