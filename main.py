"""
실행 예시:
  python main.py                                    ← 인터랙티브 모드 (권장)
  python main.py --pdf lecture --total 100          ← CLI 모드
  python main.py --api-key sk-ant-... --pdf lecture ← API 키 직접 입력
  python main.py --pdf lecture --topic 3장:1:2:1 --topic 5장:2:1:1
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
    p.add_argument("--short-answer", type=int, default=3, help="단답형 문제 수")
    p.add_argument("--essay", type=int, default=3, help="서술형 문제 수")
    p.add_argument("--application", type=int, default=4, help="사례적용형 문제 수")
    p.add_argument("--topic", action="append", dest="topics",
                   metavar="단원명:단답형:서술형:사례적용형",
                   help="단원별 문제 수 지정 (반복 사용 가능). 예: --topic 3장:1:2:1")
    return p.parse_args()


def parse_topics(raw_topics: list[str]) -> list[dict]:
    result = []
    for t in raw_topics:
        parts = t.split(":")
        if len(parts) != 4:
            raise ValueError(
                f"--topic 형식 오류: '{t}'\n올바른 형식: 단원명:단답형:서술형:사례적용형  (예: 3장:1:2:1)"
            )
        result.append({
            "name": parts[0],
            "short_answer_questions": int(parts[1]),
            "essay_questions": int(parts[2]),
            "application_questions": int(parts[3]),
        })
    return result


def build_state(pdf_path: str, total_score: int, format_counts: dict,
                user_topics, additional_requirements) -> ExamState:
    total_questions = sum(format_counts.values())
    return {
        "pdf_path": pdf_path,
        "requirements": {
            "total_score": total_score,
            "format_counts": format_counts,
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
        "_rescue_pool": [],
        "_topic_failure_reasons": {},
        "group_scenarios": {},
        "group_config": [],
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
            format_counts=cfg["format_counts"],
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
            format_counts = {
                "short_answer": sum(t["short_answer_questions"] for t in user_topics),
                "essay":        sum(t["essay_questions"] for t in user_topics),
                "application":  sum(t["application_questions"] for t in user_topics),
            }
        else:
            format_counts = {
                "short_answer": args.short_answer,
                "essay":        args.essay,
                "application":  args.application,
            }

        initial_state = build_state(
            pdf_path=args.pdf,
            total_score=args.total,
            format_counts=format_counts,
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
