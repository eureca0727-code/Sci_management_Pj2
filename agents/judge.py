import json
from collections import defaultdict
import anthropic
from state import ExamState, Question, StudentSolution, JudgeResult
from prompts.templates import JUDGE
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _group_solutions(solutions: list[StudentSolution]) -> dict[str, list[StudentSolution]]:
    groups = defaultdict(list)
    for s in solutions:
        groups[s["question_id"]].append(s)
    return groups


def _judge_question(
    question: Question,
    grounded: list[StudentSolution],
    unrestricted: StudentSolution,
) -> JudgeResult:

    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": JUDGE.format(
                question_type=question["type"],
                intended_answer=question["intended_answer"],
                source_slides=question["source_slides"],
                n=len(grounded),
                grounded_solutions=json.dumps(
                    [{"run": s["run_index"], "answer": s["answer"][:300],
                      "citations": s["citations"]} for s in grounded],
                    ensure_ascii=False,
                ),
                unrestricted_solution=unrestricted["answer"][:300],
            ),
        }],
    )

    logger.record_tokens("Judge", response.usage)
    raw = json.loads(response.content[0].text)
    return JudgeResult(
        question_id=question["id"],
        passed=raw["passed"],
        lecture_dependency=raw["lecture_dependency"],
        citation_jaccard=raw["citation_jaccard"],
        ambiguity_score=raw["ambiguity_score"],
        answer_match=raw["answer_match"],
        failure_reason=raw.get("failure_reason"),
    )


def run(state: ExamState) -> dict:
    logger.section("STEP 7 — Judge Evaluation")
    questions = state["questions"]
    grounded_map = _group_solutions(state["grounded_solutions"])
    unrestricted_map = {s["question_id"]: s for s in state["unrestricted_solutions"]}

    results: list[JudgeResult] = []
    passed: list[Question] = []
    failed: list[Question] = []
    new_failure_patterns = list(state.get("failure_patterns", []))

    for q in questions:
        logger.log("Judge", f"판정 중: [{q['id']}] {q['content'][:50]}...")
        result = _judge_question(
            q,
            grounded_map[q["id"]],
            unrestricted_map[q["id"]],
        )
        results.append(result)
        logger.show_judge(result)

        if result["passed"]:
            passed.append(q)
        else:
            failed.append(q)
            pattern = f"{q['type']}:{q['topic']}:{result['failure_reason']}"
            new_failure_patterns.append(pattern)

    # 이전 라운드에서 통과한 문제를 유지 (재출제 시 누적)
    current_ids = {q["id"] for q in questions}
    previously_passed = [
        q for q in state.get("passed_questions", [])
        if q["id"] not in current_ids
    ]
    all_passed = previously_passed + passed

    logger.log("Judge", f"✅ 판정 완료 — PASS {len(passed)}개 / FAIL {len(failed)}개"
                        + (f" (누적 통과: {len(all_passed)}개)" if previously_passed else ""))
    if failed:
        logger.log("Judge", f"⚠️  실패 문제: {[q['id'] for q in failed]} → 재출제 예정")

    return {
        "judge_results": results,
        "passed_questions": all_passed,
        "failed_questions": failed,
        "failure_patterns": new_failure_patterns,
    }
