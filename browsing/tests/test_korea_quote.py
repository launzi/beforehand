"""Offline quote boundary, mandate and synthetic detection acceptance tests."""
from dataclasses import asdict, replace
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from browsing.agent import run_agent, skill_korea_quote, SKILLS, TRIAGE_SYSTEM
from browsing.mandate import evaluate_mandate, load_mandate, PlannedAction
from browsing.persona.generate import DEFAULT_SCENARIO, load_scenario, populate, records_from_payload, detector_window
from browsing.ingest import ingest_records
from browsing.signals import detect_all
from browsing.trace import Tracer
from browsing.web.app import PROFILES, ROOT
from browsing.web.regenerate import ScriptedLLM, ScriptedSearch, scripted_visits
from browsing.web.korea_quote import (
    ENDPOINT, DISCLOSURE, KoreaQuoteClient, QuoteError, product_name, quote_arguments,
    parse_rpc, sanitize_quote, summary_facts, validate_summary,
)


@pytest.fixture
def raw():
    return json.loads((ROOT / 'fixtures/korea-quote-20261003-004400.json').read_text())


def response(raw, status=200, sse=False):
    rpc = {'jsonrpc': '2.0', 'id': 1, 'result': {'structuredContent': raw}}
    return SimpleNamespace(status_code=status, headers={'content-type': 'text/event-stream' if sse else 'application/json'},
        json=lambda: rpc, text='event: message\r\ndata: '+json.dumps(rpc)+'\r\n\r\n')


@pytest.mark.parametrize('sse', [False, True])
def test_exact_minimal_wire_and_token_boundary(raw, sse):
    calls=[]
    raw['payNow']['quoteToken']='NESTED_SECRET'
    raw['quoteToken']='TOP_SECRET'
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response(raw, sse=sse)
    quote=KoreaQuoteClient(post).quote('Anua Heartleaf 77% Soothing Toner 250ml | OLIVE YOUNG Global')
    url, call=calls[0]
    assert url == ENDPOINT
    assert call['json'] == {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{
        'name':'quote_korea_product','arguments':{'product':'Anua Heartleaf 77% Soothing Toner 250ml','destination':'US'}}}
    assert call['allow_redirects'] is False
    assert call['headers'] == {'content-type':'application/json','accept':'application/json, text/event-stream'}
    assert quote['payNow']['total'] == 60.49
    assert quote['dutyOnDelivery']['lines'][1]['amount'] == 2.089235915388495
    for forbidden in ['quoteToken','TOP_SECRET','NESTED_SECRET','next_steps','quoteExpiresAt']:
        assert forbidden not in json.dumps(quote)
        assert forbidden not in json.dumps(summary_facts(quote))
    assert "fulfilment" not in json.dumps(summary_facts(quote))


@pytest.mark.parametrize('rpc,message', [
    ({'error':{'code':-32000,'message':'Rate limit exceeded'}},'Rate limit exceeded'),
    ({'error':{'code':-32000,'message':'koreaPriceKrw required: price not found'}},'price not found'),
    ({'result':{'isError':True,'content':[{'type':'text','text':'Please supply koreaPriceKrw'}]}},'price not found'),
    ({'result':{'structuredContent':{'error':'price not found'}}},'price not found'),
    ({'result':{'content':[{'type':'text','text':'price not found'}]}},'price not found'),
    ({'error':{'message':'opaque sensitive service error'}},'Quote service error'),
    ({'result':{}},'Malformed quote response'),
])
def test_error_categories_are_explicit_and_do_not_echo_payloads(rpc, message):
    with pytest.raises(QuoteError, match=message):
        parse_rpc(rpc)


@pytest.mark.parametrize('status,message', [(429,'Rate limit exceeded'),(302,'Quote HTTP 302'),(500,'Quote HTTP 500')])
def test_http_errors(raw,status,message):
    with pytest.raises(QuoteError,match=message):
        KoreaQuoteClient(lambda *a,**kw:response(raw,status)).quote('Anua toner')


def test_unknown_verdict_and_missing_local_price_preserved(raw):
    raw['verdict']='future_verdict_not_in_client'
    raw['localPrice']=None
    quote=parse_rpc({'result':{'content':[{'type':'text','text':json.dumps(raw)}]}})
    assert quote['verdict']=='future_verdict_not_in_client'
    assert quote['localPrice'] is None


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), '60.49', True])
def test_malformed_amounts_fail_closed(raw,value):
    raw['payNow']['total']=value
    with pytest.raises(QuoteError,match='amount'):
        sanitize_quote(raw)


def test_names_are_scrubbed_without_removing_brand():
    assert product_name('MUSINSA STANDARD T-Shirt | MUSINSA') == 'MUSINSA STANDARD T-Shirt'
    name=product_name('Toner demo@example.com token=SECRET https://private.test/path | OLIVE YOUNG Global')
    for forbidden in ['demo@example.com','SECRET','https://','private.test','OLIVE']:
        assert forbidden not in name
    assert set(quote_arguments(name)) == {'product','destination'}
    with pytest.raises(QuoteError): quote_arguments('a')
    with pytest.raises(QuoteError): quote_arguments('toner','AU')


def test_minimal_product_detection_is_additive_and_conservative():
    scenario=load_scenario(DEFAULT_SCENARIO)
    payload=scripted_visits(scenario)
    with sqlite3.connect(':memory:') as conn:
        signals=populate(conn,payload,scenario)
        korea=[s for s in signals if s.kind=='korea_product']
        assert len(korea)==3
        assert all(s.evidence['visit_count']==2 for s in korea)
        baseline=detect_all(conn,**detector_window(scenario),profile='synthetic')
        # A purchase page on one host suppresses only that quote candidate.
        extra={'visits':[{'url':'https://www.musinsa.com/orders/complete','title':'Purchase complete','at':'2026-09-30T20:00:00+00:00'}]}
        ingest_records(conn,records_from_payload(extra,scenario))
        after=detect_all(conn,**detector_window(scenario),profile='synthetic')
        assert len([s for s in after if s.kind=='korea_product'])==2
        assert [s for s in baseline if s.kind=='unresolved']==[s for s in after if s.kind=='unresolved']
        assert not detect_all(conn,**detector_window(scenario),profile='other')
        conn.execute("INSERT INTO domains(host,sensitivity) VALUES ('global.oliveyoung.com','restricted')")
        assert len([s for s in detect_all(conn,**detector_window(scenario),profile='synthetic') if s.kind=='korea_product'])==1


@pytest.mark.parametrize('profile,expected', [('public','allow'),('no-search','deny'),('confirm-research','hold')])
def test_quote_mandates_and_end_to_end_token_absence(tmp_path,raw,profile,expected):
    scenario=load_scenario(DEFAULT_SCENARIO)
    with sqlite3.connect(':memory:') as conn:
        signal=next(s for s in populate(conn,scripted_visits(scenario),scenario) if s.kind=='korea_product')
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs['json']['params']['arguments'])
        return response(raw)
    path=tmp_path/'trace.jsonl'
    with closing(Tracer(path=path)) as tracer:
        result=run_agent(None,signals=[signal],llm=ScriptedLLM(),search=ScriptedSearch(),
            quote_client=KoreaQuoteClient(post),mandate_path=PROFILES[profile],mandate_local_path=None,tracer=tracer)
    assert not result.errors
    assert result.decisions[0].mandate.verdict==expected
    assert len(calls)==(1 if expected=='allow' else 0)
    serialized=json.dumps(asdict(result))+path.read_text()
    for forbidden in ['quoteToken','REDACTED-IN-FIXTURE','next_steps']:
        assert forbidden not in serialized
    if expected=='allow':
        assert result.actions[0].quote['totalCost']==65.27
        assert result.actions[0].text.startswith("It's cheaper to buy locally")
    plan=PlannedAction('anything',signal.kind,'commerce.checkout',False,False)
    denied=evaluate_mandate(load_mandate(PROFILES[profile],None),signal,plan)
    assert (denied.verdict,denied.reason)==('deny','Checkout is out of scope for this build')


def test_summary_fails_instead_of_rendering_invented_costs(raw):
    q=sanitize_quote(raw)
    with pytest.raises(QuoteError,match='unsupported number'):
        validate_summary("It's cheaper to buy locally. It costs USD 9.99.",q)
    with pytest.raises(QuoteError,match='cheaper local'):
        validate_summary('Try the concierge first.',q)


def test_docker_copy_layout_contains_every_quote_runtime_dependency(tmp_path):
    """Emulate existing source COPY layout; no Docker build, downloads or network."""
    import os
    import shutil
    import subprocess
    import sys
    root=Path(__file__).parents[2]
    # Follow literal existing COPY instructions, not a bespoke list of new modules.
    for line in (root/'Dockerfile').read_text().splitlines():
        if not line.startswith('COPY browsing/') or '${' in line:
            continue
        *sources,target=line.split()[1:]
        for source in sources:
            source=root/source
            dest=tmp_path/target.removeprefix('/app/')
            if source.is_dir():
                shutil.copytree(source,dest,ignore=shutil.ignore_patterns('__pycache__','tests'),dirs_exist_ok=True)
            elif target.endswith('/'):
                dest.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest/source.name)
            else:
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    assert not (tmp_path/'browsing/classify.py').exists()
    assert not (tmp_path/'browsing/korea_quote.py').exists()
    script="""
from pathlib import Path
from browsing.web.regenerate import regenerate_fixtures
cache=regenerate_fixtures(output_dir=Path('regenerated'))
assert all(p['status']=='complete' for p in cache['profiles'].values())
assert sum(a['quote'] is not None for a in cache['profiles']['public']['result']['actions'])==3
"""
    env={**os.environ,'PYTHONPATH':str(tmp_path),'PYTHONDONTWRITEBYTECODE':'1'}
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_quote_failure_is_an_error_not_a_successful_action(tmp_path):
    scenario=load_scenario(DEFAULT_SCENARIO)
    with sqlite3.connect(':memory:') as conn:
        signal=next(s for s in populate(conn,scripted_visits(scenario),scenario) if s.kind=='korea_product')
    class FailedQuote:
        def quote(self, **args):
            raise QuoteError('price not found')
    with closing(Tracer(path=tmp_path/'trace.jsonl')) as tracer:
        result=run_agent(None,signals=[signal],llm=ScriptedLLM(),search=ScriptedSearch(),
            quote_client=FailedQuote(),mandate_path=PROFILES['public'],mandate_local_path=None,tracer=tracer)
    assert result.actions==[]
    assert result.stats['errors']==1
    assert 'price not found' in result.errors[0]
    assert result.decisions[0].execution_status=='failed'


# KC contract pinned from kc-order-pipeline origin/main 193bf2a (PR #13):
# src/lib/jikgugak/deliveredQuote.ts success body keys.
KC_SUCCESS_KEYS = {"seller", "item", "destination", "currency", "payNow", "dutyOnDelivery",
                   "totalCost", "localPrice", "verdict", "hs", "warnings", "quoteToken",
                   "quoteExpiresAt", "fulfilment", "next_steps"}
SANITIZED_KEYS = {"seller", "item", "destination", "currency", "payNow", "dutyOnDelivery",
                  "totalCost", "localPrice", "verdict", "warnings", "fulfilment"}


def rpc(data):
    return {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": data}}


def test_fixture_matches_current_kc_contract_and_sanitize_allowlist(raw):
    assert set(raw) == KC_SUCCESS_KEYS
    quote = sanitize_quote(raw)
    assert set(quote) == SANITIZED_KEYS
    assert quote["seller"] == "Munteok"
    assert quote["fulfilment"] == raw["fulfilment"]
    assert quote["fulfilment"]
    assert "fulfilment" not in summary_facts(quote)
    for leaked in ("hs", "quoteToken", "quoteExpiresAt", "next_steps"):
        assert leaked not in quote


@pytest.mark.parametrize("missing", [False, True])
def test_null_or_missing_verdict_is_unknown_not_error(raw, missing):
    if missing:
        del raw["verdict"]
    else:
        raw["verdict"] = None
    quote = sanitize_quote(raw)
    assert quote["verdict"] is None
    assert summary_facts(quote)["verdict"] is None


def test_fulfilment_is_optional_and_bounded(raw):
    raw.pop("fulfilment")
    assert sanitize_quote(raw)["fulfilment"] is None
    raw["fulfilment"] = "Munteok\x00 is\nthe seller."
    assert sanitize_quote(raw)["fulfilment"] == "Munteok is the seller."
    raw["fulfilment"] = "x" * 501
    with pytest.raises(QuoteError):
        sanitize_quote(raw)


@pytest.mark.parametrize("data,message", [
    ({"error": "quote_unavailable", "message": "This item needs a manual quote.", "warnings": []},
     "Quote unavailable for this item"),
    ({"error": "quote_unavailable", "message": "No Korean listing found.", "warnings": [],
      "needsManualPrice": "Send koreaPriceKrw"}, "price not found"),
    ({"error": "estimate_unavailable", "message": "Estimate service unavailable. Try again later."},
     "Quote service unavailable"),
])
def test_kc_error_envelopes_map_to_clear_errors(data, message):
    with pytest.raises(QuoteError, match=message):
        parse_rpc(rpc(data))


@pytest.fixture
def korea_signal():
    scenario = load_scenario(DEFAULT_SCENARIO)
    with sqlite3.connect(':memory:') as conn:
        return next(s for s in populate(conn, scripted_visits(scenario), scenario)
                    if s.kind == 'korea_product')


@pytest.mark.parametrize('remainder', [
    'Duty is an estimate.',
    'Duty is an estimate. Shipping may change.',
])
def test_buy_local_disclosure_is_generated_before_model_remainder(raw, korea_signal, remainder):
    raw['localPrice']['price'] = 18.25
    raw['totalCost'] = 66.75
    calls = []

    class LLM:
        def complete(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return remainder

    text, quote = skill_korea_quote(korea_signal, llm=LLM(), search=None, verdict=True,
        quote_client=KoreaQuoteClient(lambda *a, **kw: response(raw)))
    assert text == ("It's cheaper to buy locally: USD 18.25 locally versus "
                    "USD 66.75 estimated total cost from Korea. " + remainder)
    assert validate_summary(text, quote) == text
    assert len(calls) == 1
    assert json.loads(calls[0][0].removeprefix('Korea quote facts: ')) == summary_facts(quote)
    assert '1-2 sentences' in calls[0][1]['system']
    assert 'not restate the local-price comparison' in calls[0][1]['system']


@pytest.mark.parametrize('remainder,message', [
    ('You save USD 9999.', 'unsupported number'),
    ('', '2-3 sentences'),
    ('Duty is estimated. Shipping may vary. Check the warnings.', '2-3 sentences'),
])
def test_buy_local_still_rejects_invalid_model_remainder(raw, korea_signal, remainder, message):
    llm = SimpleNamespace(complete=lambda *a, **kw: remainder)
    with pytest.raises(QuoteError, match=message):
        skill_korea_quote(korea_signal, llm=llm, search=None, verdict=True,
            quote_client=KoreaQuoteClient(lambda *a, **kw: response(raw)))


@pytest.mark.parametrize('verdict', ['buy_from_korea', 'close_call', 'insufficient_data', None, 'future_verdict'])
def test_other_verdict_summaries_are_unchanged(raw, korea_signal, verdict):
    from browsing.web.korea_quote import SUMMARY_SYSTEM
    raw['verdict'] = verdict
    model_text = 'Duty is an estimate. Shipping may change.'

    class LLM:
        def complete(self, prompt, **kwargs):
            assert kwargs['system'] == SUMMARY_SYSTEM
            return model_text

    text, quote = skill_korea_quote(korea_signal, llm=LLM(), search=None, verdict=True,
        quote_client=KoreaQuoteClient(lambda *a, **kw: response(raw)))
    assert text == model_text
    assert quote['verdict'] == verdict


def test_buy_local_without_local_price_does_not_invent_amount(raw, korea_signal):
    raw['localPrice'] = None
    text, quote = skill_korea_quote(korea_signal,
        llm=SimpleNamespace(complete=lambda *a, **kw: 'Duty is an estimate.'),
        search=None, verdict=True, quote_client=KoreaQuoteClient(lambda *a, **kw: response(raw)))
    assert text.startswith("It's cheaper to buy locally according to the service verdict; no local price was supplied.")
    assert validate_summary(text, quote) == text


UNAVAILABLE_ENVELOPES = [
    rpc({'error': 'quote_unavailable', 'message': 'This item needs a manual quote.', 'warnings': []}),
    rpc({'error': 'quote_unavailable', 'message': 'No Korean listing found.',
         'needsManualPrice': 'Send koreaPriceKrw', 'warnings': []}),
    rpc({'needsManualPrice': 'Send koreaPriceKrw'}),
    rpc({'error': 'price not found'}),
    {'error': {'code': -32000, 'message': 'koreaPriceKrw required: price not found'}},
    {'result': {'isError': True, 'content': [{'type': 'text', 'text': 'Please supply koreaPriceKrw'}]}},
    {'result': {'content': [{'type': 'text', 'text': 'price not found'}]}},
]


@pytest.mark.parametrize('envelope', UNAVAILABLE_ENVELOPES)
def test_unavailable_is_typed_and_succeeds_without_summary_llm(tmp_path, korea_signal, envelope):
    from browsing.web.korea_quote import QuoteUnavailable
    with pytest.raises(QuoteUnavailable):
        parse_rpc(envelope)
    client = KoreaQuoteClient(lambda *a, **kw: SimpleNamespace(
        status_code=200, headers={}, json=lambda: envelope))

    class TriageOnlyLLM:
        def complete(self, prompt, **kwargs):
            assert kwargs['system'] == TRIAGE_SYSTEM, 'Unavailable quotes must not call the summary LLM'
            return 'ACT'

    llm = TriageOnlyLLM()
    text, quote = skill_korea_quote(korea_signal, llm=llm, search=None,
                                   verdict=True, quote_client=client)
    assert quote is None
    assert text == 'No Korea quote is available for this item right now; it needs a manual price.'
    with closing(Tracer(path=tmp_path / 'trace.jsonl')) as tracer:
        result = run_agent(None, signals=[korea_signal], llm=llm, search=ScriptedSearch(),
            quote_client=client, mandate_path=PROFILES['public'], mandate_local_path=None, tracer=tracer)
    assert result.errors == []
    assert result.stats['errors'] == 0
    assert result.stats['acted'] == 1
    assert result.decisions[0].execution_status == 'succeeded'
    assert result.actions[0].quote is None
    assert result.actions[0].quote_unavailable is True
    assert asdict(result)['actions'][0]['quote_unavailable'] is True


@pytest.mark.parametrize('envelope', [
    {'error': {'code': -32000, 'message': 'Rate limit exceeded for price lookup'}},
    {'result': {'isError': True, 'content': [{'type': 'text', 'text': 'Rate limit exceeded for price lookup'}]}},
    rpc({'error': 'estimate_unavailable', 'message': 'Price estimate service unavailable.'}),
    rpc({'error': 'service_unavailable', 'message': 'Price service unavailable.'}),
    rpc({'item': {'priceKrw': 100}}),
    {'result': {'content': [{'type': 'text', 'text': '{"price": broken json'}]}},
    {'result': {'content': [{'type': 'text', 'text': '{"error": "price not found"'}]}},
    {'result': {}},
])
def test_service_and_malformed_errors_remain_failed_actions(tmp_path, korea_signal, envelope):
    from browsing.web.korea_quote import QuoteUnavailable
    with pytest.raises(QuoteError) as exc:
        parse_rpc(envelope)
    assert not isinstance(exc.value, QuoteUnavailable)
    client = KoreaQuoteClient(lambda *a, **kw: SimpleNamespace(
        status_code=200, headers={}, json=lambda: envelope))
    with closing(Tracer(path=tmp_path / 'trace.jsonl')) as tracer:
        result = run_agent(None, signals=[korea_signal], llm=ScriptedLLM(), search=ScriptedSearch(),
            quote_client=client, mandate_path=PROFILES['public'], mandate_local_path=None, tracer=tracer)
    assert result.actions == []
    assert result.stats['errors'] == 1
    assert len(result.errors) == 1
    assert result.decisions[0].execution_status == 'failed'


@pytest.mark.parametrize('failure', ['rate_limit', 'malformed_json', 'transport'])
def test_client_failures_remain_execution_errors(tmp_path, korea_signal, failure):
    import urllib.error

    def post(*args, **kwargs):
        if failure == 'transport':
            raise urllib.error.URLError('synthetic network failure')
        def invalid_json():
            raise ValueError('invalid JSON')
        return SimpleNamespace(status_code=429 if failure == 'rate_limit' else 200,
                               headers={}, json=invalid_json)

    with closing(Tracer(path=tmp_path / 'trace.jsonl')) as tracer:
        result = run_agent(None, signals=[korea_signal], llm=ScriptedLLM(), search=ScriptedSearch(),
            quote_client=KoreaQuoteClient(post), mandate_path=PROFILES['public'],
            mandate_local_path=None, tracer=tracer)
    assert result.actions == []
    assert result.stats['errors'] == 1
    assert result.decisions[0].execution_status == 'failed'
