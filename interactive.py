import os


def _input(prompt: str) -> str:
    return input(prompt).strip()


def scan_pdfs(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf"))


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

    # ── 2. 배점 ──────────────────────────────────────────
    print("\n[기본 설정]")
    raw = _input("총 배점을 입력하세요 (기본값 100): ")
    total_score = int(raw) if raw else 100

    # ── 3. 단원별 문제 수 ────────────────────────────────
    print("\n[단원별 문제 수]")
    print("단원을 직접 지정하시겠습니까? (y/n, 기본값 n)")
    print("  y → 단원명·개념문제수·사례문제수 직접 입력")
    print("  n → 총 문제 수만 입력하고 AI가 단원 배분")
    use_topics = _input("> ").lower()

    user_topics = None
    total_questions = 10
    concept_ratio = 0.5

    if use_topics == "y":
        print("\n단원명, 개념 문제 수, 사례 문제 수를 한 줄씩 입력하세요.")
        print("형식: 단원명 개념문제수 사례문제수   (예: 3장 2 1)")
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
            if len(parts) != 3:
                print("  형식 오류 — 다시 입력하세요. (예: 3장 2 1)")
                continue
            try:
                user_topics.append({
                    "name": parts[0],
                    "concept_questions": int(parts[1]),
                    "case_questions": int(parts[2]),
                })
            except ValueError:
                print("  문제 수는 숫자로 입력하세요.")

        if user_topics:
            total_questions = sum(
                t["concept_questions"] + t["case_questions"] for t in user_topics
            )
            total_concept = sum(t["concept_questions"] for t in user_topics)
            concept_ratio = total_concept / total_questions if total_questions else 0.5
    else:
        raw = _input("총 문제 수 (기본값 10): ")
        total_questions = int(raw) if raw else 10
        raw = _input("개념 문제 비율 0~1 (기본값 0.5): ")
        concept_ratio = float(raw) if raw else 0.5

    # ── 4. 추가 요구사항 ─────────────────────────────────
    print("\n[추가 요구사항]")
    print("추가로 반영할 사항이 있으면 입력하세요. (없으면 Enter)")
    print("예: '서술형만 출제', '영어 용어 반드시 포함', '난이도 높게'")
    additional = _input("> ")

    # ── 5. 최종 확인 ─────────────────────────────────────
    print("\n" + "=" * 52)
    print("  [설정 확인]")
    print("=" * 52)
    print(f"강의 폴더   : {pdf_folder}/  ({len(pdfs)}개 파일)")
    print(f"총 배점     : {total_score}점")
    print(f"총 문제 수  : {total_questions}문제")
    if user_topics:
        print("단원 구성   :")
        for t in user_topics:
            print(f"  · {t['name']} — 개념 {t['concept_questions']}문제 / 사례 {t['case_questions']}문제")
    else:
        print(f"문제 비율   : 개념 {concept_ratio:.0%} / 사례 {1 - concept_ratio:.0%}")
    if additional:
        print(f"추가 요구사항: {additional}")
    print("=" * 52)

    confirm = _input("\n위 설정으로 문제 생성을 시작하시겠습니까? (y/n): ").lower()
    if confirm != "y":
        print("취소되었습니다.")
        raise SystemExit(0)

    print("\n문제 생성을 시작합니다...\n")

    return {
        "pdf_folder": pdf_folder,
        "total_score": total_score,
        "total_questions": total_questions,
        "concept_ratio": concept_ratio,
        "user_topics": user_topics,
        "additional_requirements": additional if additional else None,
    }
