from state import ExamState
import logger

_SEP = "─" * 62


def _print_question(idx: int, total: int, q: dict) -> None:
    print(f"\n{_SEP}")
    print(f"[{idx}/{total}]  {q['id']}  |  {q.get('type','?')}  |  "
          f"{q.get('topic','?')}  |  {q.get('score', 0)}점")
    print(_SEP)
    print(q.get("content", ""))
    print(f"\n  📌 의도 답: {str(q.get('intended_answer', ''))[:120]}...")


def _edit_question(q: dict) -> dict:
    q = dict(q)
    print("\n  ── 수정 모드 ──────────────────────────────────────")
    print(f"  현재 문제 내용:\n  {q.get('content', '')}")
    new_content = input("\n  새 문제 내용 (Enter=유지): ").strip()
    if new_content:
        q["content"] = new_content

    print(f"\n  현재 점수: {q.get('score', 0)}점")
    new_score = input("  새 점수 (Enter=유지): ").strip()
    if new_score:
        try:
            q["score"] = int(new_score)
        except ValueError:
            print("  ⚠️  숫자가 아닙니다. 점수 유지.")

    return q


def run(state: ExamState) -> dict:
    logger.section("STEP 8.5 — Human Review")

    passed = list(state.get("passed_questions", []))
    answers_map = {a["question_id"]: a for a in state.get("model_answers", [])}

    if not passed:
        logger.log("HumanReview", "검토할 문제가 없습니다.")
        return {}

    total = len(passed)
    print(f"\n총 {total}개 문제를 검토합니다.")
    print("  Enter = 통과    e = 수정    d = 삭제\n")

    final_questions = []
    final_answers = []

    for idx, q in enumerate(passed, 1):
        _print_question(idx, total, q)
        print(f"\n  선택 (Enter/e/d): ", end="", flush=True)

        choice = input().strip().lower()

        if choice == "d":
            logger.log("HumanReview", f"❌ [{q['id']}] 삭제")
            continue

        if choice == "e":
            q = _edit_question(q)
            logger.log("HumanReview", f"✏️  [{q['id']}] 수정 완료")
        else:
            logger.log("HumanReview", f"✅ [{q['id']}] 통과")

        final_questions.append(q)
        ans = answers_map.get(q["id"])
        if ans:
            final_answers.append(ans)

    removed = total - len(final_questions)
    print(f"\n{_SEP}")
    print(f"검토 완료: {len(final_questions)}개 확정 / {removed}개 제거")

    # 삭제된 문제가 있으면 총점 경고
    original_score = sum(q.get("score", 0) for q in passed)
    final_score = sum(q.get("score", 0) for q in final_questions)
    if final_score != original_score:
        print(f"  ⚠️  총점 변경: {original_score}점 → {final_score}점")

    return {
        "passed_questions": final_questions,
        "model_answers": final_answers,
    }
