import os
import json

_SETTINGS_FILE = ".cache/last_settings.json"


def scan_pdfs(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf"))


def save_settings(cfg: dict):
    os.makedirs(".cache", exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_settings() -> dict | None:
    if not os.path.exists(_SETTINGS_FILE):
        return None
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _inp(prompt: str) -> str:
    return input(prompt).strip()


def _ask_int(prompt: str, default: int) -> int:
    raw = _inp(f"{prompt} (기본값 {default}): ")
    try:
        return int(raw) if raw else default
    except ValueError:
        print(f"  숫자를 입력하세요. 기본값 {default} 사용.")
        return default


def _ask_app_groups(app_count: int) -> list[int]:
    """
    사례출제형 그룹 구성을 묻고 각 그룹의 크기 목록을 반환.
    예: [2, 2], [4], [2, 1, 1], []
    """
    if app_count <= 1:
        return []

    _SEP = "─" * 48
    print(f"\n{_SEP}")
    print("  [사례출제형 그룹 설정]")
    print(f"{_SEP}")
    print("  같은 그룹의 문제는 하나의 공통 시나리오를 공유합니다.")
    print(f"  현재 사례출제형: {app_count}문제\n")
    print("  입력 형식: 각 그룹 크기를 쉼표로 구분 (합계 = 전체 문제 수)")
    print(f"  합계는 반드시 {app_count}이어야 합니다.\n")

    # 예시: app_count에 맞게 자동 생성
    examples = _make_examples(app_count)
    print("  예시:")
    for pattern, desc in examples:
        print(f"    {pattern:<12} →  {desc}")
    print(f"    {'(Enter)':<12} →  모두 독립 문제 (그룹 없음)")
    print(f"{_SEP}\n")

    while True:
        raw = _inp(f"그룹 구성 입력 (합계 {app_count}): ")
        if not raw:
            print("  그룹 없이 모두 독립 문제로 설정합니다.")
            return []
        try:
            groups = [int(x.strip()) for x in raw.split(",") if x.strip()]
            if not groups:
                return []
            if any(g < 1 for g in groups):
                print("  ⚠️  각 값은 1 이상이어야 합니다.")
                continue
            if sum(groups) != app_count:
                print(f"  ⚠️  합계가 {sum(groups)}입니다. {app_count}이어야 합니다.")
                continue
            return groups
        except ValueError:
            print("  ⚠️  숫자와 쉼표만 입력하세요.  예: 2,2")


def _make_examples(n: int) -> list[tuple[str, str]]:
    """app_count n에 맞는 대표 예시 목록."""
    if n == 2:
        return [
            ("2",     "전체 한 그룹  (시나리오 1개, 2문항)"),
            ("1,1",   "모두 독립     (시나리오 없음)"),
        ]
    if n == 3:
        return [
            ("3",     "전체 한 그룹  (시나리오 1개, 3문항)"),
            ("2,1",   "2개 묶음 + 단독 1개"),
            ("1,1,1", "모두 독립     (시나리오 없음)"),
        ]
    if n == 4:
        return [
            ("2,2",     "2개씩 두 그룹  (시나리오 2개, 각 2문항)"),
            ("4",       "전체 한 그룹   (시나리오 1개, 4문항)"),
            ("3,1",     "3개 묶음 + 단독 1개"),
            ("2,1,1",   "2개 묶음 + 단독 2개"),
        ]
    if n == 5:
        return [
            ("2,3",   "2개 그룹 + 3개 그룹"),
            ("3,2",   "3개 그룹 + 2개 그룹"),
            ("2,2,1", "2개 그룹 2개 + 단독 1개"),
        ]
    if n == 6:
        return [
            ("2,2,2", "2개씩 세 그룹"),
            ("3,3",   "3개씩 두 그룹"),
            ("2,4",   "2개 그룹 + 4개 그룹"),
        ]
    # 일반: 균등 분할 예시
    half = n // 2
    return [
        (f"{half},{n - half}", f"{half}개 + {n - half}개 두 그룹"),
        (str(n), f"전체 한 그룹  (시나리오 1개, {n}문항)"),
    ]


def _show_settings(cfg: dict, pdf_folder: str, pdfs: list[str]):
    _SEP = "═" * 48
    print(f"\n{_SEP}")
    print("  [설정 확인]")
    print(_SEP)
    print(f"  강의 폴더   : {pdf_folder}/  ({len(pdfs)}개 파일)")
    print(f"  총 배점     : {cfg['total_score']}점")
    fc = cfg.get("format_counts", {})
    sa  = fc.get("short_answer", 0)
    es  = fc.get("essay", 0)
    app = fc.get("application", 0)
    print(f"  문제 구성   : 단답형 {sa}개 / 서술형 {es}개 / 사례출제형 {app}개  (총 {sa+es+app}문제)")
    ag = cfg.get("app_groups", [])
    if ag:
        groups = [g for g in ag if g >= 2]
        solos  = sum(1 for g in ag if g == 1)
        parts  = [f"그룹{i+1}({g}문항)" for i, g in enumerate(groups)]
        if solos:
            parts.append(f"독립 {solos}문항")
        print(f"  그룹 구성   : {', '.join(parts)}")
    else:
        if app > 0:
            print(f"  그룹 구성   : 모두 독립 문제")
    if cfg.get("additional_requirements"):
        print(f"  추가 요구   : {cfg['additional_requirements']}")
    print(_SEP)


def run_wizard(pdf_folder: str = "lecture") -> dict:
    _SEP_THICK = "═" * 52
    print(f"\n{_SEP_THICK}")
    print("  시험 문제 생성기")
    print(_SEP_THICK)

    # ── 1. 강의 파일 확인 ────────────────────────────────
    print("\n[강의 파일 확인]")
    pdfs = scan_pdfs(pdf_folder)
    if not pdfs:
        print(f"⚠️  '{pdf_folder}/' 폴더에 PDF 파일이 없습니다.")
        print(f"   PDF를 '{pdf_folder}/' 폴더에 넣고 다시 실행하세요.")
        raise SystemExit(1)

    print(f"'{pdf_folder}/' 폴더에서 {len(pdfs)}개 파일을 찾았습니다:")
    for i, f in enumerate(pdfs, 1):
        print(f"  {i}. {f}")

    # ── 2. 이전 설정 재사용 여부 ─────────────────────────
    prev = load_settings()
    if prev:
        print("\n[이전 설정이 있습니다]")
        _show_settings(prev, pdf_folder, pdfs)
        ans = _inp("\n이 설정을 그대로 사용하시겠습니까? (y/n): ").lower()
        if ans == "y":
            prev["pdf_folder"] = pdf_folder
            _migrate_settings(prev)

            # app_groups가 없거나 빈 상태면 그룹 마법사 실행
            app = prev.get("format_counts", {}).get("application", 0)
            if app > 1 and not prev.get("app_groups"):
                print("\n  ※ 이전 설정에 그룹 구성이 없습니다. 새로 설정합니다.")
                prev["app_groups"] = _ask_app_groups(app)
                # additional_requirements에 남아있는 구식 그룹 지시문 제거
                prev["additional_requirements"] = _strip_group_instructions(
                    prev.get("additional_requirements") or ""
                ) or None
                _show_settings(prev, pdf_folder, pdfs)
                save_settings(prev)

            print("\n문제 생성을 시작합니다...\n")
            return prev

    # ── 3. 총 배점 ───────────────────────────────────────
    print("\n[기본 설정]")
    total_score = _ask_int("총 배점", 100)

    # ── 4. 문제 수 ───────────────────────────────────────
    print("\n[문제 수 설정]")
    print("  단답형   : 핵심 개념·정의를 묻는 문제  (2~4문장 답)")
    print("  서술형   : 개념 비교·분석·논술 문제     (자유 형식 논술)")
    print("  사례출제형: 실제 상황에 방법론을 적용하는 문제\n")
    sa  = _ask_int("단답형 문제 수", 3)
    es  = _ask_int("서술형 문제 수", 3)
    app = _ask_int("사례출제형 문제 수", 4)

    format_counts = {"short_answer": sa, "essay": es, "application": app}

    # ── 5. 사례출제형 그룹 설정 ──────────────────────────
    app_groups = _ask_app_groups(app)

    # ── 6. 추가 요구사항 ─────────────────────────────────
    print("\n[추가 요구사항]")
    print("  추가로 반영할 사항이 있으면 입력하세요. (없으면 Enter)")
    print("  예: '영어 용어 반드시 포함', '난이도 높게'")
    additional = _inp("> ")

    # ── 7. 최종 확인 ─────────────────────────────────────
    cfg = {
        "pdf_folder":             pdf_folder,
        "total_score":            total_score,
        "total_questions":        sa + es + app,
        "format_counts":          format_counts,
        "app_groups":             app_groups,
        "user_topics":            None,
        "additional_requirements": additional if additional else None,
    }
    _show_settings(cfg, pdf_folder, pdfs)

    confirm = _inp("\n위 설정으로 문제 생성을 시작하시겠습니까? (y/n): ").lower()
    if confirm != "y":
        print("취소되었습니다.")
        raise SystemExit(0)

    save_settings(cfg)
    print("\n문제 생성을 시작합니다...\n")
    return cfg


_GROUP_KEYWORDS = ("묶어", "묶이", "그룹", "시나리오에", "짝지어", "대문제", "소문항")


def _strip_group_instructions(text: str) -> str:
    """additional_requirements에서 그룹화 관련 문장을 제거 (이제 app_groups가 담당)."""
    if not text:
        return text
    sentences = [s.strip() for s in text.replace(".", ".\n").splitlines() if s.strip()]
    kept = [s for s in sentences if not any(kw in s for kw in _GROUP_KEYWORDS)]
    cleaned = " ".join(kept).strip(" .")
    if cleaned != text.strip():
        print(f"  ※ 추가 요구사항에서 그룹 관련 지시를 제거했습니다.")
        if cleaned:
            print(f"     남은 요구사항: {cleaned}")
    return cleaned


def _migrate_settings(cfg: dict):
    """이전 형식 설정을 현재 형식으로 마이그레이션."""
    if "format_counts" not in cfg:
        total_q = cfg.get("total_questions", 10)
        concept_ratio = cfg.get("concept_ratio", 0.5)
        sa = max(1, round(total_q * concept_ratio / 2))
        essay = max(1, round(total_q * concept_ratio / 2))
        app = max(0, total_q - sa - essay)
        cfg["format_counts"] = {"short_answer": sa, "essay": essay, "application": app}
    if "app_groups" not in cfg:
        cfg["app_groups"] = []
    if cfg.get("user_topics"):
        migrated = []
        for t in cfg["user_topics"]:
            if "concept_questions" in t and "short_answer_questions" not in t:
                c = t.get("concept_questions", 0)
                migrated.append({
                    "name": t["name"],
                    "short_answer_questions": max(1, c // 2),
                    "essay_questions": c - max(1, c // 2),
                    "application_questions": t.get("case_questions", 0),
                })
            else:
                migrated.append(t)
        cfg["user_topics"] = migrated
