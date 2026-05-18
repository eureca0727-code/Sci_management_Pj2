import os
import fitz  # PyMuPDF
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Tuple
import config


_client: chromadb.Client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        ef = embedding_functions.DefaultEmbeddingFunction()
        _collection = _client.get_or_create_collection(
            name=config.COLLECTION_NAME,
            embedding_function=ef,
        )
    return _collection


def _extract_text(page) -> str:
    """페이지에서 위→아래, 좌→우 순서로 텍스트 추출."""
    blocks = page.get_text("blocks")
    # block 형식: (x0, y0, x1, y1, text, block_no, block_type)
    # block_type 0 = 텍스트, 1 = 이미지
    text_blocks = sorted(
        [b for b in blocks if b[6] == 0 and b[4].strip()],
        key=lambda b: (round(b[1] / 20), b[0]),  # y를 20px 단위로 묶어 행 구분 후 x 정렬
    )
    return "\n".join(b[4].strip() for b in text_blocks)


def _split_into_chunks(text: str, chunk_size: int) -> List[str]:
    """텍스트를 chunk_size 토큰 단위로 분할. 1 token ≈ 4자 기준."""
    max_chars = chunk_size * 4
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks, current, current_len = [], [], 0
    for para in paragraphs:
        para_len = len(para)
        if current and current_len + para_len > max_chars:
            chunks.append("\n".join(current))
            current, current_len = [para], para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n".join(current))

    return chunks or [text]


def index_pdf(pdf_path: str) -> int:
    """PDF를 CHUNK_SIZE 단위로 청킹해 ChromaDB에 저장. 저장된 청크 수 반환."""
    doc = fitz.open(pdf_path)
    collection = _get_collection()
    filename = os.path.splitext(os.path.basename(pdf_path))[0]

    ids, documents, metadatas = [], [], []
    for page_num, page in enumerate(doc, start=1):
        text = _extract_text(page)
        if not text:
            continue

        chunks = _split_into_chunks(text, config.CHUNK_SIZE)
        for i, chunk in enumerate(chunks):
            ids.append(f"{filename}_p{page_num}_c{i}")
            documents.append(chunk)
            metadatas.append({"slide": page_num, "chunk": i, "source": pdf_path})

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    doc.close()
    return len(ids)


def retrieve(query: str, top_k: int = config.TOP_K) -> List[Tuple[int, str]]:
    """query와 유사한 청크를 반환. [(슬라이드번호, 텍스트), ...]"""
    collection = _get_collection()
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        include=["documents", "metadatas"],
    )
    return [
        (meta["slide"], doc)
        for doc, meta in zip(results["documents"][0], results["metadatas"][0])
    ]


def format_context(slides: List[Tuple[int, str]]) -> str:
    """retrieve 결과를 프롬프트에 주입할 문자열로 변환."""
    return "\n\n".join(f"[슬라이드 {n}]\n{text}" for n, text in slides)


def get_slides_by_numbers(slide_numbers: List[int]) -> List[Tuple[int, str]]:
    """슬라이드 번호 목록으로 직접 조회."""
    collection = _get_collection()
    results = collection.get(
        where={"slide": {"$in": slide_numbers}},
        include=["documents", "metadatas"],
    )
    return [
        (meta["slide"], doc)
        for doc, meta in zip(results["documents"], results["metadatas"])
    ]
