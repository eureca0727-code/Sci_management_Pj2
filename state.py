from typing import TypedDict, List, Optional


class Question(TypedDict):
    id: str
    type: str             # "concept" | "case"
    topic: str
    content: str
    intended_answer: str
    methodology: Optional[str]   # case 문제만
    source_slides: List[int]
    professor: str        # "A" | "B"
    score: int


class StudentSolution(TypedDict):
    question_id: str
    answer: str
    citations: List[str]  # ["슬라이드 3", "슬라이드 7", ...]
    mode: str             # "grounded" | "unrestricted"
    run_index: int
    insufficient: bool    # INSUFFICIENT_EVIDENCE 반환 여부


class JudgeResult(TypedDict):
    question_id: str
    passed: bool
    lecture_dependency: float   # grounded - unrestricted 정답률 차이
    citation_jaccard: float     # 의도 슬라이드 vs 학생 인용 슬라이드 Jaccard
    ambiguity_score: float      # N-run 답 불일치율 (낮을수록 명확한 문제)
    answer_match: float         # 의도 답 vs 학생 답 유사도
    failure_reason: Optional[str]


class ExamState(TypedDict):
    # ── 입력 ──────────────────────────────────────────
    pdf_path: str
    requirements: dict          # {"total_score": 100, "concept_ratio": 0.5, ...}

    # ── 블루프린트 (Chair) ─────────────────────────────
    blueprint: Optional[dict]   # 단원별 배점/난이도/유형 분배표

    # ── 출제 (Professor Meeting) ──────────────────────
    questions: List[Question]

    # ── 검증 (Student) ────────────────────────────────
    grounded_solutions: List[StudentSolution]
    unrestricted_solutions: List[StudentSolution]

    # ── 판정 (Judge) ──────────────────────────────────
    judge_results: List[JudgeResult]
    passed_questions: List[Question]
    failed_questions: List[Question]

    # ── 모범답안 (Answer Generator) ───────────────────
    model_answers: List[dict]

    # ── 교수 초안 (Professor Meeting 내부 임시) ───────
    _draft_a: List[dict]
    _draft_b: List[dict]

    # ── 루프 제어 ─────────────────────────────────────
    retry_count: int
    failure_patterns: List[str]  # 장기 메모리: 실패 패턴 누적
    fill_count: int              # Chair 부족분 보충 시도 횟수
    _accepted_questions: List[Question]  # fill 라운드 간 누적 채택 문제
    question_fail_counts: dict   # {"topic:type": 실패횟수} — 문제별 재출제 횟수 추적

    # ── 출력 ──────────────────────────────────────────
    output_path: Optional[str]
