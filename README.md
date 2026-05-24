# 시험 문제 자동 생성 시스템

강의 슬라이드 PDF를 입력하면 AI 에이전트들이 협력해 시험 문제·모범답안·루브릭을 자동 생성합니다.

---

## 에이전트 파이프라인

```mermaid
flowchart TD
    START([▶ 실행 시작]) --> index

    subgraph PREP ["📁 준비"]
        index["🔍 슬라이드 색인\n(Indexer)"]
        blueprint["📋 블루프린트 생성\n(Chair)"]
        review["👤 블루프린트 검토\n사용자 자연어 수정"]
    end

    subgraph DRAFT ["✏️ 출제"]
        profA["🧑‍🏫 교수 A\n개념 문제 출제"]
        profB["🧑‍🏫 교수 B\n사례 문제 출제"]
        consensus["🪑 합의\n(Chair)"]
        fill{"📊 문제 수\n충분?"}
    end

    subgraph EVAL ["🔬 검증"]
        student["🎓 학생 풀이\n(Student)"]
        judge["⚖️ 품질 판정\n(Judge)"]
        retry["🔄 재출제 준비"]
    end

    subgraph FINAL ["📄 마무리"]
        score["🔢 점수 정규화"]
        ansgen["📝 모범답안 생성\n(AnswerGen)"]
        human["👤 최종 검토\n사람이 수정·삭제"]
        scenario["🎬 공통 시나리오 생성\n(대문제 그룹용)"]
        validate{"✅ 최종 검증"}
        compiler["📦 시험지 출력\n(Compiler)"]
    end

    END([🏁 완료\nexams/ 폴더])

    index --> blueprint --> review --> profA
    profA --> profB --> consensus --> fill

    fill -->|"부족 (최대 3회)"| profA
    fill -->|충분| student

    student --> judge

    judge -->|"실패 → 재출제 (최대 10회)"| retry --> profA
    judge -->|"PASS지만 문제 수 부족"| fill
    judge -->|통과| score

    score --> ansgen --> human --> scenario --> validate

    validate -->|"✅ OK"| compiler --> END
    validate -->|"문제 수 부족"| fill
    validate -->|"점수 불일치"| score

    %% 색상
    style START fill:#4CAF50,color:#fff
    style END   fill:#4CAF50,color:#fff

    style index    fill:#2196F3,color:#fff
    style blueprint fill:#2196F3,color:#fff
    style profA    fill:#2196F3,color:#fff
    style profB    fill:#2196F3,color:#fff
    style consensus fill:#2196F3,color:#fff
    style student  fill:#2196F3,color:#fff
    style judge    fill:#2196F3,color:#fff
    style retry    fill:#FF9800,color:#fff
    style score    fill:#2196F3,color:#fff
    style ansgen   fill:#2196F3,color:#fff
    style scenario fill:#2196F3,color:#fff
    style compiler fill:#2196F3,color:#fff

    style review  fill:#9C27B0,color:#fff
    style human   fill:#9C27B0,color:#fff

    style fill     fill:#FFC107,color:#000
    style validate fill:#FFC107,color:#000
```

**색상 범례**
- 🔵 파란색 — AI 에이전트 자동 처리
- 🟣 보라색 — 사람이 직접 개입하는 단계
- 🟡 노란색 — 조건 분기 (결과에 따라 흐름이 달라짐)
- 🟢 초록색 — 시작 / 완료

---

## 실행 방법

```bash
# 인터랙티브 모드 (권장)
python main.py

# CLI 모드
python main.py --pdf lecture --total 100 --questions 8
```

lecture/ 폴더에 PDF를 넣고 실행하면 됩니다.

---

## 출력

`exams/` 폴더에 두 파일이 생성됩니다.

| 파일 | 내용 |
|------|------|
| `exam_MMDD_HHMM.docx` | 시험지 (문제 + 배점) |
| `answer_key_MMDD_HHMM.docx` | 모범답안 + 루브릭 |

---

## Mermaid 다이어그램 수정하는 법

위 파이프라인 그림은 **Mermaid** 문법으로 작성되어 있습니다.
GitHub에서 자동으로 렌더링되며, 텍스트로 관리합니다.

### 기본 문법

````markdown
```mermaid
flowchart TD
    A[노드 이름] --> B[다음 노드]
    B --> C{조건 분기?}
    C -->|예| D[결과1]
    C -->|아니오| E[결과2]
```
````

### 노드 모양

```
[텍스트]      → 사각형
(텍스트)      → 둥근 사각형
{텍스트}      → 마름모 (조건)
([텍스트])    → 경기장 모양 (시작/끝)
```

### 방향

```
TD  위→아래   LR  왼쪽→오른쪽
BT  아래→위   RL  오른쪽→왼쪽
```

### 색상

```
style 노드이름 fill:#색상코드,color:#글자색
```

### 브라우저에서 바로 테스트

https://mermaid.live 에 코드를 붙여넣으면 실시간으로 확인할 수 있습니다.
