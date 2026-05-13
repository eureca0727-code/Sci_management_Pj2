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


def index_pdf(pdf_path: str) -> int:
    """PDF를 슬라이드 단위로 청킹해 ChromaDB에 저장. 저장된 청크 수 반환."""
    doc = fitz.open(pdf_path)
    collection = _get_collection()

    ids, documents, metadatas = [], [], []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if not text:
            continue
        ids.append(f"slide_{page_num}")
        documents.append(text)
        metadatas.append({"slide": page_num, "source": pdf_path})

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    doc.close()
    return len(ids)


def retrieve(query: str, top_k: int = config.TOP_K) -> List[Tuple[int, str]]:
    """query와 유사한 슬라이드를 반환. [(슬라이드번호, 텍스트), ...]"""
    collection = _get_collection()
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        include=["documents", "metadatas"],
    )
    slides = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        slides.append((meta["slide"], doc))
    return slides


def format_context(slides: List[Tuple[int, str]]) -> str:
    """retrieve 결과를 프롬프트에 주입할 문자열로 변환."""
    return "\n\n".join(f"[슬라이드 {n}]\n{text}" for n, text in slides)


def get_slides_by_numbers(slide_numbers: List[int]) -> List[Tuple[int, str]]:
    """슬라이드 번호 목록으로 직접 조회."""
    collection = _get_collection()
    ids = [f"slide_{n}" for n in slide_numbers]
    results = collection.get(ids=ids, include=["documents", "metadatas"])
    return [
        (meta["slide"], doc)
        for doc, meta in zip(results["documents"], results["metadatas"])
    ]
