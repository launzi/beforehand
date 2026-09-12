"""
Agent loop that turns browsing signals into actions.

Signals arrive pre-computed from browsing/signals.py. This module decides which
ones are worth acting on, and produces an action for those.

Pipeline: detect (rules, done elsewhere) -> triage (LLM judges) -> act (skills) -> surface
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from browsing.signals import Signal


# ============================================================
# Public data structures
# ============================================================

@dataclass(frozen=True, slots=True)
class Action:
    """A single action produced from a signal that passed triage."""
    signal_key: str        # which signal produced it
    kind: str              # the signal's kind
    text: str              # human-readable result
    evidence: dict         # what it was based on


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Result of running the agent over a batch of signals."""
    actions: list[Action]
    errors: list[str]
    stats: dict            # {"acted": int, "skipped": int, "errors": int}


# ============================================================
# Type for the LangGraph state
# ============================================================

class AgentState(TypedDict, total=False):
    signals: list[Signal]
    actions: list[Action]
    errors: list[str]
    stats: dict
    max_signals: int
    llm: object
    search: object
    _verdicts: dict[str, bool]
    _processed_count: int


# ============================================================
# Triage — LLM judges whether a signal is worth acting on
# ============================================================

TRIAGE_SYSTEM = (
    "You are a triage judge for a personal browsing intelligence system. "
    "You receive one signal at a time with its evidence. "
    "Decide if this signal is worth acting on RIGHT NOW. "
    "Reply with exactly one word: ACT or SKIP. "
    "ACT means: this is interesting, actionable, or time-sensitive — do something with it. "
    "SKIP means: routine, stale, or not worth a follow-up."
)

TRIAGE_TEMPLATE = """Signal kind: {kind}
Signal key: {key}
Host: {host}
Term: {term}
Evidence:
{evidence}

Worth acting on now? Reply ACT or SKIP."""


def triage_signal(signal: Signal, *, llm) -> bool:
    """
    Ask the LLM whether this signal deserves action.
    Returns True for ACT, False for SKIP (or any other reply).
    """
    evidence_str = _format_evidence(signal.evidence)
    host_str = signal.host if signal.host is not None else "(none)"
    term_str = signal.term if signal.term is not None else "(none)"

    prompt = TRIAGE_TEMPLATE.format(
        kind=signal.kind,
        key=signal.key,
        host=host_str,
        term=term_str,
        evidence=evidence_str,
    )

    # ⚠ 여기서 예외를 잡지 않는다.
    #   LLM 이 죽은 것과 "판단 결과 건너뜀"은 전혀 다른 사건인데, 삼켜서 False 를
    #   돌려주면 둘이 같은 모습이 된다. 배치를 막지 않는 것은 호출부(run_triage)가
    #   신호 하나 단위로 잡아 errors 에 기록하며 이미 책임진다.
    reply = llm.complete(prompt, tier="nano", system=TRIAGE_SYSTEM, max_tokens=10)

    reply_upper = (reply or "").strip().upper()
    return reply_upper.startswith("ACT") or "ACT" in reply_upper


def _format_evidence(evidence: dict) -> str:
    """Format evidence dict for the triage prompt."""
    if not evidence:
        return "(empty)"
    lines = []
    for k, v in evidence.items():
        if isinstance(v, (list, tuple)):
            v_str = ", ".join(str(x) for x in v)
        else:
            v_str = str(v)
        lines.append(f"  {k}: {v_str}")
    return "\n".join(lines)


# ============================================================
# Skills — one per signal kind that we act on
# ============================================================

SKILL_SYSTEM = (
    "You are a concise analyst writing for a personal weekly report. "
    "Produce 2-4 sentences, plain language, no fluff. "
    "Base your answer ONLY on the provided evidence and search hits."
)

# ---- unresolved: search the term, then brief ----

UNRESOLVED_PROMPT = """Term: {term}

Search hits:
{hits}

Write a short briefing (2-4 sentences) explaining what this term refers to and why it might matter."""


def skill_unresolved(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Search for the term and write a briefing from the hits."""
    if signal.term is None:
        return "No term available for unresolved signal."

    # ⚠ 검색 실패를 잡아서 문자열로 돌려주지 않는다.
    #   "Search failed: ..." 를 행동 결과로 반환하면 상위가 성공으로 세고 그 문장이
    #   그대로 리포트에 실린다. 실패는 run_act 가 신호 단위로 잡아 errors 에 넣는다.
    hits = search.search(signal.term, limit=5)

    hits_text = _format_hits(hits)
    prompt = UNRESOLVED_PROMPT.format(term=signal.term, hits=hits_text)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=300)
# ---- new_entry: judge if setup looks finished ----

NEW_ENTRY_PROMPT = """Host: {host}
Evidence:
{evidence}

Does the initial setup for this host look finished? Answer in 2-3 sentences."""


def skill_new_entry(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Ask LLM whether setup looks finished based on evidence."""
    if signal.host is None:
        return "No host available for new_entry signal."

    evidence_str = _format_evidence(signal.evidence)
    prompt = NEW_ENTRY_PROMPT.format(host=signal.host, evidence=evidence_str)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=200)
# ---- recurring: name the through-line ----

RECURRING_PROMPT = """Host: {host}
Evidence:
{evidence}

What is the through-line connecting these visits? Name the persistent theme or purpose in 2-3 sentences."""


def skill_recurring(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Ask LLM to name the through-line across visits."""
    if signal.host is None:
        return "No host available for recurring signal."

    evidence_str = _format_evidence(signal.evidence)
    prompt = RECURRING_PROMPT.format(host=signal.host, evidence=evidence_str)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=200)
# ---- dropped: short "is this still live?" nudge ----

DROPPED_PROMPT = """Host: {host}
Evidence:
{evidence}

This host has gone quiet. Phrase a short nudge (1-2 sentences) asking if it's still live or relevant."""


def skill_dropped(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Ask LLM to phrase a short nudge."""
    if signal.host is None:
        return "No host available for dropped signal."

    evidence_str = _format_evidence(signal.evidence)
    prompt = DROPPED_PROMPT.format(host=signal.host, evidence=evidence_str)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=150)
def _format_hits(hits: list[dict]) -> str:
    """Format search hits for the unresolved prompt."""
    if not hits:
        return "(no hits)"
    lines = []
    for i, h in enumerate(hits, 1):
        title = h.get("title", "")
        url = h.get("url", "")
        snippet = h.get("snippet", "")
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n".join(lines)


# Registry: signal kind -> skill function
SKILLS: dict[str, Callable] = {
    "unresolved": skill_unresolved,
    "new_entry": skill_new_entry,
    "recurring": skill_recurring,
    "dropped": skill_dropped,
}


# ============================================================
# Core logic functions (testable without the graph)
# ============================================================

def run_triage(
    signals: list[Signal],
    *,
    llm,
    max_signals: int,
) -> tuple[dict[str, bool], dict, list[str]]:
    """
    Run triage on signals up to max_signals.
    Returns (verdicts, stats, errors).
    """
    verdicts: dict[str, bool] = {}
    stats = {"acted": 0, "skipped": 0, "errors": 0}
    errors: list[str] = []

    processed = 0
    for signal in signals:
        if processed >= max_signals:
            break
        processed += 1

        try:
            verdict = triage_signal(signal, llm=llm)
            verdicts[signal.key] = verdict
            if verdict:
                stats["acted"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            errors.append(f"triage:{signal.key}: {e}")
            stats["errors"] += 1
            verdicts[signal.key] = False

    return verdicts, stats, errors


def run_act(
    signals: list[Signal],
    verdicts: dict[str, bool],
    *,
    llm,
    search,
    stats: dict,
    errors: list[str],
) -> tuple[list[Action], dict, list[str]]:
    """
    Run skills for signals with ACT verdict.
    Returns (actions, updated_stats, updated_errors).
    """
    actions: list[Action] = []

    for signal in signals:
        verdict = verdicts.get(signal.key, False)
        if not verdict:
            continue

        skill = SKILLS.get(signal.kind)
        if skill is None:
            # No skill registered — count as error (spec says count it, never crash)
            errors.append(f"act:{signal.key}: no skill for kind '{signal.kind}'")
            stats["errors"] += 1
            stats["acted"] -= 1  # undo the acted count from triage
            continue

        try:
            text = skill(signal, llm=llm, search=search, verdict=verdict)
            action = Action(
                signal_key=signal.key,
                kind=signal.kind,
                text=text,
                evidence=signal.evidence,
            )
            actions.append(action)
        except Exception as e:
            errors.append(f"act:{signal.key}: {e}")
            stats["errors"] += 1
            stats["acted"] -= 1  # undo the acted count from triage

    return actions, stats, errors


# ============================================================
# LangGraph nodes
# ============================================================

def triage_node(state: AgentState) -> AgentState:
    """Triage each signal up to max_signals."""
    signals = state["signals"]
    max_signals = state.get("max_signals", 20)
    llm = state["llm"]

    verdicts, stats, errors = run_triage(signals, llm=llm, max_signals=max_signals)

    state["_verdicts"] = verdicts
    state["stats"] = stats
    state["errors"] = errors
    state["_processed_count"] = sum(stats.values())
    return state


def act_node(state: AgentState) -> AgentState:
    """Run the skill for each signal that got ACT verdict."""
    signals = state["signals"]
    verdicts = state.get("_verdicts", {})
    llm = state["llm"]
    search = state["search"]
    stats = state.get("stats", {"acted": 0, "skipped": 0, "errors": 0})
    errors = state.get("errors", [])

    actions, stats, errors = run_act(
        signals, verdicts, llm=llm, search=search, stats=stats, errors=errors
    )

    state["actions"] = actions
    state["stats"] = stats
    state["errors"] = errors
    return state


# ============================================================
# Graph builder
# ============================================================

def build_graph(*, llm, search) -> StateGraph:
    """
    Build and compile the LangGraph for the agent.
    Nodes: triage -> act -> END
    """
    graph = StateGraph(AgentState)

    # ⚠ llm·search 는 클로저로 잡는다. state 에서 꺼내면 build_graph 의 인자가
    #   무의미해지고, 호출자가 상태에 provider 를 끼워 넣어야 한다.
    def _triage(state):
        verdicts, stats, errors = run_triage(
            state["signals"], llm=llm, max_signals=state.get("max_signals", 20))
        return {"_verdicts": verdicts, "stats": stats, "errors": errors}

    def _act(state):
        actions, stats, errors = run_act(
            state["signals"], state.get("_verdicts", {}), llm=llm, search=search,
            stats=state.get("stats", {"acted": 0, "skipped": 0, "errors": 0}),
            errors=state.get("errors", []))
        return {"actions": actions, "stats": stats, "errors": errors}

    graph.add_node("triage", _triage)
    graph.add_node("act", _act)

    graph.set_entry_point("triage")
    graph.add_edge("triage", "act")
    graph.add_edge("act", END)

    # Compile with llm and search baked into the initial state
    compiled = graph.compile()
    # The compiled graph's invoke will merge initial state with call-time state
    # We bind llm/search as defaults in the compiled graph
    compiled.llm = llm
    compiled.search = search
    return compiled


# ============================================================
# Public runner
# ============================================================

def run_agent(
    conn,
    *,
    signals: list[Signal],
    llm,
    search,
    max_signals: int = 20,
) -> AgentResult:
    """
    Run the agent over a batch of signals.

    Args:
        conn: Database connection (accepted for future use; unused currently)
        signals: List of Signal instances to process
        llm: Injected LLM with .complete(prompt, tier, system, max_tokens) -> str
        search: Injected search with .search(query, limit) -> list[dict]
        max_signals: Cost ceiling — process at most this many signals

    Returns:
        AgentResult with actions, errors, and stats.
    """
    graph = build_graph(llm=llm, search=search)

    initial_state: AgentState = {
        "signals": signals,
        "actions": [],
        "errors": [],
        "stats": {"acted": 0, "skipped": 0, "errors": 0},
        "max_signals": max_signals,
        "llm": llm,
        "search": search,
    }

    final_state = graph.invoke(initial_state)

    return AgentResult(
        actions=final_state.get("actions", []),
        errors=final_state.get("errors", []),
        stats=final_state.get("stats", {"acted": 0, "skipped": 0, "errors": 0}),
    )
