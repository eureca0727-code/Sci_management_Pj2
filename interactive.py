import os
import json

_SETTINGS_FILE = ".cache/last_settings.json"


def _input(prompt: str) -> str:
    return input(prompt).strip()


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


def _show_settings(cfg: dict, pdf_folder: str, pdfs: list[str]):
    print(f"강의 폴더   : {pdf_folder}/  ({len(pdfs)}개 파일)")
    print(f"총 배점     : {cfg['total_score']}점")
    fc = cfg.get("format_counts", {})
    total_q = sum(fc.values()) if fc else cfg.get("total_questions", 0)
    print(f"총 문제 수  : {total_q}문제")
    if cfg.get("user_topics"):
        print("단원 구성   :")
        for t in cfg["user_topics"]:
            print(f"  · {t['name']} — "
                  f"단답형 {t.get('short_answer_questions',0)} / "
                  f"서술형 {t.get('essay_questions',0)} / "
                  f"사례적용형 {t.get('application_questions',0)}")
    elif fc:
        print(f"문제 형식   : 단답형 {fc.get('short_answer',0)}개 / "
              f"서술형 {fc.get('essay',0)}개 / "
              f"사례적용형 {fc.get('application',0)}개")
    if cfg.get("additional_requirements"):
        print(f"추가 요구사항: {cfg['additional_requirements']}")


def run_wizard(pdf_folder: str = "lecture") -> dict:
    print("\n" + "=" * 52)
    print("  시험 문제 생성기")
    print("=" * 52)

    # ── 1. 강의 파일 확인 ────────────────────────────────
    print(f"\n[강의 파일 확인]")
    pdfs = scan_pdfs(pdf_folder)

    if not pdfs:
        print(f"⚠️  '{pdf_folder}/' 폴더에 PDF 파일이 없습니다.")
        print(f"   PDF를 '{pdf_folder}/' 폴더에 넣고 다시 실행하세요.")
        raise SystemExit(1)

    print(f"'{pdf_folder}/' 폴더에서 {len(pdfs)}개 파일을 찾았습니다:\n")
    for i, f in enumerate(pdfs, 1):
        print(f"  {i}. {f}")
    print(f"\n위 {len(pdfs)}개 파일 전체가 강의 자료로 사용됩니다.")

    # ── 2. 이전 설정 재사용 여부 ─────────────────────────
    prev = load_settings()
    if prev:
        print("\n[이전 설정이 있습니다]")
        _show_settings(prev, pdf_folder, pdfs)
        ans = _input("\n이 설정을 그대로 사용하시겠습니까? (y/n): ").lower()
        if ans == "y":
            print("\n이전 설정으로 문제 생성을 시작합니다...\n")
            prev["pdf_folder"] = pdf_folder
            # 구 형식(concept_ratio / concept_questions) → 신 형식 마이그레이션
            if "format_counts" not in prev:
                total_q = prev.get("total_questions", 10)
                concept_ratio = prev.get("concept_ratio", 0.5)
                sa = max(1, round(total_q * concept_ratio / 2))
                essay = max(1, round(total_q * concept_ratio / 2))
                app = max(0, total_q - sa - essay)
                prev["format_counts"] = {"short_answer": sa, "essay": essay, "application": app}
            # user_topics 구 형식 마이그레이션
            if prev.get("user_topics"):
                migrated = []
                for t in prev["user_topics"]:
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
                prev["user_topics"] = migrated
            return prev

    # ── 3. 배점 ──────────────────────────────────────────
    print("\n[기본 설정]")
    raw = _input("총 배점을 입력하세요 (기본값 100): ")
    total_score = int(raw) if raw else 100

    # ── 4. 단원별 문제 수 ────────────────────────────────
    print("\n[단원별 문제 수]")
    print("단원을 직접 지정하시겠습니까? (y/n, 기본값 n)")
    print("  y → 단원명·단답형수·서술형수·사례적용형수 직접 입력")
    print("  n → 문제 형식별 수만 입력하고 AI가 단원 배분")
    use_topics = _input("> ").lower()

    user_topics = None
    format_counts = {}

    if use_topics == "y":
        print("\n단원명, 단답형 수, 서술형 수, 사례적용형 수를 한 줄씩 입력하세요.")
        print("형식: 단원명 단답형수 서술형수 사례적용형수   (예: 3장 1 2 1)")
        print("입력이 끝나면 빈 줄에서 Enter를 누르세요.\n")
        user_topics = []
        while True:
            line = _input("> ")
            if not line:
                if not user_topics:
                    print("단원 입력이 없어 AI가 자동 배분합니다.")
                    user_topics = None
                break
            parts = line.split()
            if len(parts) != 4:
                print("  형식 오류 — 다시 입력하세요. (예: 3장 1 2 1)")
                continue
            try:
                user_topics.append({
                    "name": parts[0],
                    "short_answer_questions": int(parts[1]),
                    "essay_questions": int(parts[2]),
                    "application_questions": int(parts[3]),
                })
            except ValueError:
                print("  문제 수는 숫자로 입력하세요.")

        if user_topics:
            format_counts = {
                "short_answer": sum(t["short_answer_questions"] for t in user_topics),
                "essay":        sum(t["essay_questions"] for t in user_topics),
                "application":  sum(t["application_questions"] for t in user_topics),
            }

    if not user_topics:
        # 자동 배분 — 형식별 문제 수만 입력
        print("\n[문제 형식 설정]")
        raw = _input("단답형(Short Answer) 문제 수 (기본값 3): ")
        sa = int(raw) if raw else 3
        raw = _input("서술형(Essay) 문제 수 (기본값 3): ")
        essay = int(raw) if raw else 3
        raw = _input("사례적용형(Application) 문제 수 (기본값 4): ")
        app = int(raw) if raw else 4
        format_counts = {"short_answer": sa, "essay": essay, "application": app}

    total_questions = sum(format_counts.values())

    # ── 5. 추가 요구사항 ─────────────────────────────────
    print("\n[추가 요구사항]")
    print("추가로 반영할 사항이 있으면 입력하세요. (없으면 Enter)")
    print("예: '영어 용어 반드시 포함', '난이도 높게'")
    additional = _input("> ")

    # ── 6. 최종 확인 ─────────────────────────────────────
    print("\n" + "=" * 52)
    print("  [설정 확인]")
    print("=" * 52)
    cfg = {
        "pdf_folder": pdf_folder,
        "total_score": total_score,
        "total_questions": total_questions,
        "format_counts": format_counts,
        "user_topics": user_topics,
        "additional_requirements": additional if additional else None,
    }
    _show_settings(cfg, pdf_folder, pdfs)
    print("=" * 52)

    confirm = _input("\n위 설정으로 문제 생성을 시작하시겠습니까? (y/n): ").lower()
    if confirm != "y":
        print("취소되었습니다.")
        raise SystemExit(0)

    save_settings(cfg)
    print("\n문제 생성을 시작합니다...\n")
    return cfg
