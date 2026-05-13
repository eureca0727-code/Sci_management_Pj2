"""
실행 예시:
  python main.py --pdf lecture.pdf --concept 0.6 --total 100
"""

import argparse
import os
from graph import build_graph
from state import ExamState
import logger


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", required=True, help="강의자료 PDF 경로")
    p.add_argument("--total", type=int, default=100, help="총 배점")
    p.add_argument("--concept", type=float, default=0.5,
                   help="개념 문제 비율 (0~1)")
    p.add_argument("--questions", type=int, default=10, help="총 문제 수")
    return p.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.pdf):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없음: {args.pdf}")

    initial_state: ExamState = {
        "pdf_path": args.pdf,
        "requirements": {
            "total_score": args.total,
            "concept_ratio": args.concept,
            "case_ratio": 1 - args.concept,
            "total_questions": args.questions,
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
        "output_path": None,
    }

    app = build_graph()
    final_state = app.invoke(initial_state)

    print(f"\n완료: {len(final_state['passed_questions'])}개 문제 생성")
    print(f"시험지: exam_output.docx  /  모범답안: answer_key.docx")
    logger.show_token_summary()


if __name__ == "__main__":
    main()
