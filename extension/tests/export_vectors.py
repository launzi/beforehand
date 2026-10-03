#!/usr/bin/env python3
"""Export only the supplied synthetic DB and Python oracle results. No provider calls."""
import ast
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from browsing.signals import detect_all, Signal, _chrome_us_from_iso
from browsing.scrub import scrub_url
from browsing.mandate import Mandate, PlannedAction, evaluate_mandate, load_mandate
from browsing.ingest import init_db, ingest_records

DB = ROOT / 'browsing/demo-assets/maker-20261003-075151.db'
OUT = Path(__file__).parent / 'vectors'


def edge_vectors():
    """Synthetic in-memory boundary cases; never read another disk database."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    day = 86400000000
    start = _chrome_us_from_iso('2026-10-02T15:00:00Z')  # KST midnight
    records = []
    def visit(url, us, profile='A'):
        records.append(dict(kind='visit',profile=profile,url=url,title='synthetic',
                            visit_time_us=us,transition=0,duration_us=0,from_visit_key=None))
    def search(url, term, us, profile='A'):
        visit(url, us, profile)
        records.append(dict(kind='search',profile=profile,url=url,term=term,first_seen_us=us))
    # Python new_entry still flags an old host with new onboarding in this window.
    visit('https://old.test/signup', start-20*day)
    visit('https://old.test/LOGIN/한😀', start+1)
    for offset in [-1,0,day,2*day]:
        visit('https://boundary.test/path',start+offset)
    # Quiet threshold is strict (<); one microsecond can change dropped status.
    for host,delta in [('exact.test',0),('before.test',-1)]:
        for offset in [-10,-9,-7]: visit(f'https://{host}/p',start+offset*day+delta)
    for i in range(3): visit('https://private.test/signup',start+i*day)
    search('https://search.test/?q=answered','answered',start)
    for offset in [1,1800000000,1800000001]: visit('https://answer.test/p',start+offset)
    search('https://search.test/?q=Shared','Shared',start,'A')
    search('https://search.test/?q=shared','shared',start+day,'B')
    search('https://private.test/?q=private','private',start,'A')
    # Earliest records before a window do not become repeated-search rows.
    search('https://search.test/?q=once','once',start-day)
    search('https://search.test/?q=once','once',start+day)
    ingest_records(conn,records)
    conn.execute("INSERT INTO domains (host, sensitivity) VALUES ('private.test', 'restricted')")
    conn.execute("INSERT INTO searches VALUES ('invalid','A',NULL,'invalid','invalid','not-a-date')")
    data = {name:[dict(row) for row in conn.execute(f'SELECT * FROM {name}')]
            for name in ('urls','visits','searches','domains')}
    cases=[]
    for profile in [None,'A','B','missing']:
        for restricted in [False,True]:
            for label,since,until,now in [('window',start,start+3*day,start+3*day),
                    ('exact',start,start+1,start),('quiet',start-30*day,start,start),
                    ('after',start+3*day,start+4*day,start+20*day)]:
                options=dict(since_us=since,until_us=until,now_us=now,profile=profile,include_restricted=restricted)
                cases.append(dict(name=f'edge/{label}/{profile}/{restricted}',options=options,
                                  expected=[asdict(s) for s in detect_all(conn,**options)]))
    conn.close()
    return dict(data=data,cases=cases)


def korea_vectors():
    from browsing.persona.generate import DEFAULT_SCENARIO, load_scenario, populate, detector_window
    from browsing.web.regenerate import scripted_visits
    from browsing.web.korea_quote import product_name
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    scenario = load_scenario(DEFAULT_SCENARIO)
    populate(conn, scripted_visits(scenario), scenario)
    # Add an observed transaction, an excluded host and a separate profile.
    ingest_records(conn, [{"kind":"visit", "profile":"synthetic", "url":"https://www.musinsa.com/orders/complete",
                           "title":"Complete", "visit_time_us":_chrome_us_from_iso('2026-09-30T22:00:00Z')}])
    conn.execute("INSERT INTO domains(host,sensitivity) VALUES ('smartstore.naver.com','restricted')")
    data = {name:[dict(row) for row in conn.execute(f'SELECT * FROM {name}')]
            for name in ('urls','visits','searches','domains')}
    cases=[]
    for profile in (None,'synthetic','missing'):
        for restricted in (False,True):
            options={**detector_window(scenario),'profile':profile,'include_restricted':restricted}
            cases.append({'name':f'korea/{profile}/{restricted}','options':options,
                          'expected':[asdict(s) for s in detect_all(conn,**options)]})
    conn.close()
    with (ROOT/'browsing/persona/scenarios/korea-domains.toml').open('rb') as stream:
        hosts=tomllib.load(stream)['korea_product']['hosts']
    names=['Anua Heartleaf 77% Soothing Toner 250ml | OLIVE YOUNG Global',
           'MUSINSA STANDARD Relaxed T-Shirt | MUSINSA', 'Vase - 네이버 스마트스토어',
           'Toner demo@example.com token=SECRET https://private.test | OLIVE YOUNG Global']
    from browsing.web.app import PROFILES
    profiles={key:{'digest':load_mandate(path,None).digest} for key,path in PROFILES.items()}
    return {'data':data,'cases':cases,'hosts':hosts,'profiles':profiles,'products':[{'input':n,'expected':product_name(n)} for n in names]}


def wire(value, key=''):
    if isinstance(value, dict):
        return {k: wire(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    if isinstance(value, int) and (key.endswith('_us') or abs(value) > 2**53-1):
        return str(value)
    return value


def main():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    data = {name: [dict(row) for row in conn.execute(f'SELECT * FROM {name}')]
            for name in ('urls', 'visits', 'searches', 'domains')}
    minimum, maximum = conn.execute('SELECT min(visit_time_us), max(visit_time_us) FROM visits').fetchone()
    day = 86400000000
    cases = []
    profiles = [row[0] for row in conn.execute('SELECT DISTINCT profile FROM visits')]
    for profile in [None, *profiles, 'missing-profile']:
        for restricted in [False, True]:
            for label, since, until, now in [('full', minimum, maximum+1, maximum+1),
                    ('recent', maximum-14*day, maximum+1, maximum+1),
                    ('quiet', minimum, maximum+1, maximum+9*day),
                    ('empty', maximum+day, maximum+2*day, maximum+2*day)]:
                options = dict(since_us=since, until_us=until, now_us=now, profile=profile, include_restricted=restricted)
                cases.append(dict(name=f'{label}/{profile}/{restricted}', options=options,
                    expected=[asdict(s) for s in detect_all(conn, **options)]))
    urls = [row['url'] for row in data['urls']]
    urls += ['https://example.com/s?' + n + '=SENSITIVE' for n in
        ['q','query','search_query','keyword','s','wd','page','tab','utm_code','code','state','access_token','session','secret','password','apikey','signature','nonce','auth_code','ACCESS_TOKEN']]
    urls += ['https://example.com/p?ref=' + 'A'*44, 'https://example.com/?q='+'a'*50,
             'https://example.com/?code=한😀글&x=a+b&x=&flag#keep',
             'http://[malformed?code=SENSITIVE#frag', '', 'not a url', '://', '?', '#', '  ',
             'HTTPS://Example.COM/p?a=%FF&code=abc', '/relative?a=1&&b=2',
             'https://example.com/?x=%3Credacted%3A3%3E',
             'https://example.com\uff0fprivate?q=secret',
             'http://[::1]/?code=private', 'http://[v1.test]/?q=ok', None, 12345]
    plans = {k: PlannedAction(k,k,a,s,True) for k,a,s in [
        ('unresolved','research_briefing',True),('new_entry','setup_check',False),
        ('recurring','theme_summary',False),('dropped','followup_nudge',False)]}
    plans['korea_product'] = PlannedAction('korea_quote','korea_product','commerce.quote',False,True)
    plans['checkout'] = PlannedAction('checkout','checkout','commerce.checkout',False,False)
    mandates = []
    for allowed in [[], [p.skill for p in plans.values()], ['unresolved'], ['스킬','😀','\ue000']]:
        for allow_search in [False,True]:
            for confirm in [[],['research_briefing','commerce.quote'],['setup_check','followup_nudge','theme_summary']]:
                mandates.append(Mandate(frozenset(allowed),allow_search,frozenset(confirm)))
    mandates.append(Mandate(frozenset(),False,frozenset(),error='base: required mandate file missing'))
    mandate_cases = []
    for m in mandates:
        value = dict(allowed_skills=sorted(m.allowed_skills),allow_search=m.allow_search,
                     require_confirmation=sorted(m.require_confirmation),error=m.error)
        for kind in [*plans,'unknown']:
            signal = Signal(kind,'test',None,None,{},0,0)
            for plan in [plans.get(kind), plans['new_entry']]:
                mandate_cases.append(dict(mandate=value, signal={'kind':kind}, plan=asdict(plan) if plan else None,
                    canonical=json.dumps({'schema_version':1,**value},sort_keys=True,separators=(',',':')),
                    expected=asdict(evaluate_mandate(m,signal,plan))))
    # Extract literal prompts and budgets without importing agent.py / graph runtime.
    tree = ast.parse((ROOT/'browsing/agent.py').read_text())
    names = ['TRIAGE_TIER','TRIAGE_MAX_TOKENS','SKILL_MAX_TOKENS','TRIAGE_SYSTEM','TRIAGE_RUBRICS',
             'TRIAGE_TEMPLATE','SKILL_SYSTEM','UNRESOLVED_PROMPT','NEW_ENTRY_PROMPT','RECURRING_PROMPT',
             'DROPPED_PROMPT','_SKILL_EVIDENCE_LABELS']
    constants = {}
    for node in tree.body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in names:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    # Compile only the two pure formatting helpers from trusted local source.
    # Do not import graph libraries or run any provider code.
    helpers = ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef)
        and node.name in ('_format_evidence','_format_skill_evidence')],type_ignores=[])
    namespace = dict(_SKILL_EVIDENCE_LABELS=constants['_SKILL_EVIDENCE_LABELS'],
                     _CHROME_EPOCH=datetime(1601,1,1,tzinfo=timezone.utc),timedelta=timedelta)
    exec(compile(helpers,'browsing/agent.py:formatting-helpers','exec'),namespace)
    evidence = [signal['evidence'] for signal in cases[0]['expected']]
    evidence += [{},{'last_visit_us':_chrome_us_from_iso('2026-10-03T00:00:00Z')-1},
                 {'empty':[], 'bools':[True,False], 'term':'한글 synthetic'}]
    formatting = [dict(evidence=item,triage=namespace['_format_evidence'](item),
                       skill=namespace['_format_skill_evidence'](item)) for item in evidence]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    result = wire(dict(source=str(DB.relative_to(ROOT)),source_sha256=hashlib.sha256(DB.read_bytes()).hexdigest(),
        data=data,cases=cases,edge=edge_vectors(),korea=korea_vectors(),scrub=[{'input':u,'expected':scrub_url(u)} for u in urls],
        mandate=mandate_cases,constants=constants,formatting=formatting))
    OUT.mkdir(exist_ok=True)
    dest = OUT/f'parity-{stamp}.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    dest.with_suffix('.json.md').write_text(
        '# Synthetic browser-extension parity vectors\n\n'
        'Python reference results for detector windows, URL scrubbing, mandate decisions, '
        'canonical JSON bytes/digests and prompt constants. Includes an in-memory boundary dataset. '
        'Used by Node tests; contains only synthetic visits and queries, never a real browser profile.\n\n'
        f'Source: `{DB.relative_to(ROOT)}`; SHA-256: `{result["source_sha256"]}`.\n\n'
        'Regenerate with `extension/tests/export_vectors.py`. The newest JSON vector is used by tests.\n')
    # Runtime source is readable, literal ES exports, generated only from public Python constants.
    generated = '// Apache-2.0 — Munteok. Literal prompts from browsing/agent.py; regenerate with tests/export_vectors.py.\n'
    generated += '\n'.join(f'export const {k} = {json.dumps(v, ensure_ascii=False, indent=2)};' for k,v in constants.items())+'\n'
    (ROOT/'extension/core/prompts.js').write_text(generated)
    print(f'{dest.relative_to(ROOT)}: {len(cases)} detector cases, {len(urls)} scrub cases, {len(mandate_cases)} mandate cases')

if __name__ == '__main__':
    main()
