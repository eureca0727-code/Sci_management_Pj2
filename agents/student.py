import re
import anthropic
from state import ExamState, Question, StudentSolution
from prompts.templates import STUDENT_GROUNDED
from tools.rag import retrieve, format_context
from utils import cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _full_question_text(question: Question) -> str:
    """scenario 필드가 분리된 경우 합쳐서 반환, 없으면 content만."""
    scenario = (question.get("scenario") or "").strip()
    content = (question.get("content") or "").strip()
    if scenario:
        return f"{scenario}\n\n{content}"
    return content


def _solve_grounded(question: Question, run_index: int) -> StudentSolution:
    full_text = _full_question_text(question)
    search_query = question.get("topic") or full_text[:100]
    slides = retrieve(search_query, top_k=config.TOP_K)
    context = format_context(slides)

    response = cached_create(
        _client,
        model=config.HAIKU_MODEL,
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": STUDENT_GROUNDED.format(
                context=context,
                question=full_text,
            ),
        }],
    )

    logger.record_tokens("Student", response.usage)
    answer = response.content[0].text.strip()
    insufficient = answer == "INSUFFICIENT_EVIDENCE"
    citations = re.findall(r"\[슬라이드\s*(\d+)\]", answer)

    logger.show_student(
        question["id"], run_index + 1, answer,
        [f"슬라이드 {n}" for n in citations], "grounded"
    )
    if insufficient:
        logger.log("Student", f"  ⚠️  [{question['id']}] INSUFFICIENT_EVIDENCE 반환")

    return StudentSolution(
        question_id=question["id"],
        answer=answer,
        citations=[f"슬라이드 {n}" for n in citations],
        mode="grounded",
        run_index=run_index,
        insufficient=insufficient,
    )


def run(state: ExamState) -> dict:
    logger.section("STEP 6 — Student Simulation (grounded only)")
    questions = state["questions"]
    logger.log("Student", f"{len(questions)}개 문제 × grounded {config.STUDENT_RUNS}회 풀이 시작")

    grounded_solutions: list[StudentSolution] = []

    for q in questions:
        content = q.get("content", "")
        logger.log("Student", f"── [{q['id']}] {content[:60]}...")
        for i in range(config.STUDENT_RUNS):
            sol = _solve_grounded(q, run_index=i)
            grounded_solutions.append(sol)

    logger.log("Student", f"✅ 풀이 완료: grounded {len(grounded_solutions)}건")

    current_ids = {q["id"] for q in questions}
    prev_grounded = [s for s in state.get("grounded_solutions", [])
                     if s["question_id"] not in current_ids]

    return {
        "grounded_solutions": prev_grounded + grounded_solutions,
        "unrestricted_solutions": [],
    }
