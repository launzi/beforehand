# Before You Ask — Chrome MV3 MVP

Munteok · 0.1.0 · Apache-2.0. A dependency-free, readable ES-module port of the local browsing signal pipeline. No build, package installation, bundler, minification, service worker or remote scripts.

## Install unpacked

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select this `extension/` directory.
4. Open **Before You Ask** from the extensions menu. Read and accept the first-use disclosure.
5. Open **Settings** and save a Nebius Token Factory API key. Optionally add a Tavily key for research. Saving does not contact providers.
6. Press **Scan local history**. Choose an allowed signal and inspect **What leaves your device**.
7. Press **Run this request** to execute only that request. Model discovery, Ultra triage, optional Tavily research and Nano suggestions each need their own review and Run click.

Use **Open in a tab** for longer work. Keep the extension page open while requests run; closing a popup can interrupt work. An interrupted trace can retain a `sending` record with no completion. No background job retries it. A request already sent cannot be recalled.

The extension is free; provider account charges may apply. There are no developer-owned API keys. Keys are saved only in `chrome.storage.local`, not sync; they are not additionally encrypted. Use Settings to delete keys, settings or traces. Chrome's original history is never modified.

## Mandate and privacy

Search can be **Allow**, **Hold — require confirmation**, or **Deny**. A missing Tavily key denies research. Hold never resumes automatically: change to Allow, save, scan again, then review and Run. Every detected signal displays the rule verdict, reason and Python-compatible SHA-256 mandate digest.

No network call occurs on load, scan, settings save, preview or export. Each Run performs one request to one of the two manifest-approved hosts. Provider keys are included only in Authorization headers; preview and trace omit them. Audit-write failures block sending. Response and network failures are surfaced without echoing remote error bodies or keys.

Local raw records are not saved. The extension sends only a minimized signal, with recognizable sensitive patterns scrubbed, generic onboarding markers and day-level times. This is **not anonymization**: a search term or hostname can still be personal. Read every preview. Optional excluded hosts also exclude subdomains. See [PRIVACY.md](PRIVACY.md) and [STORE_LISTING.md](STORE_LISTING.md).

## Tests (Node 22 and the repository Python environment)

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/launzi/Desktop/claude/chat-in-claude/.venv/bin/python extension/tests/export_vectors.py
/usr/bin/node --test --experimental-test-isolation=none extension/tests/*.test.js
PYTHONDONTWRITEBYTECODE=1 /home/launzi/Desktop/claude/chat-in-claude/.venv/bin/python -m pytest browsing -q -p no:cacheprovider
```

Only Node's built-in test runner is used. `--experimental-test-isolation=none` makes individual test totals visible in this execution environment; the default isolated runner here reports file-level totals. All provider calls in tests use injected fake `fetch`. No keys or real browsing profile are needed, and no provider call is made.

The export script reads only the supplied synthetic `browsing/demo-assets/maker-20261003-075151.db`, creates timestamped JSON under `tests/vectors/`, and derives literal prompt constants from `browsing/agent.py` using AST parsing. It does not import the agent runtime or call providers. Tests select the newest vector. Timestamp fields travel as decimal strings, then use BigInt in JavaScript to avoid precision loss above 2^53. The vectors include Python detector, scrub, canonical mandate bytes/digest, and prompt/budget oracles. The script does not read any real Chrome database.

## Browser adapter differences

- Chrome history exposes the current profile's history, which may include synchronized visits. It does not expose Python's `keyword_search_terms` table, visit duration, raw transition flags, or other profiles. The detectors do not use duration/transition/referrer fields, so those fields are not invented.
- Search terms are approximated from URL query parameters for Google `.com`/`.co.kr`, Bing, DuckDuckGo, Naver and YouTube. Other engines and missing/deleted history are not inferred. One search per scrubbed URL/term uses the earliest observed visit in the 90-day scan, matching the database's first-seen approach within the available window. Revisits to the same query URL are not separate search rows.
- Chrome millisecond visit times are converted to Chrome microseconds using BigInt; native sub-millisecond precision is unavailable. Search first-seen time is truncated to seconds as in Python ingestion. Day grouping remains **KST (UTC+9)** to match the existing detector, irrespective of the browser's local time zone.
- Detection uses the latest 30 days; dropped activity has only 90 days of lookback rather than the Python DB's entire history. API result limits trigger time-window subdivision. Saturation at one timestamp, excessive URL count or an API failure aborts the scan explicitly; partial results are not presented as complete.
- Public Python domain rules mark no hosts restricted. The extension's user-entered excluded hosts supply restriction rules. Excluded search-host terms are omitted as an additional browser privacy guard; Python's unresolved detector itself does not filter search records by the search host's sensitivity.
- Python `new_entry` checks the first visit **within the supplied window**, not the first-ever visit across all history. This port preserves that behavior; it does not assert that a website is genuinely new to you.
- The pure detector/scrub/mandate ports are parity-tested. The outbound minimizer deliberately removes more data than Python's query-only URL scrubber. Request bodies therefore differ intentionally from Python's full-signal prompts, while retaining the same system prompts, rubrics, skill templates, tiers and budgets.
- Model selection matches Python: the shortest available model ID containing both `nemotron` and the tier, discovered by an explicitly approved GET. Triage uses **Ultra, 8192 tokens**. Skills use **Nano** with `/no_think`: unresolved **2348**, new_entry/recurring **2248**, dropped **2198**. Null/blank Nemotron content is an error; `finish_reason=length` with blank content has a distinct error. Python currently accepts a nonblank truncated response; this implementation preserves that behavior.
- Python can triage held/denied actions. The extension is more conservative: it gates all requests for those signals before triage. The deterministic mandate verdict/digest is unchanged.

## Source map

`core/history.js` adapts Chrome history; `signals.js`, `scrub.js` and `mandate.js` contain deterministic ports; `agent.js` minimizes signals and builds prompts; `providers.js` is the only network sink; `controller.js` requires a separate Run per stage; `storage.js` manages the bounded local trace. `prompts.js` is readable generated source from Python literals. `popup.js` and `options.js` use DOM text nodes, never provider-supplied HTML.

Trace export uses a Blob and an ordinary download link. Its JSON `records` array corresponds to JSONL events; it contains scrubbed request bodies and outcomes, never provider keys or response bodies. Age pruning occurs on next use, with a 500-record cap and 30-day age limit.

## Release checks still needed

Load unpacked in a clean Chrome profile and validate onboarding, real history API coverage, settings, Run previews and JSON export. Verify actual provider connectivity and model availability only in a separately authorized live smoke check. Replace the privacy contact TODO, publish the policy URL and add store artwork before submission. This MVP does not itself publish to the Web Store.
