from docx import Document
from docx.shared import RGBColor
from state import ExamState, Question
import logger


def _add_heading(doc: Document, text: str, level: int = 1):
    p = doc.add_heading(text, level=level)
    p.runs[0].font.color.rgb = RGBColor(0, 0, 0)


def _build_exam(doc: Document, questions: list[Question], requirements: dict):
    doc.add_heading("EXAM", 0)
    doc.add_paragraph(f"Total: {requirements.get('total_score', 100)} points")
    doc.add_paragraph()

    concept_qs = [q for q in questions if q["type"] == "concept"]
    case_qs    = [q for q in questions if q["type"] == "case"]

    if concept_qs:
        _add_heading(doc, "Part I — Concept Questions")
        for q in concept_qs:
            doc.add_paragraph(f"[{q['id']}] ({q['score']}pts)  {q['content']}",
                               style="List Number")
            doc.add_paragraph()

    if case_qs:
        _add_heading(doc, "Part II — Case Analysis Questions")
        for q in case_qs:
            doc.add_paragraph(f"[{q['id']}] ({q['score']}pts)  {q['content']}",
                               style="List Number")
            doc.add_paragraph()


def _build_answer_key(doc: Document, model_answers: list[dict],
                      questions: list[Question]):
    qmap = {q["id"]: q for q in questions}
    doc.add_heading("MODEL ANSWERS & RUBRIC", 0)

    for ans in model_answers:
        qid = ans["question_id"]
        q = qmap.get(qid, {})
        _add_heading(doc, f"{qid}  ({q.get('type','').upper()})", level=2)

        doc.add_paragraph("Model Answer:", style="Heading 3")
        doc.add_paragraph(ans["model_answer"])

        if ans.get("key_concepts"):
            doc.add_paragraph("Key Concepts: " + ", ".join(ans["key_concepts"]))

        doc.add_paragraph("Rubric:", style="Heading 3")
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text = "Item", "Points", "Criteria"

        for item in ans.get("rubric", []):
            row = table.add_row().cells
            row[0].text = item.get("item", "")
            row[1].text = str(item.get("points", ""))
            row[2].text = item.get("criteria", "")

        doc.add_paragraph()


def run(state: ExamState) -> dict:
    logger.section("STEP 9 — Exam Compilation")
    passed        = state["passed_questions"]
    model_answers = state["model_answers"]
    requirements  = state["requirements"]

    concept_count = sum(1 for q in passed if q["type"] == "concept")
    case_count    = sum(1 for q in passed if q["type"] == "case")
    logger.log("Compiler", f"개념 {concept_count}문항 + 사례 {case_count}문항 → DOCX 생성 중...")

    exam_doc = Document()
    _build_exam(exam_doc, passed, requirements)
    exam_path = "exam_output.docx"
    exam_doc.save(exam_path)
    logger.log("Compiler", f"✅ 시험지 저장: {exam_path}")

    answer_doc = Document()
    _build_answer_key(answer_doc, model_answers, passed)
    answer_path = "answer_key.docx"
    answer_doc.save(answer_path)
    logger.log("Compiler", f"✅ 모범답안 저장: {answer_path}")

    return {"output_path": exam_path}
