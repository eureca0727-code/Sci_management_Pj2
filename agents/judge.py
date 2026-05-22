import json
from collections import defaultdict
import anthropic
from state import ExamState, Question, StudentSolution, JudgeResult
from prompts.templates import JUDGE
from utils import parse_json, cached_create
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
) -> JudgeResult:

    response = cached_create(
        _client,
        model=config.MODEL,
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": JUDGE.format(
                question_type=question.get("type", "concept"),
                intended_answer=question.get("intended_answer", ""),
                source_slides=question.get("source_slides", []),
                n=len(grounded),
                grounded_solutions=json.dumps(
                    [{"run": s["run_index"], "answer": s["answer"][:2000],
                      "citations": s["citations"]} for s in grounded],
                    ensure_ascii=False,
                ),
            ),
        }],
    )

    logger.record_tokens("Judge", response.usage)
    raw = parse_json(response.content[0].text)
    if not isinstance(raw, dict):
        raw = {}

    q_type = question.get("type", "concept")
    answer_match       = float(raw.get("answer_match", 0.0))
    ambiguity_score    = float(raw.get("ambiguity_score", 0.0))
    lecture_dependency = float(raw.get("lecture_dependency", 0.0))
    citation_jaccard   = float(raw.get("citation_jaccard", 0.0))

    # 지표가 기준을 충족하면 LLM 판정과 무관하게 pass
    if q_type == "concept":
        metrics_pass = (answer_match >= config.CONCEPT_ANSWER_MATCH_MIN
                        and ambiguity_score <= config.AMBIGUITY_MAX)
    else:
        metrics_pass = (answer_match >= config.CASE_ANSWER_MATCH_MIN
                        and ambiguity_score <= config.AMBIGUITY_MAX)

    llm_passed = bool(raw.get("passed", False))
    passed = llm_passed or metrics_pass

    return JudgeResult(
        question_id=question["id"],
        passed=passed,
        lecture_dependency=lecture_dependency,
        citation_jaccard=citation_jaccard,
        ambiguity_score=ambiguity_score,
        answer_match=answer_match,
        failure_reason=None if passed else raw.get("failure_reason"),
    )


def run(state: ExamState) -> dict:
    logger.section("STEP 7 — Judge Evaluation")
    questions = state["questions"]
    grounded_map = _group_solutions(state["grounded_solutions"])

    results: list[JudgeResult] = []
    passed: list[Question] = []
    failed: list[Question] = []
    new_failure_patterns = list(state.get("failure_patterns", []))

    for q in questions:
        logger.log("Judge", f"판정 중: [{q['id']}] {q.get('content','')[:50]}...")
        grounded = grounded_map[q["id"]]
        result = _judge_question(q, grounded)
        results.append(result)
        logger.show_judge(result)

        if result["passed"]:
            passed.append(q)
        else:
            failed.append(q)
            pattern = f"{q.get('type','?')}:{q.get('topic','?')}:{result['failure_reason']}"
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
    retries = state.get("retry_count", 0)
    if failed and retries < config.MAX_RETRIES:
        logger.log("Judge", f"⚠️  실패 문제: {[q['id'] for q in failed]} → 재출제 예정")
    elif failed:
        logger.log("Judge", f"⚠️  실패 문제: {[q['id'] for q in failed]} → 최대 재출제 횟수 도달, 통과 문제만으로 진행")

    return {
        "judge_results": results,
        "passed_questions": all_passed,
        "failed_questions": failed,
        "failure_patterns": new_failure_patterns,
    }
