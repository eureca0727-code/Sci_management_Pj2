import os
from state import ExamState
from tools.rag import index_pdf
import logger


def run(state: ExamState) -> dict:
    logger.section("STEP 1 — Document Indexing")

    path = state["pdf_path"]
    if os.path.isdir(path):
        pdf_files = sorted(
            os.path.join(path, f)
            for f in os.listdir(path)
            if f.lower().endswith(".pdf")
        )
        if not pdf_files:
            raise FileNotFoundError(f"폴더에 PDF 파일이 없음: {path}")
    else:
        pdf_files = [path]

    total = 0
    for pdf_file in pdf_files:
        logger.log("Indexer", f"PDF 로딩: {pdf_file}")
        count = index_pdf(pdf_file)
        logger.log("Indexer", f"  └ {count}개 슬라이드 인덱싱 완료")
        total += count

    logger.log("Indexer", f"✅ 총 {total}개 슬라이드 → ChromaDB 저장 완료")
    return {}
