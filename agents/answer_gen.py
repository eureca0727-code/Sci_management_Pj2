import json
from collections import defaultdict
import anthropic
from state import ExamState, Question, StudentSolution
from prompts.templates import ANSWER_GENERATOR
from tools.rag import get_slides_by_numbers, format_context
from utils import parse_json, cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _best_grounded(solutions: list[StudentSolution]) -> StudentSolution | None:
    if not solutions:
        return None
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
        best_answer_text = best["answer"][:600] if best else "(학생 풀이 없음)"
        slides = get_slides_by_numbers(q.get("source_slides", []))
        slide_text = format_context(slides)

        response = cached_create(
            _client,
            model=config.MODEL,
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": ANSWER_GENERATOR.format(
                    question=q.get("content", ""),
                    intended_answer=q.get("intended_answer", ""),
                    best_student_answer=best_answer_text,
                    slide_excerpts=slide_text,
                ),
            }],
        )

        logger.record_tokens("AnswerGen", response.usage)
        raw = parse_json(response.content[0].text)
        if not isinstance(raw, dict):
            raw = {"model_answer": str(raw), "key_concepts": [], "rubric": []}

    # 루브릭 합계가 문제 점수와 정확히 일치하도록 정수 점수로 보정
        q_score = int(q.get("score", 0))
        rubric = [item for item in raw.get("rubric", []) if isinstance(item, dict)]
        rubric_sum = sum(float(item.get("points", 0)) for item in rubric)

        if rubric and rubric_sum > 0:
            scaled = [float(item.get("points", 0)) * q_score / rubric_sum for item in rubric]
            int_points = [max(0, int(x)) for x in scaled]
            remainder = q_score - sum(int_points)

    # 소수 부분이 큰 항목부터 남은 점수 배분
             order = sorted(
                range(len(scaled)),
                key=lambda i: scaled[i] - int(scaled[i]),
                reverse=True,
            )


             for i in order[:max(0, remainder)]:
                int_points[i] += 1
                 
    # 혹시 초과되면 마지막 항목에서 보정
         diff = q_score - sum(int_points)
            int_points[-1] += diff

            for item, pts in zip(rubric, int_points):
                item["points"] = int(pts)

            raw["rubric"] = rubric
            fixed_sum = sum(item["points"] for item in rubric)

            if abs(rubric_sum - q_score) > 0.001 or fixed_sum != q_score:
                logger.log("AnswerGen", f"  ⚠️  루브릭 합계 보정: {rubric_sum:.0f}pt → {q_score}pt")

        raw["question_id"] = q["id"]
        raw["question_type"] = q.get("type", "")
        model_answers.append(raw)

        logger.log(
            "AnswerGen",
            f"  ✅ 루브릭 {len(raw.get('rubric', []))}항목 / 키워드: {raw.get('key_concepts', [])}",
        )

    logger.log("AnswerGen", f"✅ 모범답안 {len(model_answers)}개 생성 완료")
    return {"model_answers": model_answers}
