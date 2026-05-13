import json
from collections import defaultdict
import anthropic
from state import ExamState, Question, StudentSolution
from prompts.templates import ANSWER_GENERATOR
from tools.rag import get_slides_by_numbers, format_context
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _best_grounded(solutions: list[StudentSolution]) -> StudentSolution:
    valid = [s for s in solutions if not s["insufficient"]]
    if not valid:
        return solutions[0]
    return max(valid, key=lambda s: len(s["citations"]))


def run(state: ExamState) -> dict:
    logger.section("STEP 8 — Model Answer Generation")
    passed = state["passed_questions"]
    grounded_map = defaultdict(list)
    for s in state["grounded_solutions"]:
        grounded_map[s["question_id"]].append(s)

    model_answers = []

    for q in passed:
        logger.log("AnswerGen", f"[{q['id']}] 모범답안 생성 중...")
        best = _best_grounded(grounded_map[q["id"]])
        slides = get_slides_by_numbers(q["source_slides"])
        slide_text = format_context(slides)

        response = _client.messages.create(
            model=config.MODEL,
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": ANSWER_GENERATOR.format(
                    question=q["content"],
                    intended_answer=q["intended_answer"],
                    best_student_answer=best["answer"][:400],
                    slide_excerpts=slide_text,
                ),
            }],
        )

        logger.record_tokens("AnswerGen", response.usage)
        raw = json.loads(response.content[0].text)
        raw["question_id"] = q["id"]
        raw["question_type"] = q["type"]
        model_answers.append(raw)

        logger.log("AnswerGen", f"  ✅ 루브릭 {len(raw.get('rubric', []))}항목 / "
                                f"키워드: {raw.get('key_concepts', [])}")

    logger.log("AnswerGen", f"✅ 모범답안 {len(model_answers)}개 생성 완료")
    return {"model_answers": model_answers}
