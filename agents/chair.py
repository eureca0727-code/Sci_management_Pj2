import json
import anthropic
from state import ExamState, Question
from prompts.templates import CHAIR_BLUEPRINT, CHAIR_CONSENSUS
from tools.rag import retrieve, format_context
import config
import logger

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def run_blueprint(state: ExamState) -> dict:
    logger.section("STEP 2 — Blueprint Generation (Chair)")
    logger.log("Chair", "강의자료 분석 중...")

    req = state["requirements"]
    slides = retrieve("목차 단원 주요 개념", top_k=10)
    context = format_context(slides)

    logger.log("Chair", f"관련 슬라이드 {len(slides)}개 검색 완료 → LLM 블루프린트 생성 중...")

    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=1500,
        system=CHAIR_BLUEPRINT,
        messages=[{
            "role": "user",
            "content": (
                f"강의자료 발췌:\n{context}\n\n"
                f"출제 요구사항:\n{json.dumps(req, ensure_ascii=False)}"
            ),
        }],
    )

    logger.record_tokens("Chair", response.usage)
    blueprint = json.loads(response.content[0].text)

    logger.log("Chair", f"✅ 블루프린트 확정: {len(blueprint['topics'])}개 단원")
    for t in blueprint["topics"]:
        print(f"         단원: {t['name']}  "
              f"배점비율={t['weight']:.0%}  "
              f"개념{t['concept_questions']}문항 / 사례{t['case_questions']}문항  "
              f"난이도={t['difficulty']}")

    return {"blueprint": blueprint}


def run_consensus(state: ExamState) -> dict:
    logger.section("STEP 5 — Chair Consensus (교수 회의 합의)")
    prof_a = state.get("_draft_a", [])
    prof_b = state.get("_draft_b", [])
    failure_patterns = state.get("failure_patterns", [])

    logger.log("Chair", f"A 초안 {len(prof_a)}개 + B 초안 {len(prof_b)}개 검토 중...")
    if failure_patterns:
        logger.log("Chair", f"⚠️  회피 패턴 {len(failure_patterns)}개 적용 중")

    response = _client.messages.create(
        model=config.MODEL,
        max_tokens=3000,
        system=CHAIR_CONSENSUS,
        messages=[{
            "role": "user",
            "content": (
                f"블루프린트:\n{json.dumps(state['blueprint'], ensure_ascii=False)}\n\n"
                f"Professor A 초안:\n{json.dumps(prof_a, ensure_ascii=False)}\n\n"
                f"Professor B 초안:\n{json.dumps(prof_b, ensure_ascii=False)}\n\n"
                f"회피 실패 패턴:\n{failure_patterns}"
            ),
        }],
    )

    logger.record_tokens("Chair", response.usage)
    raw = json.loads(response.content[0].text)
    questions: list[Question] = []
    for i, q in enumerate(raw):
        q["id"] = f"Q{i+1:02d}"
        q.setdefault("methodology", None)
        questions.append(q)

    logger.log("Chair", f"✅ 합의 완료: {len(questions)}개 문제 확정")
    for q in questions:
        logger.show_question(q)

    return {"questions": questions, "_draft_a": [], "_draft_b": []}
