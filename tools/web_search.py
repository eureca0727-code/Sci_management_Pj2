from duckduckgo_search import DDGS
from typing import List


def search_cases(methodology: str, topic: str, max_results: int = 3) -> List[dict]:
    """방법론으로 실제 사례 검색 (영어 쿼리만 사용). [{title, url, body}, ...]"""
    query = f'"{methodology}" case study real world example application'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception:
        return []


def _sanitize(text: str) -> str:
    """JSON 문자열 안에서 문제가 될 수 있는 문자 제거."""
    return (
        text.replace('"', "'")
            .replace("\\", " ")
            .replace("\r", " ")
            .replace("\n", " ")
            .strip()
    )


def format_cases(results: List[dict]) -> str:
    """검색 결과를 프롬프트에 주입할 텍스트로 변환."""
    if not results:
        return "검색 결과 없음"
    parts = []
    for i, r in enumerate(results, 1):
        title = _sanitize(r.get("title", ""))
        url   = r.get("href", r.get("url", ""))
        body  = _sanitize(r.get("body", ""))[:400]
        parts.append(f"[사례 {i}] {title}\n출처: {url}\n{body}")
    return "\n\n".join(parts)
