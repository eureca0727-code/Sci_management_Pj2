import os
from dotenv import load_dotenv

load_dotenv(override=True)  # .env 파일이 시스템 환경변수보다 우선

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# 키 검증은 main.py에서 import 전에 처리 — 여기서 raise 하지 않음

MODEL       = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"   # 단순 작업 전용

# RAG
CHUNK_SIZE = 400          # tokens per slide chunk
TOP_K = 5                 # retrieved chunks per query
CHROMA_PERSIST_DIR = "./chroma_db"
COLLECTION_NAME = "lecture_slides"

# Judge thresholds
SHORT_ANSWER_MATCH_MIN = 0.80
ESSAY_MATCH_MIN        = 0.65
APPLICATION_MATCH_MIN  = 0.55
AMBIGUITY_MAX = 0.4       # N-run 답 불일치율 상한
LECTURE_DEPENDENCY_MIN = 0.3  # grounded - unrestricted 정답률 차이 하한

# Student simulation
STUDENT_RUNS = 1          # 모호성 측정을 위한 반복 풀이 횟수
MAX_RETRIES = 3           # 전체 재출제 라운드 최대 횟수
MAX_FILL = 3              # fill 보충 최대 시도 횟수
TOP_K_MAX = 15            # 재출제 반복 시 TOP_K 상한
