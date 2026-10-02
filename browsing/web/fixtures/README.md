# Offline walkthrough

`visits.json` is a scripted fictional fixture, not exported browser history
and not an LLM-generated persona. `cache.json` contains precomputed results from
the real agent and mandate pipeline with explicitly scripted fake providers.
The page labels these as `illustrative-fixture`; they do not establish API usage.
The cache includes the SHA-256 of the exact fixture bytes and each applied mandate.
It is never substituted for a different generated dataset or mandate.

The generated deployment bundle is separate: create it with `browsing.persona`
after review, then supply its DB and validation manifest to the container build.

## Regeneration (offline, no API keys)

From the repository root, with the project's Python environment:

```bash
python -m browsing.web regenerate-fixtures
```

This replaces `visits.json` and `cache.json` together after successful validation
and execution of all three profiles. Optional `--scenario PATH` and
`--output-dir DIRECTORY` select the scenario and destination. The default is
`browsing/persona/scenarios/maker.toml` and this directory; it does not read
`DEMO_DB`, browser data, saved live runs, or provider credentials.

The maker story in `browsing/web/regenerate.py` derives hosts, the search term,
and dates from the scenario. It uses the real ingest/signal validation and
`browsing.web.app.execute` agent/mandate pipeline, passing scripted LLM and
search providers explicitly. The dataset digest is computed from the exact
new JSON bytes; signal keys and mandate digests come from the pipeline.
The visits and decisions are reproducible; cache creation/trace timestamps and
elapsed times reflect each new run. No hashes or trace records are hand-edited.
When changing the scenario's story structure (not just hostnames), update the
scripted story too; incompatible stories fail validation before publication.
