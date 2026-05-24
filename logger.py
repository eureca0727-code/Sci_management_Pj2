import time
import re
import os
from datetime import datetime
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

# 로그 파일 초기화
os.makedirs("logs", exist_ok=True)
_log_path = os.path.join("logs", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
_log_file = open(_log_path, "w", encoding="utf-8")

def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)

def _fwrite(text: str):
    _log_file.write(_strip_ansi(text) + "\n")
    _log_file.flush()

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
    _fwrite(f"\n  예상 비용: ${cost:.4f}  ({total_in+total_out:,} tokens)")
    _fwrite(f"  소요 시간: {time.time()-_start:.1f}s")
    _fwrite(f"{'═'*60}\n")
    _log_file.close()


def log(agent: str, msg: str):
    elapsed = time.time() - _start
    color = COLORS.get(agent, "")
    line = f"{color}{BOLD}[{agent:10s}]{RESET} {elapsed:5.1f}s │ {msg}"
    print(line)
    _fwrite(f"[{agent:10s}] {elapsed:5.1f}s │ {msg}")


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {BOLD}{title}{RESET}")
    print(f"{'─'*60}")
    _fwrite(f"\n{'─'*60}\n  {title}\n{'─'*60}")


def show_question(q: dict):
    _TAG = {"short_answer": "📘 단답형", "essay": "📝 서술형", "application": "📊 사례적용형"}
    tag = _TAG.get(q.get("type", ""), "📄 기타")
    score = q.get("score", "?")
    slides = q.get("source_slides", [])
    lines = [
        f"         {tag}  [{q.get('id','?')}]  {q.get('topic','?')}  ({score}점)",
        f"         문제: {q.get('content','')[:80]}{'...' if len(q.get('content',''))>80 else ''}",
        f"         근거 슬라이드: {slides}",
    ]
    for l in lines:
        print(l)
        _fwrite(l)


def show_judge(r: dict):
    icon = "✅ PASS" if r["passed"] else "❌ FAIL"
    lines = [
        f"         {icon}  [{r['question_id']}]",
        f"         lecture_dep={r['lecture_dependency']:.2f}  "
        f"citation_J={r['citation_jaccard']:.2f}  "
        f"ambiguity={r['ambiguity_score']:.2f}  "
        f"answer_match={r['answer_match']:.2f}",
    ]
    if r.get("failure_reason"):
        lines.append(f"         실패 이유: {r['failure_reason']}")
    for l in lines:
        print(l)
        _fwrite(l)


def show_student(q_id: str, run: int, answer: str, citations: list, mode: str):
    preview = answer[:100].replace("\n", " ")
    lines = [f"         [{q_id}] {mode} run{run}: {preview}..."]
    if citations:
        lines.append(f"         인용: {citations}")
    for l in lines:
        print(l)
        _fwrite(l)
