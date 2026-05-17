# 시험 문제 자동 생성 시스템 — 구조 설명서

> 팀원 온보딩용 문서. 시스템 전체 흐름, 입출력, 에이전트 역할을 설명합니다.

---

## 1. 개요

강의 PDF를 입력받아 **개념 문제**와 **사례 문제**를 자동 생성하고, 품질 검증을 거쳐 시험지(`.docx`)와 모범답안(`.docx`)을 출력하는 멀티 에이전트 시스템입니다.

- **LLM**: Claude Sonnet (Anthropic API)
- **벡터 DB**: ChromaDB (로컬)
- **오케스트레이션**: LangGraph
- **웹 검색**: DuckDuckGo (사례 문제용)

---

## 2. 입력값

### 인터랙티브 모드 (권장)
```bash
python main.py
```
실행하면 아래 항목을 순서대로 물어봅니다.

| 항목 | 설명 |
|------|------|
| 강의 파일 | `lecture/` 폴더 안의 PDF 자동 감지 |
| 총 배점 | 시험 전체 점수 |
| 단원별 문제 수 | 단원명 + 개념 문제 수 + 사례 문제 수 직접 지정 |
| 총 문제 수 | 단원 미지정 시 AI가 자동 배분 |
| 추가 요구사항 | 자유 텍스트 (예: "서술형만 출제", "난이도 높게") |

### CLI 모드
```bash
python main.py --pdf lecture --total 100 --topic 3장:2:1 --topic 5장:1:2
```

---

## 3. 전체 흐름

```
[입력]
PDF 파일(들) + 출제 요구사항
        │
        ▼
┌───────────────┐
│  STEP 1       │  Indexer
│  PDF 인덱싱   │  PDF → 페이지별 텍스트 → ChromaDB 저장
└───────┬───────┘  API 호출: 없음
        │
        ▼
┌───────────────┐
│  STEP 2       │  Chair
│  블루프린트   │  강의자료 분석 → 단원별 배점·문제수·난이도 결정
└───────┬───────┘  API 호출: 1회
        │
   ┌────┴────┐
   ▼         ▼  (병렬 실행)
┌──────┐  ┌──────┐
│STEP 3│  │STEP 3│  Professor A / B
│Prof A│  │Prof B│  A: 개념 문제 초안
│개념  │  │사례  │  B: 사례 문제 초안 (웹 검색 포함)
└──┬───┘  └───┬──┘  API 호출: 단원당 1회 / 2~3회
   └────┬─────┘
        ▼
┌───────────────┐
│  STEP 4       │  Chair
│  합의·확정    │  A·B 초안 검토 → 최종 문제 목록 확정
└───────┬───────┘  API 호출: 1회
        │
        ▼
┌───────────────┐
│  STEP 5       │  Student  ← 가장 비싼 단계
│  학생 시뮬    │  각 문제를 강의자료 기반 3회 + 일반 지식 1회 풀기
└───────┬───────┘  API 호출: 문제당 4회
        │
        ▼
┌───────────────┐
│  STEP 6       │  Judge
│  품질 판정    │  4가지 지표로 통과/실패 판정
└───────┬───────┘  API 호출: 문제당 1회
        │
   ┌────┴──────────────┐
   ▼ PASS              ▼ FAIL (최대 2회 재출제)
   │            Professor A/B로 루프백
   ▼
┌───────────────┐
│  STEP 7       │  Answer Generator
│  모범답안     │  모범답안 + 채점 루브릭 생성
└───────┬───────┘  API 호출: 문제당 1회
        │
        ▼
┌───────────────┐
│  STEP 8       │  Compiler
│  문서 생성    │  DOCX 파일 출력
└───────────────┘  API 호출: 없음

[출력]
exam_output.docx  /  answer_key.docx
```

---

## 4. 에이전트별 상세 설명

### Indexer `agents/indexer.py`
- PyMuPDF로 PDF 페이지별 텍스트 추출
- ChromaDB에 저장 (ID: `{파일명}_p{페이지번호}`)
- 텍스트 없는 페이지(이미지 슬라이드)는 자동 건너뜀
- 여러 PDF를 넣으면 하나의 collection에 합쳐짐
- 같은 파일을 재실행해도 upsert라 중복 없음

### Chair `agents/chair.py`
두 번 실행됩니다.

**① Blueprint 생성 (STEP 2)**
- "목차 단원 주요 개념" 쿼리로 슬라이드 10개 RAG 검색
- user_topics 지정 시: 단원명·문제수 고정, 슬라이드 범위·난이도만 AI 추론
- 출력 형식:
```json
{
  "topics": [{"name": "3장", "slides": [10, 25], "weight": 0.4,
              "concept_questions": 2, "case_questions": 1, "difficulty": "medium"}],
  "total_concept": 6,
  "total_case": 4,
  "rationale": "배분 근거"
}
```

**② Consensus 확정 (STEP 4)**
- A·B 초안 + 블루프린트 + 이전 실패 패턴을 종합해 최종 문제 결정
- 범위 이탈 문제 제거, 중복 개념 제거, 비율 준수 검토

### Professor A `agents/professor.py`
- **개념 문제** 담당 (강의 내용 충실 재현)
- 각 단원별로 RAG 검색 → 해당 슬라이드 근거로 문제 생성
- 답이 강의자료에서 직접 확인 가능한 문제만 출제

### Professor B `agents/professor.py`
- **사례 문제** 담당 (방법론 실제 적용)
- 단계: ① 방법론 키워드 추출 → ② 웹 검색으로 실제 사례 수집 → ③ 문제 생성
- 문제 본문에 실제 사례 출처 URL 포함

### Student `agents/student.py`
- 문제 품질 측정을 위한 시뮬레이션 (실제 학생 행동이 아님)
- **Grounded 모드**: 강의자료만 보고 3회 반복 풀기 → 모호성 측정
- **Unrestricted 모드**: 강의자료 없이 1회 풀기 → 강의 의존도 측정
- 답변마다 `[슬라이드 N]` 출처 표기 강제

### Judge `agents/judge.py`
4가지 지표를 측정해 통과/실패 판정:

| 지표 | 의미 | 통과 기준 |
|------|------|----------|
| `answer_match` | 의도 답 vs 학생 답 유사도 | 개념 ≥ 0.75 / 사례 ≥ 0.55 |
| `ambiguity_score` | N회 풀이 간 불일치율 | ≤ 0.4 |
| `lecture_dependency` | grounded 정답률 - unrestricted 정답률 | 측정만 (판정 미사용) |
| `citation_jaccard` | 의도 슬라이드 vs 인용 슬라이드 일치율 | 측정만 (판정 미사용) |

실패 문제는 `failure_patterns`에 이유가 기록되어 재출제 시 Professor에게 전달됩니다.

### Answer Generator `agents/answer_gen.py`
- grounded 풀이 중 가장 우수한 답변(인용 많은 것)을 참고
- 출력: 모범답안 본문 + 핵심 키워드 목록 + 항목별 채점 루브릭

### Compiler `agents/compiler.py`
- API 호출 없이 python-docx로 DOCX 파일 생성
- `exam_output.docx`: 개념(Part I) + 사례(Part II) 구성
- `answer_key.docx`: 문제별 모범답안 + 루브릭 표

---

## 5. 상태(State) 흐름

```
ExamState 딕셔너리가 전체 파이프라인을 흐름

pdf_path              Indexer가 읽음
requirements          전 단계에서 참조 (배점, 비율, user_topics, 추가요구사항)
blueprint             Chair가 생성 → Professor, Consensus가 참조
_draft_a / _draft_b   Professor가 채움 → Consensus가 소비 후 초기화
questions             Consensus가 확정 → 이후 모든 단계가 참조
grounded_solutions    Student가 채움 → Judge, AnswerGen이 참조
unrestricted_solutions Student가 채움 → Judge가 참조
judge_results         Judge가 채움 (로깅용)
passed_questions      Judge가 분류 → AnswerGen이 처리
failed_questions      Judge가 분류 → 루프 제어에서 사용
failure_patterns      Judge가 누적 → 재출제 시 Professor에 전달
retry_count           Judge 후 +1, MAX_RETRIES 초과 시 루프 탈출
model_answers         AnswerGen이 채움 → Compiler가 소비
output_path           Compiler가 기록
```

---

## 6. API 호출 비용 (10문제 기준)

| 단계 | 호출 수 | 비고 |
|------|--------|------|
| Indexer | 0 | 로컬 처리 |
| Blueprint | 1 | |
| Professor A | ~4 | 단원 수 |
| Professor B | ~8 | 단원당 2~3회 |
| Consensus | 1 | |
| **Student** | **40** | 문제당 4회 — 가장 비쌈 |
| Judge | 10 | |
| Answer Gen | ~10 | |
| Compiler | 0 | 로컬 처리 |
| **합계** | **~74회** | 재출제 없을 때 |

예상 비용: **약 $1~2** (재출제 발생 시 최대 $3)

비용 절감 옵션 (`config.py`):
```python
STUDENT_RUNS = 3   # 1로 줄이면 Student 비용 2/3 절감
MAX_RETRIES  = 2   # 0~1로 줄이면 재출제 없음
```

---

## 7. 프로젝트 구조

```
Sci_management_Pj2/
├── main.py              진입점 (인터랙티브/CLI 모드)
├── interactive.py       인터랙티브 설정 마법사
├── config.py            전역 설정 (모델, 임계값, ChromaDB 경로)
├── state.py             ExamState TypedDict 정의
├── graph.py             LangGraph 파이프라인 조립
├── logger.py            컬러 로그 + 토큰 사용량 추적
├── agents/
│   ├── indexer.py       PDF → ChromaDB
│   ├── chair.py         블루프린트 생성 + 합의 확정
│   ├── professor.py     개념/사례 문제 초안 생성
│   ├── student.py       문제 품질 측정용 시뮬레이션
│   ├── judge.py         통과/실패 판정
│   ├── answer_gen.py    모범답안 + 루브릭 생성
│   └── compiler.py      DOCX 파일 출력
├── prompts/
│   └── templates.py     모든 에이전트의 시스템/유저 프롬프트
├── tools/
│   ├── rag.py           ChromaDB 인덱싱 + 검색
│   └── web_search.py    DuckDuckGo 사례 검색
├── lecture/             강의 PDF 폴더 (직접 생성)
└── requirements.txt     의존 패키지
```

---

## 8. 실행 방법

```bash
# 1. 패키지 설치 (최초 1회)
pip install -r requirements.txt

# 2. lecture/ 폴더에 PDF 넣기

# 3. 실행
python main.py
```

환경변수 `ANTHROPIC_API_KEY`가 설정되어 있어야 합니다.
