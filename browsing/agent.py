"""
Agent loop that turns browsing signals into actions.

Signals arrive pre-computed from browsing/signals.py. This module decides which
ones are worth acting on, and produces an action for those.

Pipeline: detect -> triage (LLM) -> mandate (rules) -> act (skills) -> surface
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from browsing.signals import Signal
from browsing.mandate import (
    DEFAULT_BASE_PATH, DEFAULT_LOCAL_PATH, MandateDecision, PlannedAction,
    declares_action, evaluate_mandate, load_mandate,
)
from browsing.trace import Tracer, disable_external_tracing


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
class SignalDecision:
    """Policy judgment and execution outcome, including held/denied signals.

    executed means the skill was invoked, not that it succeeded. Signals outside
    max_signals have no triage or policy judgment and do not appear here.
    """
    signal_key: str
    signal_kind: str
    triage: str
    planned_action: PlannedAction | None
    mandate: MandateDecision
    executed: bool = False
    execution_status: str = "not_run"
    execution_error: str | None = None


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Result of running the agent over a batch of signals."""
    actions: list[Action]
    errors: list[str]
    stats: dict            # acted/skipped/errors; held/denied count blocked ACTs
    decisions: list[SignalDecision] = field(default_factory=list)


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
    _verdicts: dict[str, bool | None]
    _decisions: dict[str, SignalDecision]
    decisions: list[SignalDecision]
    _processed_count: int


# ============================================================
# Triage — LLM judges whether a signal is worth acting on
# ============================================================

# Token Factory Nano measurements (2026-10-03): /no_think does not stop reasoning.
# A short probe used 89-137 completion tokens, but the 12 real synthetic-persona
# triage prompts (2 calls each) used 90-1674, and the same prompt varied 394 vs
# 1674. A 400 cap failed 2-3 of 12 signals with finish_reason=length. Nano is
# cheap, so cap generously: triage 2048 (max observed 1674 + margin); skills get
# their 150-300 output budget plus the same 2048 reasoning allowance.
# These are ceilings, not guaranteed usage or success.
TRIAGE_MAX_TOKENS = 2048
SKILL_MAX_TOKENS = {
    "unresolved": 2348,  # 300 output + 2048 reasoning
    "new_entry": 2248,   # 200 output + 2048 reasoning
    "recurring": 2248,   # 200 output + 2048 reasoning
    "dropped": 2198,     # 150 output + 2048 reasoning
}

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
    reply = llm.complete(prompt, tier="nano", system=TRIAGE_SYSTEM, max_tokens=TRIAGE_MAX_TOKENS)

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


@declares_action(PlannedAction(
    "unresolved", "unresolved", "research_briefing", uses_search=True, uses_llm=True,
))
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
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=SKILL_MAX_TOKENS["unresolved"])
# ---- new_entry: judge if setup looks finished ----

NEW_ENTRY_PROMPT = """Host: {host}
Evidence:
{evidence}

Does the initial setup for this host look finished? Answer in 2-3 sentences."""


@declares_action(PlannedAction(
    "new_entry", "new_entry", "setup_check", uses_search=False, uses_llm=True,
))
def skill_new_entry(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Ask LLM whether setup looks finished based on evidence."""
    if signal.host is None:
        return "No host available for new_entry signal."

    evidence_str = _format_evidence(signal.evidence)
    prompt = NEW_ENTRY_PROMPT.format(host=signal.host, evidence=evidence_str)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=SKILL_MAX_TOKENS["new_entry"])
# ---- recurring: name the through-line ----

RECURRING_PROMPT = """Host: {host}
Evidence:
{evidence}

What is the through-line connecting these visits? Name the persistent theme or purpose in 2-3 sentences."""


@declares_action(PlannedAction(
    "recurring", "recurring", "theme_summary", uses_search=False, uses_llm=True,
))
def skill_recurring(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Ask LLM to name the through-line across visits."""
    if signal.host is None:
        return "No host available for recurring signal."

    evidence_str = _format_evidence(signal.evidence)
    prompt = RECURRING_PROMPT.format(host=signal.host, evidence=evidence_str)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=SKILL_MAX_TOKENS["recurring"])
# ---- dropped: short "is this still live?" nudge ----

DROPPED_PROMPT = """Host: {host}
Evidence:
{evidence}

This host has gone quiet. Phrase a short nudge (1-2 sentences) asking if it's still live or relevant."""


@declares_action(PlannedAction(
    "dropped", "dropped", "followup_nudge", uses_search=False, uses_llm=True,
))
def skill_dropped(signal: Signal, *, llm, search, verdict: bool) -> str:
    """Ask LLM to phrase a short nudge."""
    if signal.host is None:
        return "No host available for dropped signal."

    evidence_str = _format_evidence(signal.evidence)
    prompt = DROPPED_PROMPT.format(host=signal.host, evidence=evidence_str)

    # ⚠ LLM 실패를 문자열로 돌려주지 않는다 — 상위(run_act)가 신호 단위로
    #   잡아 errors 에 기록한다. 여기서 삼키면 실패가 행동 결과로 위장된다.
    return llm.complete(prompt, tier="nano", system=SKILL_SYSTEM, max_tokens=SKILL_MAX_TOKENS["dropped"])
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
) -> tuple[dict[str, bool | None], dict, list[str]]:
    """
    Run triage on signals up to max_signals.
    Returns (verdicts, stats, errors).
    """
    if max_signals < 0:
        raise ValueError("max_signals must be non-negative")
    if len({signal.key for signal in signals}) != len(signals):
        raise ValueError("Signal keys must be unique within a batch")
    verdicts: dict[str, bool | None] = {}
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
            verdicts[signal.key] = None  # ERROR is distinct from a triage SKIP

    return verdicts, stats, errors


def run_act(
    signals: list[Signal],
    verdicts: dict[str, bool | None],
    *,
    llm,
    search,
    stats: dict,
    errors: list[str],
    decisions: dict[str, SignalDecision],
    tracer: Tracer,
) -> tuple[list[Action], dict, list[str], list[SignalDecision]]:
    """
    Run skills only for ACT + allow. Every processed signal gets an audit record.
    """
    actions: list[Action] = []
    outcomes: list[SignalDecision] = []
    stats = {**stats, "held": 0, "denied": 0}
    errors = list(errors)

    for signal in signals:
        if signal.key not in verdicts:
            continue
        verdict = verdicts[signal.key]
        record = decisions[signal.key]  # Missing authorization is an error, never allow.
        skill = SKILLS.get(signal.kind)
        if verdict and record.mandate.verdict != "allow":
            stats["acted"] -= 1
            stats["held" if record.mandate.verdict == "hold" else "denied"] += 1
            if record.planned_action is None:
                errors.append(f"mandate:{signal.key}: no declared skill for kind '{signal.kind}'")
                stats["errors"] += 1
        elif verdict:
            try:
                text = skill(signal, llm=llm, search=search, verdict=True)
                actions.append(Action(signal.key, signal.kind, text, signal.evidence))
                record = replace(record, executed=True, execution_status="succeeded")
            except Exception as e:
                errors.append(f"act:{signal.key}: {e}")
                stats["errors"] += 1
                stats["acted"] -= 1
                record = replace(record, executed=True, execution_status="failed", execution_error=str(e))

        tracer.decision(
            signal_key=record.signal_key, signal_kind=record.signal_kind,
            triage=record.triage, planned_action=asdict(record.planned_action) if record.planned_action else None,
            mandate_digest=record.mandate.mandate_digest,
            verdict=record.mandate.verdict, reason=record.mandate.reason,
            executed=record.executed, execution_status=record.execution_status,
            execution_error=record.execution_error,
        )
        outcomes.append(record)

    return actions, stats, errors, outcomes


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


def mandate_node(
    state: AgentState, *, base_path: Path = DEFAULT_BASE_PATH,
    local_path: Path | None = DEFAULT_LOCAL_PATH,
) -> AgentState:
    """Snapshot both TOML layers once per invocation, then judge without an LLM."""
    mandate = load_mandate(base_path, local_path)
    decisions = {}
    for signal in state["signals"]:
        if signal.key not in state["_verdicts"]:
            continue
        verdict = state["_verdicts"][signal.key]
        plan = getattr(SKILLS.get(signal.kind), "planned_action", None)
        decisions[signal.key] = SignalDecision(
            signal.key, signal.kind,
            "ERROR" if verdict is None else "ACT" if verdict else "SKIP",
            plan, evaluate_mandate(mandate, signal, plan),
        )
    state["_decisions"] = decisions
    if mandate.error is not None:
        state["errors"] = [*state["errors"], f"mandate: {mandate.error}"]
        state["stats"] = {**state["stats"], "errors": state["stats"]["errors"] + 1}
    return state


def act_node(state: AgentState, *, tracer: Tracer | None = None) -> AgentState:
    """Run the skill for each signal that got ACT verdict."""
    signals = state["signals"]
    verdicts = state.get("_verdicts", {})
    llm = state["llm"]
    search = state["search"]
    stats = state.get("stats", {"acted": 0, "skipped": 0, "errors": 0})
    errors = state.get("errors", [])

    # Caller-owned tracers stay open; the default local tracer lives for one run.
    active_tracer = tracer if tracer is not None else Tracer()
    try:
        actions, stats, errors, decisions = run_act(
            signals, verdicts, llm=llm, search=search, stats=stats, errors=errors,
            decisions=state["_decisions"], tracer=active_tracer,
        )
    finally:
        if tracer is None:
            active_tracer.close()

    state["actions"] = actions
    state["stats"] = stats
    state["errors"] = errors
    state["decisions"] = decisions
    return state


# ============================================================
# Graph builder
# ============================================================

def build_graph(
    *, llm, search, mandate_path: Path = DEFAULT_BASE_PATH,
    mandate_local_path: Path | None = DEFAULT_LOCAL_PATH, tracer: Tracer | None = None,
) -> StateGraph:
    """
    Build and compile the LangGraph for the agent.
    Nodes: triage -> mandate -> act -> END
    """
    disable_external_tracing()
    graph = StateGraph(AgentState)

    # ⚠ llm·search 는 클로저로 잡는다. state 에서 꺼내면 build_graph 의 인자가
    #   무의미해지고, 호출자가 상태에 provider 를 끼워 넣어야 한다.
    def _triage(state):
        # Enforce local-only tracing even when a compiled graph is reused.
        disable_external_tracing()
        return triage_node({**state, "llm": llm})

    def _mandate(state):
        return mandate_node(state, base_path=mandate_path, local_path=mandate_local_path)

    def _act(state):
        return act_node({**state, "llm": llm, "search": search}, tracer=tracer)

    graph.add_node("triage", _triage)
    graph.add_node("mandate", _mandate)
    graph.add_node("act", _act)

    graph.set_entry_point("triage")
    graph.add_edge("triage", "mandate")
    graph.add_edge("mandate", "act")
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
    mandate_path: Path = DEFAULT_BASE_PATH,
    mandate_local_path: Path | None = DEFAULT_LOCAL_PATH,
    tracer: Tracer | None = None,
) -> AgentResult:
    """
    Run the agent over a batch of signals.

    Args:
        conn: Database connection (accepted for future use; unused currently)
        signals: List of Signal instances to process
        llm: Injected LLM with .complete(prompt, tier, system, max_tokens) -> str
        search: Injected search with .search(query, limit) -> list[dict]
        max_signals: Cost ceiling — process at most this many signals
        mandate_path: Required base TOML; unreadable/invalid means deny all skills
        mandate_local_path: Optional overlay; None explicitly disables the overlay
        tracer: Caller-owned local tracer, or a per-run default Tracer

    Returns:
        AgentResult with actions, errors, stats, and per-signal decisions. A hold
        never resumes automatically; the user must change the policy and rerun.
        Search restrictions do not prohibit triage or non-search skill LLM calls.

    Raises:
        OSError: A required local mandate audit record could not be written.
    """
    graph = build_graph(llm=llm, search=search, mandate_path=mandate_path,
                        mandate_local_path=mandate_local_path, tracer=tracer)

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
        decisions=final_state["decisions"],
    )
