# Browsing AI — before you ask

A personal AI that starts from past actions: an unfinished exploration, repeated
visits, a first signup, or a project that went quiet. It proposes follow-ups within
an explicit mandate and records the judgment and outcome in a local JSONL trace.

## Four differentiators

1. **Knows before you ask.** Prior actions, rather than a new instruction or goal,
   provide day-zero context. The demo opens with rule-detected signals. A signup
   path is a candidate for follow-up, not proof that registration was unfinished.
2. **Zero account permissions.** No OAuth, passwords, or email access. Raw history
   stays on the user's device; only scrubbed minimal fragments are used for
   inference. Search queries go to the selected search provider. The public demo
   uses entirely fictional history; no real browser data is deployed.
3. **Proposes and proves.** Model triage judges usefulness; deterministic mandate
   checks allow, hold, or deny execution. A local trace records the mandate digest, reason, and
   outcome. These are inspectable audit records, not cryptographic attestation.
4. **Open source and self-hostable.** One codebase, with private data and local
   configuration kept out of the public distribution. Providers are replaceable;
   local Nemotron execution has not been verified.

The current recurring detector groups by host, not semantic topic clustering.
A hold does not resume automatically. Change the mandate and run again.

## Start the offline walkthrough

Use Python 3.12 and the repository virtual environment, or install the minimal
runtime dependencies into your own virtual environment:

```sh
python -m pip install -r browsing/web/requirements.txt
DEMO_STATE_DIR=.demo-state python -m uvicorn browsing.web.app:create_app \
  --factory --host 127.0.0.1 --port 8080 --workers 1
```

Open `http://127.0.0.1:8080/`. No provider calls occur on startup, page views,
profile selection, cache export, or `GET /healthz`. The built-in fixture is
scripted; its precomputed walkthrough uses scripted fake providers and is
explicitly labeled **CACHED / illustrative-fixture**. It demonstrates pipeline
behavior, not past API usage. A live attempt is labeled **LIVE**; revisiting a
successful result is labeled **CACHED / live**.

After editing the maker scenario, rebuild the offline visits and all profile
caches with `python -m browsing.web regenerate-fixtures` (fake providers only).
See [fixture regeneration](web/fixtures/README.md) for inputs and reproducibility.

The public default allows research. Select **Search disabled** or **Confirm
research first** to compare `deny` and `hold` decisions. Profiles are predefined
server files; there is no TOML upload or history upload endpoint. The selected
policy and the policy used by a cached result have separately displayed digests.

## Live execution and limits

Provide `NEBIUS_API_KEY` and `TAVILY_API_KEY` as runtime environment variables.
Click **Run agent** to invoke the existing providers and agent loop. The existing
agent uses Nemotron Ultra for triage and Nano for skill text. Triage uses a
kind-specific evidence rubric with an 8,192-token reasoning/output ceiling;
this is a provisional cap, not measured usage or a guarantee of repeatability.
Skills request 2–3 English sentences: an observation and one suggested next step.
Tavily is called for an
unresolved search only if triage returns ACT and the mandate permits research;
SKIP, hold, and deny intentionally avoid that search call. Disabling search does
not disable LLM inference.

For an explicitly requested live quality evaluation of a validated synthetic DB:

```sh
python -m browsing.web eval-live --db /path/to/synthetic.db --runs 3
```

This command **calls paid providers**; it is not an offline test. It runs all three
mandate profiles by default. Repeat `--profile public` / `--profile no-search` /
`--profile confirm-research` to select a subset. With 12 signals and 3 runs per
profile, it makes 108 triage attempts, plus permitted skills and search calls.
It does not use the web server's daily budget or cached results; the CLI operator
chooses the run count. Input must have a matching synthetic validation manifest;
no browser path or `DEMO_DB` fallback is used. The demo's 20-signal limit applies.

JSON on stdout contains per-signal/per-profile ACT rates, counts, evidence,
skill samples, raw triage replies, errors and mandate audit traces. Rates exclude
triage errors (reported separately); malformed replies retain the agent's SKIP
fallback and remain visible in raw replies. A failed run produces JSON and exit 1;
invalid input raises before provider creation. Review samples for grounding and
sentence count: the offline tests verify prompt contracts, not live quality.
Temporary trace files are created beside the supplied DB and removed after capture
in JSON. Save stdout to a timestamped file if results need to be retained.

- `DEMO_DAILY_LIMIT`: total attempted runs per UTC day, default `20`; `0` disables
  live execution. Errors consume budget too. Each run processes at most 20 signals.
- `DEMO_STATE_DIR`: shared writable state directory for counters, successful
  cached results, and traces. SQLite transactions persist the daily budget.
- A nonblocking file lock permits **one run across all workers sharing that
  directory**. Busy or exhausted requests display the last successful result
  instead of invoking providers. Different cached mandates are called out.
- Failed runs return HTTP 502, display errors, and preserve the last successful
  cache. Failed trace writes are not reported as successful actions.
- Deploy **one replica** and mount persistent state. Independent replicas,
  replacing the state volume, or ephemeral restarts would reset/split the budget.
  Do not enable autoscaling without adding a shared durable execution gate.

The UI uses POST, bounded form bodies, CSRF tokens, HTML escaping, and fixed
profile identifiers. The global execution budget is the primary public cost cap.

## Generate a fictional persona (operator step; makes real API calls)

After reviewing the scenario and approving provider use:

```sh
python -m browsing.persona generate \
  --scenario browsing/persona/scenarios/maker.toml \
  --out browsing/demo-assets/maker-YYYYMMDD-HHMMSS.db --attempts 3
```

The scenario contains a fictional role and planted signals: two onboarding
services, one unresolved search, one dropped task, and one recurring host.
Nemotron Super via `providers.get_llm()` fills in URLs, titles, times, and search
terms. The generator feeds the **existing ingest schema**, runs `signals.py`, and
requires every planted kind **and exact host/search term** to be detected.
Invalid output or missing signals retry up to the requested bound (1–10 total
attempts). Provider errors propagate immediately. Exhaustion fails with no output
DB. Existing bundles are never overwritten.

The result is a DB plus adjacent `<database>.json` manifest (synthetic declaration,
scenario, SHA-256, and detected keys). Review generated text for identifiers before
publication; a synthetic marker or hash is not a privacy audit. No actual LLM
persona generation was performed while implementing this demo.

To use that bundle locally:

```sh
DEMO_DB=browsing/demo-assets/maker-YYYYMMDD-HHMMSS.db \
  DEMO_STATE_DIR=.demo-state python -m uvicorn browsing.web.app:create_app \
  --factory --host 127.0.0.1 --port 8080 --workers 1
```

The DB opens read-only and its hash and signals are checked against the manifest.
The fixed story window makes detection reproducible regardless of today's date.
Until this dataset has a cached run, all signals show explicit not-run states;
results from the built-in fixture are never presented as its results.

## Precompute and export a cache

Run each of the three profiles once against the reviewed synthetic DB. Then
export those successful runs with **no additional API calls**:

```sh
python -m browsing.web export-cache \
  --db browsing/demo-assets/maker-YYYYMMDD-HHMMSS.db \
  --state .demo-state --out browsing/demo-assets/cache-YYYYMMDD-HHMMSS.json
```

Set `DEMO_CACHE` to that JSON path to preload it on a fresh instance. The export
requires successful runs for all profiles and current mandate digests. Both the
DB fingerprint and mandate digest must match when displaying a cached result.
With this cache, the full walkthrough remains available during provider outages.
Keep the state volume as well: a cache file does not preserve the execution budget.

## CPU containers and Nebius Serverless

The root `.dockerignore` denies files by default and includes only the runtime
modules, public profiles, fictional fixtures, and explicitly staged synthetic
DB bundles under `browsing/demo-assets/`. Private history, reports, `.env*`,
`*.local.*`, scratch files, and repository history are excluded. The image copies
only the selected DB bundle; other staged DBs are not copied into the image.

```sh
docker build -f Dockerfile \
  --build-arg SYNTHETIC_DB=browsing/demo-assets/maker-YYYYMMDD-HHMMSS.db \
  -t browsing-demo .
docker volume create browsing-demo-state
docker run --rm -p 8080:8080 \
  -e NEBIUS_API_KEY -e TAVILY_API_KEY -e DEMO_DAILY_LIMIT=20 \
  -v browsing-demo-state:/state browsing-demo
```

For a precomputed cache, additionally bind-mount the exported JSON read-only to
`/cache/precomputed.json` and set `DEMO_CACHE=/cache/precomputed.json`.
Use a runtime secret store for keys; no API key is a build argument or image ENV.
The CPU image listens on port 8080, runs as UID/GID 10001, and checks `/healthz`.
Ensure the persistent state mount is writable by UID 10001. The generated DB and
manifest must already exist before building; no LLM runs during image build.

`Dockerfile.job` is a separate one-shot persona-generation container:

```sh
docker build -f Dockerfile.job -t browsing-persona-job .
# After provider-use approval, configure the Job's runtime NEBIUS_API_KEY,
# an output volume writable by UID 10001 at /output, and the command arguments:
# --scenario browsing/persona/scenarios/maker.toml --out /output/browsing.db
```

**Stack roles:** NVIDIA Nemotron provides inference; **Nebius Token Factory** is
the existing inference API; **Tavily** supplies permitted live research;
**Nebius AI Cloud Serverless** hosts the CPU web container and can execute the
separate generation Job. Configure the web service's public endpoint, port 8080,
one replica, runtime secrets, and persistent `/state` in the deployment service.
Actual Serverless deployment, persistence configuration, and image execution
remain to be verified by the deployment operator. No deployment was made here.

## Tests

```sh
python -m pytest browsing -q -p no:cacheprovider
```

Persona and web tests use fake providers only. They cover complete signal
validation, bounded retries, propagated errors, policy allow/hold/deny, trace
rendering, cache provenance, budget persistence and rollover, concurrent rejection,
health during a live run, invalid requests, and read-only synthetic bundles.
The original ingest, agent, mandate, and signal behavior is unchanged.
