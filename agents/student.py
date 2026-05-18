import re
import anthropic
from state import ExamState, Question, StudentSolution
from prompts.templates import STUDENT_GROUNDED, STUDENT_UNRESTRICTED
from tools.rag import retrieve, format_context
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _solve_grounded(question: Question, run_index: int) -> StudentSolution:
    slides = retrieve(question["content"], top_k=config.TOP_K)
    context = format_context(slides)

    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": STUDENT_GROUNDED.format(
                context=context,
                question=question["content"],
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


def _solve_unrestricted(question: Question) -> StudentSolution:
    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": STUDENT_UNRESTRICTED.format(question=question["content"]),
        }],
    )

    logger.record_tokens("Student", response.usage)
    answer = response.content[0].text.strip()
    logger.show_student(question["id"], 0, answer, [], "unrestricted")

    return StudentSolution(
        question_id=question["id"],
        answer=answer,
        citations=[],
        mode="unrestricted",
        run_index=0,
        insufficient=False,
    )


def run(state: ExamState) -> dict:
    logger.section("STEP 6 — Student Simulation")
    questions = state["questions"]
    logger.log("Student", f"{len(questions)}개 문제 × (grounded {config.STUDENT_RUNS}회 + unrestricted 1회) 풀이 시작")

    grounded_solutions: list[StudentSolution] = []
    unrestricted_solutions: list[StudentSolution] = []

    for q in questions:
        logger.log("Student", f"── [{q['id']}] {q['content'][:60]}...")

        for i in range(config.STUDENT_RUNS):
            sol = _solve_grounded(q, run_index=i)
            grounded_solutions.append(sol)

        unres = _solve_unrestricted(q)
        unrestricted_solutions.append(unres)

    logger.log("Student", f"✅ 풀이 완료: grounded {len(grounded_solutions)}건 / unrestricted {len(unrestricted_solutions)}건")

    # 재출제 시 이전 통과 문제의 풀이 기록 보존
    current_ids = {q["id"] for q in questions}
    prev_grounded = [s for s in state.get("grounded_solutions", [])
                     if s["question_id"] not in current_ids]
    prev_unrestricted = [s for s in state.get("unrestricted_solutions", [])
                         if s["question_id"] not in current_ids]

    return {
        "grounded_solutions": prev_grounded + grounded_solutions,
        "unrestricted_solutions": prev_unrestricted + unrestricted_solutions,
    }
