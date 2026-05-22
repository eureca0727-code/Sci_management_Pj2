import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일 자동 로딩

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    raise ValueError(".env 파일에 ANTHROPIC_API_KEY가 없음")

MODEL       = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"   # 단순 작업 전용

# RAG
CHUNK_SIZE = 400          # tokens per slide chunk
TOP_K = 5                 # retrieved chunks per query
CHROMA_PERSIST_DIR = "./chroma_db"
COLLECTION_NAME = "lecture_slides"

# Judge thresholds
CONCEPT_ANSWER_MATCH_MIN = 0.75
CASE_ANSWER_MATCH_MIN = 0.55
AMBIGUITY_MAX = 0.4       # N-run 답 불일치율 상한
LECTURE_DEPENDENCY_MIN = 0.3  # grounded - unrestricted 정답률 차이 하한

# Student simulation
STUDENT_RUNS = 1          # 모호성 측정을 위한 반복 풀이 횟수
MAX_RETRIES = 2           # Judge 실패 시 재출제 최대 횟수
