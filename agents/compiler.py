import os
import re
from datetime import datetime
from docx import Document
from docx.shared import RGBColor
from state import ExamState, Question
import logger

_OUTPUT_DIR = "exams"

_KR_NUM = {
    "한": 1, "하나": 1, "일": 1,
    "두": 2, "둘": 2, "이": 2,
    "세": 3, "셋": 3, "삼": 3,
    "네": 4, "넷": 4, "사": 4,
    "다섯": 5, "오": 5,
    "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7,
    "여덟": 8, "팔": 8,
    "아홉": 9, "구": 9,
    "열": 10, "십": 10,
}


def _parse_group_config(additional: str):
    """'N문제씩 짝지어서 M개의 대문제' 패턴 파싱 → (group_size, group_count)."""
    if not additional or "대문제" not in additional:
        return None, None

    def _to_int(token: str):
        return int(token) if token.isdigit() else _KR_NUM.get(token)

    size_m = re.search(r'(\d+|\w+)\s*문제씩', additional)
    count_m = re.search(r'(\d+|\w+)\s*개(?:의)?\s*대문제', additional)

    group_size  = _to_int(size_m.group(1))  if size_m  else 2
    group_count = _to_int(count_m.group(1)) if count_m else None
    return group_size, group_count


def _add_heading(doc: Document, text: str, level: int = 1):
    p = doc.add_heading(text, level=level)
    if p.runs:
        p.runs[0].font.color.rgb = RGBColor(0, 0, 0)


def _build_exam(doc: Document, questions: list[Question], requirements: dict,
                group_scenarios: dict | None = None):
    doc.add_heading("EXAM", 0)
    doc.add_paragraph(f"Total: {requirements.get('total_score', 100)} points")
    doc.add_paragraph()

    additional = requirements.get("additional_requirements", "") or ""
    group_size, group_count = _parse_group_config(additional)

    # 출력 순서: 개념 먼저, 사례 나중
    ordered = (
        [q for q in questions if q.get("type") == "concept"] +
        [q for q in questions if q.get("type") == "case"]
    )

    if group_size and group_count:
        # ── 대문제 구조 ───────────────────────────────────────
        grouped_total = group_size * group_count
        grouped_qs    = ordered[:grouped_total]
        standalone_qs = ordered[grouped_total:]

        for g in range(group_count):
            chunk = grouped_qs[g * group_size:(g + 1) * group_size]
            if not chunk:
                break
            total_score = sum(q.get("score", 0) for q in chunk)
            _add_heading(doc, f"대문제 {g + 1}  ({total_score}pts)", level=1)

            # 공통 시나리오가 있으면 대문제 앞에 출력
            scenario = (group_scenarios or {}).get(g)
            if scenario:
                p = doc.add_paragraph("다음 사례를 읽고 아래 물음에 답하시오.")
                p.runs[0].bold = True
                doc.add_paragraph(scenario)
                doc.add_paragraph()

            for sub_i, q in enumerate(chunk, 1):
                score = q.get("score", "?")
                doc.add_paragraph(
                    f"({sub_i}) ({score}pts)  {q.get('content', '')}",
                    style="List Number",
                )
                doc.add_paragraph()

        if standalone_qs:
            _add_heading(doc, "추가 문제", level=1)
            for seq, q in enumerate(standalone_qs, grouped_total + 1):
                score = q.get("score", "?")
                doc.add_paragraph(
                    f"[{seq}] ({score}pts)  {q.get('content', '')}",
                    style="List Number",
                )
                doc.add_paragraph()

    else:
        # ── 기본 구조 (파트 I / II) ───────────────────────────
        concept_qs = [q for q in ordered if q.get("type") == "concept"]
        case_qs    = [q for q in ordered if q.get("type") == "case"]
        seq = 1

        if concept_qs:
            _add_heading(doc, "Part I — Concept Questions")
            for q in concept_qs:
                score = q.get("score", "?")
                doc.add_paragraph(f"[{seq}] ({score}pts)  {q.get('content', '')}",
                                   style="List Number")
                doc.add_paragraph()
                seq += 1

        if case_qs:
            _add_heading(doc, "Part II — Case Analysis Questions")
            for q in case_qs:
                score = q.get("score", "?")
                doc.add_paragraph(f"[{seq}] ({score}pts)  {q.get('content', '')}",
                                   style="List Number")
                doc.add_paragraph()
                seq += 1


def _build_answer_key(doc: Document, model_answers: list[dict],
                      questions: list[Question]):
    # Build ordered list: concept first, then case — matching exam order
    ordered = sorted(
        questions,
        key=lambda q: (0 if q.get("type") == "concept" else 1, q.get("id", ""))
    )
    seq_map = {q["id"]: i + 1 for i, q in enumerate(ordered)}
    doc.add_heading("MODEL ANSWERS & RUBRIC", 0)

    # Output answers in exam display order
    answer_map = {a["question_id"]: a for a in model_answers}
    for q in ordered:
        qid = q["id"]
        ans = answer_map.get(qid)
        if not ans:
            continue
        seq = seq_map[qid]
        _add_heading(doc, f"[{seq}]  ({q.get('type','').upper()})", level=2)

        doc.add_paragraph("Model Answer:", style="Heading 3")
        doc.add_paragraph(ans.get("model_answer", ""))

        if ans.get("key_concepts"):
            doc.add_paragraph("Key Concepts: " + ", ".join(str(k) for k in ans["key_concepts"]))

        doc.add_paragraph("Rubric:", style="Heading 3")
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text = "Item", "Points", "Criteria"

        for item in ans.get("rubric", []):
            if not isinstance(item, dict):
                continue
            row = table.add_row().cells
            row[0].text = str(item.get("item", ""))
            row[1].text = str(item.get("points", ""))
            row[2].text = str(item.get("criteria", ""))

        doc.add_paragraph()


def run(state: ExamState) -> dict:
    logger.section("STEP 9 — Exam Compilation")
    passed        = state["passed_questions"]
    model_answers = state["model_answers"]
    requirements  = state["requirements"]

    concept_count = sum(1 for q in passed if q.get("type") == "concept")
    case_count    = sum(1 for q in passed if q.get("type") == "case")
    logger.log("Compiler", f"개념 {concept_count}문항 + 사례 {case_count}문항 → DOCX 생성 중...")

    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%m%d_%H%M")

    exam_doc = Document()
    _build_exam(exam_doc, passed, requirements, state.get("group_scenarios", {}))
    exam_path = os.path.join(_OUTPUT_DIR, f"exam_{ts}.docx")
    exam_doc.save(exam_path)
    logger.log("Compiler", f"✅ 시험지 저장: {exam_path}")

    answer_doc = Document()
    _build_answer_key(answer_doc, model_answers, passed)
    answer_path = os.path.join(_OUTPUT_DIR, f"answer_key_{ts}.docx")
    answer_doc.save(answer_path)
    logger.log("Compiler", f"✅ 모범답안 저장: {answer_path}")

    return {"output_path": exam_path}
