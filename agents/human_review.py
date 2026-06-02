import anthropic
from state import ExamState
from prompts.templates import QUESTION_EDITOR
from utils import parse_json, cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_SEP = "─" * 62


def _print_question(idx: int, total: int, q: dict) -> None:
    print(f"\n{_SEP}")
    print(f"[{idx}/{total}]  {q['id']}  |  {q.get('type','?')}  |  "
          f"{q.get('topic','?')}  |  {q.get('score', 0)}점")
    print(_SEP)
    scenario = (q.get("scenario") or "").strip()
    if scenario:
        print(f"[사례] {scenario}\n")
    print(q.get("content", ""))
    print(f"\n  📌 의도 답: {str(q.get('intended_answer', ''))[:120]}...")


def _edit_question(q: dict) -> dict:
    """자연어 요구사항을 LLM에 전달해 문제를 수정. 미리보기 + 확인 루프."""
    q = dict(q)

    while True:
        print("\n  ── 수정 요구사항 입력 ────────────────────────────────")
        print("  예: '난이도 낮춰줘', '시나리오랑 더 연결되게', 'PDCA 대신 5Why 넣어줘'")
        user_request = input("  요구사항 (Enter=취소): ").strip()

        if not user_request:
            print("  수정 취소.")
            return q

        print("\n  ⏳ 수정 중...")
        response = cached_create(
            _client,
            model=config.MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": QUESTION_EDITOR.format(
                    question_type=q.get("type", ""),
                    topic=q.get("topic", ""),
                    scenario=q.get("scenario", "") or "없음",
                    content=q.get("content", ""),
                    score=q.get("score", 0),
                    intended_answer=q.get("intended_answer", ""),
                    user_request=user_request,
                ),
            }],
        )
        logger.record_tokens("HumanReview", response.usage)

        updated = parse_json(response.content[0].text)
        if not isinstance(updated, dict) or "content" not in updated:
            print("  ⚠️  수정 실패. 다시 입력해주세요.")
            continue

        summary = updated.pop("edit_summary", "")

        # 미리보기
        print(f"\n  ── 수정 결과 {'─' * 42}")
        if summary:
            print(f"  ✏️  {summary}")
        new_scenario = updated.get("scenario", "").strip()
        if new_scenario and new_scenario != "없음":
            print(f"\n  [사례] {new_scenario}")
        print(f"\n  {updated.get('content', '')}")
        print(f"  배점: {updated.get('score', q.get('score', 0))}점")
        print(f"  의도 답: {str(updated.get('intended_answer', ''))[:120]}...")

        print(f"\n  확정(Enter) / 재수정(r) / 취소(c): ", end="", flush=True)
        confirm = input().strip().lower()

        if confirm == "c":
            print("  수정 취소. 원본 유지.")
            return q

        if confirm == "r":
            continue  # 미리보기 루프 재시작 아닌, 요구사항 재입력

        # 확정
        q["content"] = updated.get("content", q["content"])
        q["intended_answer"] = updated.get("intended_answer", q["intended_answer"])
        q["score"] = int(updated.get("score", q["score"]))
        new_s = updated.get("scenario", "").strip()
        if new_s and new_s != "없음":
            q["scenario"] = new_s
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
    print("  Enter = 통과    e = 수정(자연어)    d = 삭제\n")

    final_questions = []
    final_answers = []
    edited_ids: set[str] = set()

    for idx, q in enumerate(passed, 1):
        _print_question(idx, total, q)
        print(f"\n  선택 (Enter/e/d): ", end="", flush=True)

        choice = input().strip().lower()

        if choice == "d":
            logger.log("HumanReview", f"❌ [{q['id']}] 삭제")
            continue

        if choice == "e":
            original_content = q.get("content", "")
            q = _edit_question(q)
            if q.get("content", "") != original_content:
                edited_ids.add(q["id"])
                logger.log("HumanReview", f"✏️  [{q['id']}] 수정 완료 → 답안 재생성 필요")
            else:
                logger.log("HumanReview", f"✅ [{q['id']}] 수정 취소 — 원본 유지")
        else:
            logger.log("HumanReview", f"✅ [{q['id']}] 통과")

        final_questions.append(q)
        ans = answers_map.get(q["id"])
        # 수정된 문제는 기존 답안 버림 → answer_gen에서 새로 생성
        if ans and q["id"] not in edited_ids:
            final_answers.append(ans)

    removed = total - len(final_questions)
    print(f"\n{_SEP}")
    print(f"검토 완료: {len(final_questions)}개 확정 / {removed}개 제거"
          + (f" / {len(edited_ids)}개 수정" if edited_ids else ""))

    original_score = sum(q.get("score", 0) for q in passed)
    final_score = sum(q.get("score", 0) for q in final_questions)
    if final_score != original_score:
        print(f"  ⚠️  총점 변경: {original_score}점 → {final_score}점")

    needs_regen = bool(edited_ids)
    if needs_regen:
        logger.log("HumanReview", f"🔄 수정된 문제 {len(edited_ids)}개 → 답안 재생성")

    return {
        "passed_questions": final_questions,
        "model_answers": final_answers,
        "_needs_answer_regen": needs_regen,
    }
