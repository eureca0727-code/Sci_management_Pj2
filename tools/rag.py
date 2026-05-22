import os
import base64
import fitz  # PyMuPDF
import chromadb
import anthropic
from chromadb.utils import embedding_functions
from typing import List, Tuple
import config
import logger

_llm = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


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


def _describe_image_page(page, page_num: int) -> str:
    """이미지 슬라이드를 Claude Vision으로 설명 텍스트 추출."""
    pixmap = page.get_pixmap(dpi=150)
    img_b64 = base64.standard_b64encode(pixmap.tobytes("png")).decode()

    response = _llm.messages.create(
        model=config.MODEL,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                },
                {
                    "type": "text",
                    "text": (
                        "이 강의 슬라이드의 내용을 설명하세요. "
                        "다이어그램, 도표, 핵심 개념, 텍스트를 모두 포함해 "
                        "강의 내용을 이해할 수 있도록 서술하세요."
                    ),
                },
            ],
        }],
    )
    logger.record_tokens("Indexer", response.usage)
    return response.content[0].text.strip()


def index_pdf(pdf_path: str) -> int:
    """PDF를 CHUNK_SIZE 단위로 청킹해 ChromaDB에 저장. 저장된 청크 수 반환."""
    doc = fitz.open(pdf_path)
    collection = _get_collection()
    filename = os.path.splitext(os.path.basename(pdf_path))[0]

    ids, documents, metadatas = [], [], []
    for page_num, page in enumerate(doc, start=1):
        text = _extract_text(page)

        if not text:
            # 이미지 슬라이드 → Vision으로 설명 추출
            text = _describe_image_page(page, page_num)
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


def is_indexed(pdf_path: str) -> bool:
    """PDF가 이미 ChromaDB에 인덱싱되어 있는지 확인."""
    collection = _get_collection()
    results = collection.get(
        where={"source": pdf_path},
        limit=1,
        include=[],
    )
    return len(results["ids"]) > 0


def get_all_sources() -> List[str]:
    """ChromaDB에 인덱싱된 모든 PDF 경로 목록 반환."""
    collection = _get_collection()
    results = collection.get(include=["metadatas"])
    seen, sources = set(), []
    for meta in results["metadatas"]:
        src = meta.get("source", "")
        if src and src not in seen:
            seen.add(src)
            sources.append(src)
    return sorted(sources)


def retrieve_per_source(query: str, chunks_per_source: int = 2) -> List[Tuple[int, str]]:
    """각 PDF 소스마다 chunks_per_source개씩 검색해 전 강의 범위를 균등하게 커버."""
    collection = _get_collection()
    sources = get_all_sources()
    results = []
    for src in sources:
        res = collection.query(
            query_texts=[query],
            n_results=chunks_per_source,
            where={"source": src},
            include=["documents", "metadatas"],
        )
        for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
            results.append((meta["slide"], doc))
    return results


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
    if not slide_numbers:
        return []
    collection = _get_collection()
    results = collection.get(
        where={"slide": {"$in": [int(n) for n in slide_numbers]}},
        include=["documents", "metadatas"],
    )
    return [
        (meta["slide"], doc)
        for doc, meta in zip(results["documents"], results["metadatas"])
    ]
