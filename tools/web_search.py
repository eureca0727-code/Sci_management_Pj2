from duckduckgo_search import DDGS
from typing import List


def search_cases(methodology: str, topic: str, max_results: int = 3) -> List[dict]:
    """방법론 + 주제로 실제 사례 검색. [{title, url, body}, ...]"""
    query = f'"{methodology}" case study real example {topic}'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception:
        return []


def format_cases(results: List[dict]) -> str:
    """검색 결과를 프롬프트에 주입할 텍스트로 변환."""
    if not results:
        return "검색 결과 없음"
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(
            f"[사례 {i}] {r.get('title', '')}\n"
            f"출처: {r.get('href', r.get('url', ''))}\n"
            f"{r.get('body', '')[:400]}"
        )
    return "\n\n".join(parts)
