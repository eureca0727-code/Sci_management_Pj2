"""
PDF 추출 결과 확인용 스크립트
실행: python test_pdf.py
"""

import os
import sys
from tools.rag import _extract_text, _split_into_chunks
import config
import fitz


def test_pdf(pdf_path: str):
    doc = fitz.open(pdf_path)
    filename = os.path.basename(pdf_path)
    total_chunks = 0

    print(f"\n{'='*60}")
    print(f"파일: {filename}  ({len(doc)}페이지)")
    print(f"{'='*60}")

    for page_num, page in enumerate(doc, start=1):
        text = _extract_text(page)
        if not text:
            print(f"\n[페이지 {page_num}] 🖼️  이미지 슬라이드 → Vision 추출 중...")
            from tools.rag import _describe_image_page
            text = _describe_image_page(page, page_num)
            if not text:
                print(f"  ⚠️  Vision 추출 실패, 건너뜀")
                continue
            print(f"  Vision 결과: {text[:150].replace(chr(10), ' ')}{'...' if len(text) > 150 else ''}")
            chunks = _split_into_chunks(text, config.CHUNK_SIZE)
            total_chunks += len(chunks)
            continue

        chunks = _split_into_chunks(text, config.CHUNK_SIZE)
        total_chunks += len(chunks)

        print(f"\n[페이지 {page_num}]  →  {len(chunks)}청크  ({len(text)}자)")
        for i, chunk in enumerate(chunks):
            preview = chunk[:120].replace("\n", " ")
            print(f"  청크{i}: {preview}{'...' if len(chunk) > 120 else ''}")

    doc.close()
    print(f"\n총 {total_chunks}개 청크 생성")
    return total_chunks


def main():
    folder = "lecture"
    if not os.path.isdir(folder):
        print(f"'{folder}/' 폴더가 없습니다.")
        sys.exit(1)

    pdfs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf"))
    if not pdfs:
        print(f"'{folder}/' 폴더에 PDF가 없습니다.")
        sys.exit(1)

    print(f"'{folder}/'에서 {len(pdfs)}개 PDF 발견")

    grand_total = 0
    for pdf_file in pdfs:
        grand_total += test_pdf(os.path.join(folder, pdf_file))

    print(f"\n{'='*60}")
    print(f"전체 합계: {grand_total}개 청크")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
