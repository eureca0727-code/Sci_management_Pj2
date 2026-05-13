from state import ExamState
from tools.rag import index_pdf
import logger


def run(state: ExamState) -> dict:
    logger.section("STEP 1 — Document Indexing")
    logger.log("Indexer", f"PDF 로딩: {state['pdf_path']}")

    count = index_pdf(state["pdf_path"])

    logger.log("Indexer", f"✅ {count}개 슬라이드 → ChromaDB 저장 완료")
    return {}
