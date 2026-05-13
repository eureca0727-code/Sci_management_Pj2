import time
from collections import defaultdict

COLORS = {
    "Indexer":    "\033[94m",   # 파랑
    "Chair":      "\033[95m",   # 보라
    "ProfA":      "\033[93m",   # 노랑
    "ProfB":      "\033[92m",   # 초록
    "Student":    "\033[96m",   # 청록
    "Judge":      "\033[91m",   # 빨강
    "AnswerGen":  "\033[33m",   # 주황
    "Compiler":   "\033[97m",   # 흰색
}
RESET = "\033[0m"
BOLD  = "\033[1m"

_start = time.time()

# Claude Sonnet 4-6 가격 ($/1M tokens)
_PRICE_INPUT  = 3.0
_PRICE_OUTPUT = 15.0

_tokens: dict[str, int] = defaultdict(int)  # {agent: input/output 합산}
_usage_log: list[dict] = []                  # 호출별 상세 기록


def record_tokens(agent: str, usage):
    """anthropic response.usage 객체를 받아 누적."""
    inp = getattr(usage, "input_tokens", 0)
    out = getattr(usage, "output_tokens", 0)
    _tokens[f"{agent}_input"]  += inp
    _tokens[f"{agent}_output"] += out
    _usage_log.append({"agent": agent, "input": inp, "output": out})


def show_token_summary():
    agents = sorted({entry["agent"] for entry in _usage_log})

    total_in  = sum(_tokens[f"{a}_input"]  for a in agents)
    total_out = sum(_tokens[f"{a}_output"] for a in agents)
    cost = (total_in * _PRICE_INPUT + total_out * _PRICE_OUTPUT) / 1_000_000

    print(f"\n{'═'*60}")
    print(f"  {BOLD}TOKEN USAGE SUMMARY{RESET}")
    print(f"{'═'*60}")
    print(f"  {'Agent':<12} {'Input':>8} {'Output':>8} {'Total':>8}")
    print(f"  {'─'*44}")
    for a in agents:
        inp = _tokens[f"{a}_input"]
        out = _tokens[f"{a}_output"]
        print(f"  {a:<12} {inp:>8,} {out:>8,} {inp+out:>8,}")
    print(f"  {'─'*44}")
    print(f"  {'TOTAL':<12} {total_in:>8,} {total_out:>8,} {total_in+total_out:>8,}")
    print(f"\n  예상 비용: ${cost:.4f}  ({total_in+total_out:,} tokens)")
    print(f"  소요 시간: {time.time()-_start:.1f}s")
    print(f"{'═'*60}\n")


def log(agent: str, msg: str):
    elapsed = time.time() - _start
    color = COLORS.get(agent, "")
    print(f"{color}{BOLD}[{agent:10s}]{RESET} {elapsed:5.1f}s │ {msg}")


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {BOLD}{title}{RESET}")
    print(f"{'─'*60}")


def show_question(q: dict):
    tag = "📘 개념" if q["type"] == "concept" else "📊 사례"
    print(f"         {tag}  [{q.get('id','?')}]  {q['topic']}  ({q['score']}점)")
    print(f"         문제: {q['content'][:80]}{'...' if len(q['content'])>80 else ''}")
    print(f"         근거 슬라이드: {q['source_slides']}")


def show_judge(r: dict):
    icon = "✅ PASS" if r["passed"] else "❌ FAIL"
    print(f"         {icon}  [{r['question_id']}]")
    print(f"         lecture_dep={r['lecture_dependency']:.2f}  "
          f"citation_J={r['citation_jaccard']:.2f}  "
          f"ambiguity={r['ambiguity_score']:.2f}  "
          f"answer_match={r['answer_match']:.2f}")
    if r.get("failure_reason"):
        print(f"         실패 이유: {r['failure_reason']}")


def show_student(q_id: str, run: int, answer: str, citations: list, mode: str):
    preview = answer[:100].replace("\n", " ")
    print(f"         [{q_id}] {mode} run{run}: {preview}...")
    if citations:
        print(f"         인용: {citations}")
