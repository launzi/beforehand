# Chrome Web Store listing draft

**Name:** Before You Ask  
**Version:** 0.1.0  
**Publisher:** Munteok  
**License:** Apache-2.0  
**Price:** Free extension; bring your own Nebius Token Factory API key. Provider usage charges may apply.

## Short description

Turn local browsing patterns into useful next steps. Review every outgoing request before you run it.

## Detailed description

Find a useful next step in the browsing you have already done.

Before You Ask reads recent Chrome history locally, on demand, to surface four kinds of clues: new setup activity, searches with little follow-through, repeated visits, and activity that has gone quiet. It can suggest a setup check, a focused research briefing, a short synthesis, or a gentle next step to resume something.

**Your browsing history is essential to this feature.** The extension reads website addresses and visit times for up to 90 days only after you accept its disclosure and press Scan. It does not read page contents or run background scans. These patterns do not prove that a task is unfinished or that you need to act.

**Raw history stays on your device.** AI suggestions are optional. “What leaves your device” shows the exact outgoing request body and destination before every Run click. Nebius Token Factory receives a minimized, scrubbed signal: a hostname or search term, aggregate counts, day-level dates and generic setup markers. Full history URLs, titles, identifiers and exact visit times are excluded. Scrubbing is imperfect, so review the request and cancel anything private.

Optional research sends a scrubbed query to Tavily. Search results require another preview before selected titles, URLs and snippets go to Nebius. Without a Tavily key, research is denied; the other skills remain available. Every signal shows its allow, hold or deny verdict, reason, and mandate SHA-256 digest. Run never overrides a held or denied action.

Keys and settings stay in local extension storage. You can exclude websites, delete local data, and export the local audit log as JSON to see what was sent. No sale, advertising, analytics, automatic external calls, or remote code.

Getting started: accept the disclosure, configure your Nebius key in Settings, scan locally, select a signal, and review each request before pressing Run. Keep the extension page open during requests; Open in a tab provides a larger workspace.

Published by Munteok. Free and open source under Apache-2.0. Own provider accounts are required for AI features and their usage charges may apply. Suggestions may be inaccurate; you decide what to do next.

## Single purpose

Help the user turn locally detected browsing patterns into optional, evidence-grounded next-step suggestions, with explicit review and permission before each external AI or research request.

## Permission justifications

| Permission | Why it is necessary |
| --- | --- |
| `history` | On an explicit local scan, read website addresses, visit times and product-page titles to detect the four existing browsing patterns and repeated Korean product views. No history mutation is performed. |
| `storage` | Store user-entered provider keys, the search mandate, excluded hosts, versioned first-use consent and quote destination and a bounded local audit log. Only `chrome.storage.local` is used. |
| `https://api.tokenfactory.nebius.com/*` | After Run, discover available Nemotron models and send the exact reviewed, minimized triage or suggestion request to the user's Nebius account. |
| `https://concierge.youngji.kim/*` | After Run and quote mandate approval, send only the scrubbed product name and destination for a free cost estimate. No order or payment is created. |
| `https://api.tavily.com/*` | After Run and only when the mandate allows research and a key exists, send the reviewed scrubbed query for a research briefing. |

No `alarms`, `tabs`, `downloads`, content-script, browsing-page host access or wildcard-host permission is required. A local Blob download exports traces without the downloads API.

## Data usage answers — draft for publisher review

Korea Concierge is a Munteok-operated service receiving approved quote requests. **User-approved provider processing counts as data handling**. Do not select “no data collected” merely because processing begins locally. Confirm the current dashboard's field wording before submitting.

| Data category | Draft answer and scope |
| --- | --- |
| Web history | **Yes.** History addresses/times are processed locally; only reviewed derived signals may be sent to the three named services. |
| Authentication information | **Yes.** User-entered API keys are stored locally and sent only to their respective provider for authentication. No Chrome passwords or cookies are read. |
| Personally identifiable information | **Potentially yes.** Terms and hostnames may retain names or other identifying text even after scrubbing. Review with the publisher; do not claim guaranteed anonymization. |
| Health / financial information | Not deliberately requested or inferred, but user-approved query text can contain these subjects. Final disclosure must account for this possibility; redaction is not a semantic sensitivity classifier. |
| Location | No location permission or precise-location collection. The selected destination country is sent for a quote. Providers receive network IP information; an approved query may include a location. |
| Personal communications | No email/chat content access. No content scripts or page-body reading. |
| User activity | Visits are used as browsing signals. No keystroke, click, mouse or screen monitoring. |
| Website content | No visited-page bodies or images are sent. Scrubbed product names derived from history titles are sent only for the requested quote feature. Optional third-party search snippets are processed for the requested research feature. |

Required certifications, if the released package continues to match this implementation:

- Data is not sold or transferred outside the allowed user-facing feature, including its necessary third-party processing.
- Data is not used or transferred for purposes unrelated to the single purpose.
- Data is not used or transferred to determine creditworthiness or for lending purposes.
- No remote code: all executable code ships as readable local ES modules, without dependencies, bundling, minification, eval or CDN scripts.

## Before publication

Privacy contact: privacy@munteok.com. Host a public privacy-policy URL; provide support and source-code URLs; add store icons, screenshots and promotional assets; confirm data-category answers against the live dashboard; perform unpacked Chrome and provider-account smoke checks; review provider terms. This draft is not a store submission or a guarantee of review approval.


## Korea quote permission and disclosure

`https://concierge.youngji.kim/*`: access to the quote-only MCP endpoint. Sends only the scrubbed product name and selected destination in tool arguments, never browsing URLs or visit times. No authentication, checkout, order or payment action. Quote tokens are discarded. The exact JSON-RPC request is previewed before Run. Estimated cost cards include fees, duty source text, local price comparison, warnings and service verdict; buy_local is honestly surfaced first.

Korea Concierge is operated by the developer of this extension (Munteok). Quotes are free; a service fee is included only if you choose to buy through it.

First-use prominent disclosure requires **I agree** before history reads or any provider calls. Accepted disclosure version 2 is stored locally; a version increase prompts again. **Withdraw consent and delete all local data** clears keys, trace, settings and consent. No pre-consent network traffic. Contact: privacy@munteok.com.
