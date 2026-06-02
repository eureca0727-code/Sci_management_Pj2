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

_SEP  = "─" * 54
_SEP2 = "═" * 54


def _display(blueprint: dict) -> None:
    topics = blueprint.get("topics", [])
    print(f"\n{_SEP}")
    for i, t in enumerate(topics, 1):
        print(f"  {i}. {t.get('name','?')}")
        print(f"       단답형 {t.get('short_answer_questions', 0)}문제 / "
              f"서술형 {t.get('essay_questions', 0)}문제 / "
              f"사례출제형 {t.get('application_questions', 0)}문제 / "
              f"난이도 {t.get('difficulty', '?')}")
    total_q = sum(
        t.get("short_answer_questions", 0) + t.get("essay_questions", 0)
        + t.get("application_questions", 0)
        for t in topics
    )
    print(f"\n  총 {total_q}문제")
    print(_SEP)


def _apply_groups(topics: list[dict], app_groups: list[int]) -> list[dict]:
    """app_groups 패턴을 사례출제형 단원에 적용해 group_id 배정 (코드 레벨)."""
    for t in topics:
        t.pop("group_id", None)

    if not app_groups:
        return topics

    app_topics = [t for t in topics if t.get("application_questions", 0) > 0]
    if sum(app_groups) != len(app_topics):
        return topics  # 수가 안 맞으면 배정 불가 — 호출부에서 처리

    group_id = 0
    idx = 0
    for size in app_groups:
        if size >= 2:
            for i in range(size):
                app_topics[idx + i]["group_id"] = group_id
            group_id += 1
        idx += size

    return topics


def _show_group_assignment(app_topics: list[dict], app_groups: list[int]) -> None:
    """현재 group_id 배정 상태를 출력."""
    print(f"\n{_SEP}")
    print("  [사례출제형 그룹 배정]")
    print(_SEP)

    groups: dict[int, list[str]] = {}
    solos: list[str] = []
    for t in app_topics:
        gid = t.get("group_id")
        if gid is not None:
            groups.setdefault(gid, []).append(t["name"])
        else:
            solos.append(t["name"])

    for gid in sorted(groups):
        names = ", ".join(groups[gid])
        print(f"  대문제 {gid + 1}: {names}")
    for name in solos:
        print(f"  독립 문제: {name}")
    print(_SEP)


def _structured_group_step(blueprint: dict, app_groups: list[int]) -> dict:
    """
    사례출제형 단원을 명시적으로 그룹에 배정하는 구조화 스텝.
    LLM 없이 코드 레벨로 group_id를 확정한다.
    """
    topics = blueprint.get("topics", [])
    app_topics = [t for t in topics if t.get("application_questions", 0) > 0]

    if not app_topics:
        return blueprint

    # app_groups가 없거나 모두 독립이면 배정 불필요
    has_real_groups = any(g >= 2 for g in app_groups)
    if not app_groups or not has_real_groups:
        logger.log("BlueprintReview", "그룹 설정 없음 — 사례출제형 전부 독립 문제")
        return blueprint

    print(f"\n{_SEP2}")
    print("  [사례출제형 그룹 배정]")
    print(_SEP2)
    print(f"  입력하신 그룹 패턴: {','.join(str(g) for g in app_groups)}")
    print(f"\n  블루프린트의 사례출제형 단원 ({len(app_topics)}개):")
    for i, t in enumerate(app_topics, 1):
        print(f"    {i}. {t['name']}  (사례출제형 {t.get('application_questions',0)}문항)")

    # 패턴과 단원 수가 맞지 않으면 사용자가 다시 지정
    while sum(app_groups) != len(app_topics):
        print(f"\n  ⚠️  패턴 합계({sum(app_groups)})와 단원 수({len(app_topics)})가 다릅니다.")
        print(f"  합계가 {len(app_topics)}인 패턴을 다시 입력하세요.  (Enter → 모두 독립)")
        raw = input("> ").strip()
        if not raw:
            app_groups = []
            break
        try:
            new_groups = [int(x.strip()) for x in raw.split(",") if x.strip()]
            if sum(new_groups) == len(app_topics) and all(g >= 1 for g in new_groups):
                app_groups = new_groups
            else:
                print(f"  ⚠️  합계가 {len(app_topics)}이어야 합니다.")
        except ValueError:
            print("  숫자와 쉼표만 입력하세요.")

    if not app_groups or not any(g >= 2 for g in app_groups):
        logger.log("BlueprintReview", "그룹 없이 모두 독립 문제로 확정")
        return blueprint

    # 기본 배정 적용 (순서대로)
    topics = _apply_groups(topics, app_groups)
    blueprint = {**blueprint, "topics": topics}
    app_topics = [t for t in topics if t.get("application_questions", 0) > 0]
    _show_group_assignment(app_topics, app_groups)

    # 순서 재배정 안내
    print("\n  기본 배정은 블루프린트 단원 순서대로 묶습니다.")
    print("  순서를 바꾸려면 각 그룹에 포함할 단원 번호를 입력하세요.")

    # 그룹별 크기 계산
    real_groups = [g for g in app_groups if g >= 2]
    example_parts = []
    cursor = 1
    for g in app_groups:
        nums = ",".join(str(cursor + i) for i in range(g))
        example_parts.append(nums)
        cursor += g
    print(f"  예) '{' / '.join(example_parts)}' → 현재와 동일")

    swapped = _ask_group_reorder(app_topics, app_groups)
    if swapped:
        blueprint = {**blueprint, "topics": topics}

    logger.log("BlueprintReview", "그룹 배정 완료")
    return blueprint


def _ask_group_reorder(app_topics: list[dict], app_groups: list[int]) -> bool:
    """
    사용자가 단원 번호로 그룹을 재배정할 수 있게 한다.
    변경이 있으면 True 반환.
    """
    real_groups = [(i, g) for i, g in enumerate(app_groups) if g >= 2]
    if not real_groups:
        return False

    print(f"\n  그룹 재배정 (없으면 Enter):")
    while True:
        raw = input("  > ").strip()
        if not raw:
            return False

        # "1,2 / 3,4" 또는 "1,2  3,4" 형식 파싱
        sep = "/" if "/" in raw else None
        parts = [p.strip() for p in (raw.split("/") if sep else raw.split())]

        if len(parts) != len(real_groups):
            print(f"  ⚠️  그룹 수({len(real_groups)})에 맞게 {len(real_groups)}개 부분을 입력하세요.")
            print(f"  예) {' / '.join(f'그룹{i+1}번호들' for i,_ in real_groups)}")
            continue

        try:
            assignment: list[list[int]] = []
            all_indices: list[int] = []
            valid = True
            for part, (_, size) in zip(parts, real_groups):
                indices = [int(x.strip()) for x in part.split(",") if x.strip()]
                if len(indices) != size:
                    print(f"  ⚠️  그룹 크기({size})와 입력 수({len(indices)})가 다릅니다.")
                    valid = False
                    break
                if any(i < 1 or i > len(app_topics) for i in indices):
                    print(f"  ⚠️  단원 번호는 1~{len(app_topics)} 사이여야 합니다.")
                    valid = False
                    break
                all_indices.extend(indices)
                assignment.append(indices)

            if not valid:
                continue

            if len(all_indices) != len(set(all_indices)):
                print("  ⚠️  중복된 단원 번호가 있습니다.")
                continue

            # 재배정 적용
            # 먼저 모든 group_id 제거
            for t in app_topics:
                t.pop("group_id", None)

            group_id = 0
            for indices in assignment:
                for idx in indices:
                    app_topics[idx - 1]["group_id"] = group_id
                group_id += 1

            _show_group_assignment(app_topics, app_groups)
            confirm = input("  이 배정으로 확정하시겠습니까? (y/n): ").strip().lower()
            if confirm in ("y", ""):
                return True
            # n이면 다시 입력
        except ValueError:
            print("  ⚠️  숫자와 쉼표만 입력하세요.")


def run(state: ExamState) -> dict:
    logger.section("STEP 2.5 — Blueprint Review")
    blueprint = dict(state["blueprint"])
    app_groups: list[int] = state.get("requirements", {}).get("app_groups", [])

    _display(blueprint)
    print("\n단원 구성·난이도 등 수정할 사항을 입력하세요.")
    print("예: '3번 단원 난이도 어렵게', '5번 단원 삭제', '서술형 1개 더 추가'")
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
            print("\n블루프린트 확정. 그룹 배정으로 진행합니다...\n")
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

    # ── 그룹 배정 (코드 레벨) ─────────────────────────────
    blueprint = _structured_group_step(blueprint, list(app_groups))

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
