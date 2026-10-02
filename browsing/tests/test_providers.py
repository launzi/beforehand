"""provider 계약 테스트 — 검색·LLM 교체 가능성.

두 가지가 급소다.

  1. **기본값이 Tavily + Nebius 여야 한다.** 제출 자격이 거기 걸려 있다 —
     Token Factory 런타임 호출은 참가 자격 자체이고, Tavily 런타임 호출은 보너스
     요건이다. 개인 인스턴스가 다른 것으로 바꿔 끼우는 것은 설정이지 코드 분기가 아니다.
  2. 키가 없거나 이름이 틀렸을 때 **조용히 비어 있는 결과를 주면 안 된다.**

⚠ 네트워크를 타지 않는다. 실제 호출은 별도 프로브로 확인한다.
"""

import pytest

from browsing.providers import (
    ProviderError,
    get_llm,
    get_search,
    list_llm,
    list_search,
)


# 티어 해석은 _raw_models 를 부른다 — 그것까지 막아야 네트워크를 안 탄다.
FAKE_MODELS = [
    {"id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"},
    {"id": "nvidia/nemotron-3-super-120b-a12b"},
    {"id": "nvidia/Nemotron-3-Ultra-550b-a55b"},
]


def _offline_llm(monkeypatch, complete_fn):
    p = get_llm("nebius")
    monkeypatch.setattr(p, "_resolve_key", lambda: "k", raising=False)
    monkeypatch.setattr(p, "_raw_models", lambda: FAKE_MODELS, raising=False)
    monkeypatch.setattr(p, "_raw_complete", complete_fn, raising=False)
    return p


# ── 기본값 — 제출 자격이 걸려 있다 ────────────────────────────────────────────

def test_default_search_provider_is_tavily():
    assert get_search().name == "tavily"


def test_default_llm_provider_is_nebius():
    assert get_llm().name == "nebius"


def test_defaults_are_not_overridden_by_registry_order():
    """다른 provider 를 나중에 등록해도 기본값은 바뀌지 않는다."""
    assert get_search(None).name == "tavily"
    assert get_llm(None).name == "nebius"


# ── 교체 ─────────────────────────────────────────────────────────────────────

def test_named_search_provider_is_returned():
    assert get_search("serper").name == "serper"


def test_registry_lists_available_providers():
    assert "tavily" in list_search()
    assert "serper" in list_search()
    assert "nebius" in list_llm()


def test_unknown_search_provider_raises_with_the_name():
    with pytest.raises(ProviderError) as e:
        get_search("nope")
    assert "nope" in str(e.value)


def test_unknown_llm_provider_raises_with_the_name():
    with pytest.raises(ProviderError) as e:
        get_llm("nope")
    assert "nope" in str(e.value)


def test_error_names_the_available_options():
    """무엇을 쓸 수 있는지 알려주지 않으면 사용자가 추측하게 된다."""
    with pytest.raises(ProviderError) as e:
        get_search("nope")
    assert "tavily" in str(e.value)


# ── 인터페이스 ───────────────────────────────────────────────────────────────

def test_search_provider_exposes_search():
    assert callable(get_search().search)


def test_llm_provider_exposes_complete():
    assert callable(get_llm().complete)


@pytest.mark.parametrize("name", ["tavily", "serper"])
def test_every_search_provider_has_a_name_attribute(name):
    assert get_search(name).name == name


# ── 키 부재는 명확히 실패한다 ────────────────────────────────────────────────

def test_search_without_key_raises_not_returns_empty(monkeypatch):
    """키가 없는데 빈 결과를 주면 '검색 결과 없음'과 구분이 안 된다."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    p = get_search("tavily")
    monkeypatch.setattr(p, "_resolve_key", lambda: None, raising=False)
    with pytest.raises(ProviderError):
        p.search("anything")


def test_llm_without_key_raises(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    p = get_llm("nebius")
    monkeypatch.setattr(p, "_resolve_key", lambda: None, raising=False)
    with pytest.raises(ProviderError):
        p.complete("hi")


# ── 검색 결과 형태 — 상위 계층이 의존한다 ─────────────────────────────────────

def test_search_normalises_results(monkeypatch):
    """provider 마다 응답 형태가 다르다. 위층이 그것을 알면 안 된다."""
    p = get_search("tavily")
    monkeypatch.setattr(p, "_raw_search", lambda q, n: {
        "results": [{"title": "T", "url": "https://x.test", "content": "body"}]
    }, raising=False)
    monkeypatch.setattr(p, "_resolve_key", lambda: "k", raising=False)
    out = p.search("q")
    assert out[0]["title"] == "T"
    assert out[0]["url"] == "https://x.test"
    assert "snippet" in out[0]


def test_serper_normalises_to_the_same_shape(monkeypatch):
    p = get_search("serper")
    monkeypatch.setattr(p, "_raw_search", lambda q, n: {
        "organic": [{"title": "T2", "link": "https://y.test", "snippet": "s"}]
    }, raising=False)
    monkeypatch.setattr(p, "_resolve_key", lambda: "k", raising=False)
    out = p.search("q")
    assert out[0]["title"] == "T2"
    assert out[0]["url"] == "https://y.test"
    assert out[0]["snippet"] == "s"


def test_empty_response_gives_empty_list_not_error(monkeypatch):
    p = get_search("tavily")
    monkeypatch.setattr(p, "_raw_search", lambda q, n: {"results": []}, raising=False)
    monkeypatch.setattr(p, "_resolve_key", lambda: "k", raising=False)
    assert p.search("q") == []


def test_blank_query_raises(monkeypatch):
    p = get_search("tavily")
    monkeypatch.setattr(p, "_resolve_key", lambda: "k", raising=False)
    with pytest.raises(ProviderError):
        p.search("   ")


# ── LLM 응답 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content", ["hello", "\nACT", "  answer\n"])
def test_llm_returns_text(monkeypatch, content):
    p = _offline_llm(monkeypatch, lambda **kw: {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"completion_tokens": 3},
    })
    assert p.complete("hi") == content


@pytest.mark.parametrize("content", [None, "", " \n\t"])
@pytest.mark.parametrize("finish_reason", ["length", "stop"])
def test_llm_empty_content_raises_not_returns_blank(monkeypatch, content, finish_reason):
    """Nemotron 은 추론 예산에 먹히면 빈 content 를 준다. 그것을 답으로 쓰면 안 된다."""
    p = _offline_llm(monkeypatch, lambda **kw: {
        "choices": [{"message": {"content": content, "reasoning": "thinking..."},
                     "finish_reason": finish_reason}],
        "usage": {"completion_tokens": 100},
    })
    with pytest.raises(ProviderError) as e:
        p.complete("hi")
    assert f"finish_reason={finish_reason}" in str(e.value)
    if finish_reason == "stop":
        assert "empty content" in str(e.value)


def test_llm_tier_selects_a_model(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {}}

    p = _offline_llm(monkeypatch, fake)
    p.complete("hi", tier="nano")
    assert "nano" in str(seen.get("model", "")).lower()


# ── 키가 없으면 네트워크를 타지 않는다 (테스트 시간이 드러낸 결함) ────────────

def test_no_network_call_when_llm_key_is_missing(monkeypatch):
    """키 검사가 모델 조회 뒤에 있으면, 키도 없는데 밖으로 나간다.

    실측: 이 테스트가 1.92초 걸렸다. monkeypatch 한 테스트가 느리다는 것은
    진짜 소켓을 열었다는 뜻이다.
    """
    p = get_llm("nebius")
    monkeypatch.setattr(p, "_resolve_key", lambda: None, raising=False)

    def boom(*a, **k):
        raise AssertionError("키가 없는데 네트워크를 탔다")

    monkeypatch.setattr(p, "_raw_models", boom, raising=False)
    monkeypatch.setattr(p, "_raw_complete", boom, raising=False)
    with pytest.raises(ProviderError):
        p.complete("hi")


def test_no_network_call_when_search_key_is_missing(monkeypatch):
    p = get_search("tavily")
    monkeypatch.setattr(p, "_resolve_key", lambda: None, raising=False)

    def boom(*a, **k):
        raise AssertionError("키가 없는데 네트워크를 탔다")

    monkeypatch.setattr(p, "_raw_search", boom, raising=False)
    with pytest.raises(ProviderError):
        p.search("q")


def test_blank_query_does_not_reach_the_network(monkeypatch):
    p = get_search("tavily")
    monkeypatch.setattr(p, "_resolve_key", lambda: "k", raising=False)

    def boom(*a, **k):
        raise AssertionError("빈 질의로 네트워크를 탔다")

    monkeypatch.setattr(p, "_raw_search", boom, raising=False)
    with pytest.raises(ProviderError):
        p.search("   ")
