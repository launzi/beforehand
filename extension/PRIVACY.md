# Before You Ask — Privacy Policy (draft)

Publisher: **Munteok**. Version: 0.1.0. Contact: **TODO** (replace before publication).

Before You Ask turns patterns in your local browsing history into optional, useful next-step suggestions. The extension is free and licensed under Apache-2.0. You supply your own provider accounts; their charges may apply.

## What we read and why

After you accept the first-use disclosure and press **Scan local history**, the extension reads website addresses and visit times from Chrome's history API for up to the last 90 days. It derives supported search-engine query terms locally. It looks for new setup activity, searches with limited follow-through, repeated visits, and activity that has gone quiet. These are clues, not conclusions about your intentions.

The extension does not access page contents, cookies, passwords saved in Chrome, downloads, or other Chrome profiles. It does not scan in the background. Chrome may return history synchronized into the current profile; the extension does not independently access other devices.

## What leaves your device

Raw history records are never uploaded. Before **every** external request, the “What leaves your device” panel shows the exact request body and destination. Only pressing **Run this request** sends that request. Each following stage requires a new preview and Run click.

- **Nebius Token Factory** (`https://api.tokenfactory.nebius.com/v1/models` and `/v1/chat/completions`): model discovery sends no history. Triage and suggestion requests send instructions plus a minimized signal: a hostname or scrubbed search term, aggregate activity counts, dates rounded to whole days, and generic onboarding path markers such as `/signup`. Research suggestions may also send selected, scrubbed Tavily result titles, URLs with query strings and fragments removed, and snippets.
- **Tavily** (`https://api.tavily.com/search`): optional research sends only a scrubbed search query and a result-count limit. Research is denied without a Tavily key or when the search mandate forbids it. A held mandate must be changed to Allow before research can run.
- Each provider receives its own API key in an Authorization header and ordinary connection information, including your IP address. Keys are hidden in previews and never written to traces. There are no Munteok servers in this data path.

Scrubbing removes recognizable credentials, email addresses, long identifiers, phone-like numbers and embedded URLs from outgoing free text. It also removes raw history URLs, page titles, profile and visit IDs, path identifiers, exact visit times and stable signal hashes from model requests. **Scrubbing is not a guarantee of anonymity.** A hostname or search term can still reveal personal interests, names, health or financial matters. Review each request and cancel anything you do not want to share. Excluded websites and their subdomains are omitted from signal detection and search-term extraction.

## Local storage and retention

- Raw scan records and detected signals exist only in the current extension page's memory. Closing that page discards them. Scanning again replaces the previous results.
- Nebius/Tavily keys, your mandate, excluded websites and onboarding acknowledgement are stored only in **chrome.storage.local**, never chrome.storage.sync. The extension does not add encryption to Chrome's local storage.
- A local audit log records approved scrubbed request bodies, destinations, mandate digests, local signal hashes, timestamps, stages and outcomes. It never stores API keys, Authorization headers, raw history records or provider response bodies. It retains the newest **500 records**, for up to **30 days**. Age-based cleanup happens when the extension is next opened or used; no background timer runs while it is closed.
- AI output and research hits remain in the active page's memory. They are not saved as a conversation history.
- Exported JSON trace files remain wherever you download them until you delete those files yourself. They contain the minimized requests you approved and may still be sensitive.

## Your controls and deletion

Use Settings to change search permission, exclude websites, delete the local trace, or delete all extension keys, settings and trace. Deleting all local data also resets the first-use acknowledgement. Uninstalling removes the extension's local storage. These actions do not delete Chrome's own history, exported files, or data already received by providers. A request already sent cannot be recalled by closing the page or deleting settings.

Nebius Token Factory and Tavily process requests under your respective account agreements and privacy terms. Their retention and deletion practices are provider-controlled and may differ from local retention above. Munteok does not claim a provider-side zero-retention period. Contact the relevant provider to request deletion of provider-side data.

## No sale, advertising or unrelated use

Munteok does not sell browsing data, use it for advertising, transmit analytics, or build advertising profiles. Data is used only to provide the user-visible browsing-signal and next-step suggestion feature. There is no remote code, telemetry, or third-party analytics SDK.

The use of information received from Google APIs will adhere to the Chrome Web Store User Data Policy, including the Limited Use requirements.

This is a publication draft. Replace the contact TODO, publish an accessible policy URL, and review the final store disclosures before release.
