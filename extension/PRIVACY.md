# Beforehand: Privacy Policy

Publisher: **Munteok**, an individual developer in the Republic of Korea · Contact: **privacy@munteok.com**
Policy version 3 (matches in-extension disclosure version 3) · Effective: {{EFFECTIVE_DATE}}

## Summary

Beforehand reads your Chrome history **on your device** to suggest useful next steps. Only approved research and quote requests (scrubbed search terms, product names and destination countries) pass through Korea Concierge, a server operated by Munteok. Munteok does not receive your browsing history itself.

Data leaves your device in one situation only. When you press **Run this request**, a minimized request goes to a service you have chosen. Before that request is sent, the extension shows you its exact body and destination. Nothing runs in the background, and nothing is read until you agree on the first-use screen.

## 1. Single purpose

The extension turns patterns in your own browsing history into optional suggestions. It looks for:

- new setup activity
- searches with limited follow-through
- repeated visits
- activity that has gone quiet
- repeated views of a Korean product page without an observed purchase page

Every use of data in this policy serves that one purpose. The patterns are clues, and the extension does not treat them as conclusions about your intentions.

## 2. Consent comes first

Before any history read or external call, the extension asks for an explicit **I agree** to the current disclosure, version 3. The accepted version is stored in `chrome.storage.local`. If the disclosure changes, you are asked again.

You can withdraw consent at any time. Withdrawing deletes all extension storage, including keys, settings, consent and trace, and any response that arrives after deletion is discarded. Withdrawing does not delete Chrome's own history or records already held by a provider.

## 3. What the extension reads

The extension reads only after you agree and press **Scan local history**. It reads, through Chrome's history API, for up to the last 90 days:

- website addresses
- visit times
- product-page titles

From these, it derives supported search-engine query terms locally.

It does not access page contents, cookies, passwords saved in Chrome, downloads, or other Chrome profiles. Chrome may return history synchronized into the current profile; the extension does not access other devices on its own. Websites you exclude in Settings, and their subdomains, are left out of detection.

## 4. What leaves your device, and only when you press Run

Raw history records are never uploaded. Each stage of a suggestion needs its own preview and its own Run.

| Recipient | What is sent | When |
|---|---|---|
| **Your selected AI provider**: OpenAI (`api.openai.com`) or Anthropic (`api.anthropic.com`) in the store build; Nebius Token Factory (`api.tokenfactory.nebius.com`) in the hackathon build | Model discovery: no history. Triage and suggestions: instructions plus a minimized signal: a hostname or scrubbed search term, aggregate counts, dates rounded to whole days, and generic path markers such as `/signup`. Research suggestions may add selected, scrubbed search-result titles, URLs without query strings, and snippets. | Each Run you approve |
| **Korea Concierge** (`concierge.youngji.kim`), optional research | A scrubbed search query. Korea Concierge (operated by Munteok) searches through Tavily and returns result titles, URLs and snippets. Research queries are not logged or stored. For each call, Korea Concierge records only the tool name, success or failure, error code, duration and time. To limit abuse, it also counts requests per 10 minutes under a hashed form of your IP address; these counters are deleted after 24 hours. | Only when your mandate allows research and you approve Run; no Tavily key is required from you |
| **Korea Concierge** (`concierge.youngji.kim`) | A scrubbed product name and your chosen delivery country (US by default). No product URL, no visit time. | Only for a Korean product signal, when your mandate allows quotes |

Only your selected AI provider receives the one AI API key you entered, in an authentication header. Korea Concierge needs no key from you; it manages Tavily access on its server. The AI provider and Korea Concierge receive ordinary connection information, including your IP address, when contacted. Keys are hidden in previews and never written to the trace.

**Scrubbing is not anonymization.** It removes recognizable credentials, email addresses, long identifiers, phone-like numbers and embedded URLs. Model requests also leave out raw history URLs, unsanitized titles, profile and visit IDs, path identifiers, exact visit times and signal hashes. A hostname or search term can still reveal personal interests, names, or health or financial matters. Review each request, and cancel anything you do not want to share.

### Providers act under your own accounts

Your selected AI provider processes requests under your account agreement with it: OpenAI or Anthropic in the store build, or Nebius Token Factory in the hackathon build. Tavily is used by Korea Concierge for research; you do not need a Tavily account or key.

- **OpenAI**: see the [OpenAI privacy policy](https://openai.com/policies/privacy-policy/).
- **Anthropic**: see the [Anthropic privacy policy](https://www.anthropic.com/legal/privacy).

- **Nebius Token Factory** may, by default, keep prompts and outputs to speed up inference (speculative decoding). Nebius says these are stored in the EU and not used for training. If you enable **Zero Data Retention** in your Nebius account, Nebius says it keeps no copy after each request. We recommend enabling it. See the [Nebius Token Factory legal guide](https://docs.tokenfactory.nebius.com/legal/legal-quick-guide) and the [Nebius privacy policy](https://docs.nebius.com/legal/privacy).
- **Tavily**: see the [Tavily privacy policy](https://tavily.com/privacy).

Munteok does not control provider-side retention and makes no claim about it. Ask the provider directly to delete data it holds.

### Korea product quotes and a conflict of interest

**Korea Concierge is operated by the developer of this extension (Munteok).** Quotes are free. A service fee is included only if you choose to buy through Korea Concierge.

- This extension cannot place orders. No checkout, order creation or payment is implemented.
- Quote tokens and next-step instructions from the service are discarded, never stored, displayed or forwarded.
- Costs are shown exactly as the service returns them, including duty sources, warnings and the local price.
- When buying locally is cheaper, the quote card says so first.
- Selected quote facts may then go to your selected AI provider for a separately previewed English explanation.
- Quotes are estimates and do not commit you to buy anything.

## 5. What is stored on your device

| Item | Where | Kept for |
|---|---|---|
| Scan results and detected signals | Memory of the open extension page | Until you close that page or rescan |
| AI output, quote cards, research results | Memory of the open extension page | Until you close that page |
| One selected AI provider key, mandate, excluded websites, quote destination, consent | `chrome.storage.local` (never `chrome.storage.sync`) | Until you delete them, withdraw consent, or uninstall |
| Audit trace: approved scrubbed request bodies, destinations, mandate digests, signal hashes, timestamps, stages, outcomes | `chrome.storage.local` | Newest 500 records, up to 30 days, pruned the next time you open the extension |

Keys are stored **without additional encryption** beyond Chrome's own storage. The trace never contains API keys, Authorization headers, raw history records or provider response bodies.

If you export the trace to a JSON file, that file stays wherever you save it until you delete it. It holds the requests you approved and may still be sensitive.

## 6. What we do not do

- Munteok does not receive your browsing history itself. Only approved research and quote requests (scrubbed search terms, product names and destination countries) pass through its Korea Concierge server. Research queries are not logged or stored. For each call, Korea Concierge records only the tool name, success or failure, error code, duration and time. To limit abuse, it also counts requests per 10 minutes under a hashed form of your IP address; these counters are deleted after 24 hours.
- No analytics, telemetry, crash reporting or advertising SDKs.
- No sale or transfer of your data, and no use for advertising, for creditworthiness or lending, or for any purpose other than the single purpose above.
- No person reads your data.
- No remote code.

**The use of information received from Google APIs will adhere to the Chrome Web Store User Data Policy, including the Limited Use requirements.**

## 7. Automated suggestions

Suggestions come from rules on your device plus AI model output. They have no legal or similarly significant effect on you. The allow, hold or deny decision is deterministic, and it is recorded in your local trace so you can inspect it.

## 8. Your choices and rights

- **Settings**: change what your mandate allows, exclude websites, delete the trace, or delete all keys, settings and trace.
- **Uninstall**: Chrome removes the extension's local storage.
- These actions do not delete Chrome's own history, files you exported, or data a provider already received. A request that has already been sent cannot be recalled.
- Research queries are not logged or stored. For each call, Korea Concierge records only the tool name, success or failure, error code, duration and time. To limit abuse, it also counts requests per 10 minutes under a hashed form of your IP address; these counters are deleted after 24 hours. For requests sent under your AI provider account, contact OpenAI, Anthropic or Nebius as applicable; for Korea Concierge processing, contact Munteok.
- For questions or complaints, write to **privacy@munteok.com**. You may also contact your local data protection authority. In Korea, this is the Personal Information Protection Commission ([pipc.go.kr](https://www.pipc.go.kr)).

## 9. Children

The extension is not directed at children under 14.

## 10. Open source

The full source code is published under the Apache License 2.0 at {{REPO_URL}}, so anyone can check these statements against the code.

## 11. Changes

If what the extension reads or sends changes, we update this policy and the in-extension disclosure version. The extension then asks for your agreement again before it reads or sends anything.

| Date | Change |
|---|---|
| {{EFFECTIVE_DATE}} | First published version |
