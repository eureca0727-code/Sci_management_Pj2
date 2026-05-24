import json
import anthropic
from state import ExamState
from prompts.templates import BLUEPRINT_EDITOR
from utils import parse_json, cached_create
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_CONFIRM = {"", "ㅇ", "ㅇㅇ", "응", "예", "네", "ok", "yes",
            "확정", "좋아", "됐어", "괜찮아", "완료", "done", "y", "ㅇㅋ"}

_SEP = "═" * 54


def _display(blueprint: dict) -> None:
    topics = blueprint.get("topics", [])
    print(f"\n{_SEP}")
    for i, t in enumerate(topics, 1):
        group = f"  [대문제 그룹 {t['group_id'] + 1}]" if "group_id" in t else ""
        print(f"  {i}. {t.get('name','?')}{group}")
        print(f"       단답형 {t.get('short_answer_questions', 0)}문제 / "
              f"서술형 {t.get('essay_questions', 0)}문제 / "
              f"사례적용형 {t.get('application_questions', 0)}문제 / "
              f"난이도 {t.get('difficulty', '?')}")
    total_q = sum(
        t.get("short_answer_questions", 0) + t.get("essay_questions", 0)
        + t.get("application_questions", 0)
        for t in topics
    )
    print(f"\n  총 {total_q}문제")
    print(_SEP)


def run(state: ExamState) -> dict:
    logger.section("STEP 2.5 — Blueprint Review")
    blueprint = dict(state["blueprint"])

    _display(blueprint)
    print("\n수정할 사항을 자연어로 입력하세요.")
    print("예: '1번이랑 2번 같은 대문제로 묶어줘', '3번 사례 문제 추가해줘', '4번 삭제해줘'")
    print("없으면 Enter로 확정\n")

    while True:
        user_input = input("> ").strip()

        if user_input.lower() in _CONFIRM:
            # format_counts와 총합 검증
            fmt = state["requirements"].get("format_counts", {})
            topics = blueprint.get("topics", [])
            actual = {
                "short_answer": sum(t.get("short_answer_questions", 0) for t in topics),
                "essay":        sum(t.get("essay_questions", 0) for t in topics),
                "application":  sum(t.get("application_questions", 0) for t in topics),
            }
            mismatches = [
                f"{k} {fmt.get(k,0)}개 요구 → 블루프린트 {actual[k]}개"
                for k in ("short_answer", "essay", "application")
                if actual[k] != int(fmt.get(k, 0))
            ]
            if mismatches:
                print("\n  ⚠️  문제 수가 초기 설정과 다릅니다:")
                for m in mismatches:
                    print(f"     {m}")
                print("  그대로 확정하려면 Enter, 수정하려면 수정 내용 입력\n")
                continue
            print("\n블루프린트 확정. 문제 출제를 시작합니다...\n")
            break

        response = cached_create(
            _client,
            model=config.MODEL,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": BLUEPRINT_EDITOR.format(
                    current_blueprint=json.dumps(blueprint, ensure_ascii=False, indent=2),
                    user_request=user_input,
                ),
            }],
        )
        logger.record_tokens("BlueprintReview", response.usage)

        updated = parse_json(response.content[0].text)
        if not isinstance(updated, dict) or "topics" not in updated:
            print("  ⚠️  수정 실패. 다시 입력해주세요.\n")
            continue

        summary = updated.pop("change_summary", "")
        blueprint = updated

        if summary:
            print(f"\n  ✅ {summary}")

        _display(blueprint)
        print("\n추가 수정사항을 입력하세요. (없으면 Enter로 확정)\n")

    # group_id 기반 group_config 추출
    group_map: dict[int, list[str]] = {}
    for t in blueprint.get("topics", []):
        gid = t.get("group_id")
        if gid is not None:
            group_map.setdefault(int(gid), []).append(t.get("name", ""))

    group_config = [
        {"group_id": gid, "topic_names": names}
        for gid, names in sorted(group_map.items())
    ]

    return {
        "blueprint": blueprint,
        "_full_blueprint": blueprint,
        "group_config": group_config,
    }
