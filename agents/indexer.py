import os
from state import ExamState
from tools.rag import index_pdf, is_indexed
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
    skipped = 0
    for pdf_file in pdf_files:
        abs_path = os.path.abspath(pdf_file)
        if is_indexed(abs_path):
            logger.log("Indexer", f"이미 인덱싱됨, 건너뜀: {pdf_file}")
            skipped += 1
            continue
        logger.log("Indexer", f"PDF 로딩: {pdf_file}")
        count = index_pdf(abs_path)
        logger.log("Indexer", f"  └ {count}개 청크 인덱싱 완료")
        total += count

    if skipped:
        logger.log("Indexer", f"✅ {skipped}개 파일 캐시 사용 / {total}개 청크 신규 저장")
    else:
        logger.log("Indexer", f"✅ 총 {total}개 청크 → ChromaDB 저장 완료")
    return {}
