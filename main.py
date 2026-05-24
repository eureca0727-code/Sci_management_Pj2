"""
실행 예시:
  python main.py                                    ← 인터랙티브 모드 (권장)
  python main.py --pdf lecture --total 100          ← CLI 모드
  python main.py --api-key sk-ant-... --pdf lecture ← API 키 직접 입력
  python main.py --pdf lecture --topic 3장:2:1 --topic 5장:1:2
"""

import argparse
import os
import sys
from state import ExamState  # config를 import하지 않아 안전


def _resolve_api_key(cli_key: str | None) -> str:
    """CLI 인자 → 환경변수 → 직접 입력 순으로 API 키 확인."""
    if cli_key:
        return cli_key
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if env_key:
        return env_key
    print("\nAnthropoc API Key가 설정되어 있지 않습니다.")
    try:
        key = input("API Key를 입력하세요 (sk-ant-...): ").strip()
    except (EOFError, KeyboardInterrupt):
        key = ""
    return key


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--api-key", help="Anthropic API Key (없으면 환경변수 또는 입력 프롬프트 사용)")
    p.add_argument("--pdf", help="강의자료 PDF 경로 또는 폴더 경로")
    p.add_argument("--total", type=int, default=100, help="총 배점")
    p.add_argument("--concept", type=float, default=0.5, help="개념 문제 비율 (0~1)")
    p.add_argument("--questions", type=int, default=10, help="총 문제 수")
    p.add_argument("--topic", action="append", dest="topics",
                   metavar="단원명:개념:사례",
                   help="단원별 문제 수 지정 (반복 사용 가능). 예: --topic 3장:2:1")
    return p.parse_args()


def parse_topics(raw_topics: list[str]) -> list[dict]:
    result = []
    for t in raw_topics:
        parts = t.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"--topic 형식 오류: '{t}'\n올바른 형식: 단원명:개념문제수:사례문제수  (예: 3장:2:1)"
            )
        result.append({
            "name": parts[0],
            "concept_questions": int(parts[1]),
            "case_questions": int(parts[2]),
        })
    return result


def build_state(pdf_path: str, total_score: int, total_questions: int,
                concept_ratio: float, user_topics, additional_requirements) -> ExamState:
    return {
        "pdf_path": pdf_path,
        "requirements": {
            "total_score": total_score,
            "concept_ratio": concept_ratio,
            "case_ratio": 1 - concept_ratio,
            "total_questions": total_questions,
            "user_topics": user_topics,
            "additional_requirements": additional_requirements,
        },
        "blueprint": None,
        "questions": [],
        "_draft_a": [],
        "_draft_b": [],
        "grounded_solutions": [],
        "unrestricted_solutions": [],
        "judge_results": [],
        "passed_questions": [],
        "failed_questions": [],
        "model_answers": [],
        "retry_count": 0,
        "failure_patterns": [],
        "fill_count": 0,
        "_accepted_questions": [],
        "question_fail_counts": {},
        "_needs_fill": False,
        "output_path": None,
        "_full_blueprint": None,
        "_validation_ok": False,
        "_needs_answer_regen": False,
    }


def main():
    args = parse_args()

    # ── API 키 설정 (import 전에 반드시 처리) ────────────
    api_key = _resolve_api_key(getattr(args, "api_key", None))
    if not api_key:
        print("오류: Anthropic API Key가 필요합니다.")
        sys.exit(1)
    os.environ["ANTHROPIC_API_KEY"] = api_key

    # config-dependent 모듈은 키 설정 후에 import
    from graph import build_graph
    import logger

    # ── 인터랙티브 모드: --pdf 없이 실행 ──────────────────
    if not args.pdf:
        from interactive import run_wizard
        cfg = run_wizard(pdf_folder="lecture")
        initial_state = build_state(
            pdf_path=cfg["pdf_folder"],
            total_score=cfg["total_score"],
            total_questions=cfg["total_questions"],
            concept_ratio=cfg["concept_ratio"],
            user_topics=cfg["user_topics"],
            additional_requirements=cfg["additional_requirements"],
        )

    # ── CLI 모드: --pdf 지정 ──────────────────────────────
    else:
        if not os.path.exists(args.pdf):
            raise FileNotFoundError(f"경로를 찾을 수 없음: {args.pdf}")

        user_topics = None
        if args.topics:
            user_topics = parse_topics(args.topics)
            total_q = sum(t["concept_questions"] + t["case_questions"] for t in user_topics)
            total_concept = sum(t["concept_questions"] for t in user_topics)
            concept_ratio = total_concept / total_q if total_q else 0.5
        else:
            total_q = args.questions
            concept_ratio = args.concept

        initial_state = build_state(
            pdf_path=args.pdf,
            total_score=args.total,
            total_questions=total_q,
            concept_ratio=concept_ratio,
            user_topics=user_topics,
            additional_requirements=None,
        )

    app = build_graph()
    final_state = app.invoke(initial_state)

    print(f"\n완료: {len(final_state['passed_questions'])}개 문제 생성")
    print(f"결과물: exams/ 폴더 확인")
    logger.show_token_summary()


if __name__ == "__main__":
    main()
