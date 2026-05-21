import re
import json
import hashlib
import os
from json_repair import repair_json

_CACHE_DIR = ".cache/llm"


def parse_json(text: str):
    """마크다운 코드블록, 깨진 JSON 모두 처리."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = repair_json(text)
        return json.loads(repaired)


class _Block:
    def __init__(self, text): self.text = text

class _Usage:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

class _CachedResponse:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


def cached_create(client, **kwargs):
    """client.messages.create() + 디스크 캐시. 동일 입력이면 API 재호출 없음."""
    try:
        raw = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)
        key = hashlib.sha256(raw.encode()).hexdigest()[:20]
        path = os.path.join(_CACHE_DIR, f"{key}.json")
    except Exception:
        return client.messages.create(**kwargs)

    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return _CachedResponse(json.load(f)["text"])
        except Exception:
            pass  # 캐시 파일 손상 시 재호출

    os.makedirs(_CACHE_DIR, exist_ok=True)
    response = client.messages.create(**kwargs)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"text": response.content[0].text}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 저장 실패해도 응답은 반환
    return response
