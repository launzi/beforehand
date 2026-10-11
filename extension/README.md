# beforehand

Chrome MV3 extension showing the Korea delivered price or Korean alternatives for the current product on 22 supported shops. Plain JavaScript modules; no AI keys or build dependencies.

```sh
cd extension
npm test
node scripts/build.mjs store
```

Load `dist/store` unpacked in Chrome 116 or later. The build also creates a timestamped `dist/beforehand-store-*.zip`; the system `zip` command is required.

Only `core/sink.js` performs network requests, exclusively to Korea Concierge. Tests inject fake fetch functions and contract fixtures; they do not call a live API. Consent, settings, cache, per-day limits and checkout orchestration live in `background.js` and `core/storage.js`. Classic content scripts use `BeforehandExtract` and `BeforehandCard` globals. All prices are quote-engine output; page prices remain local.

Approved v4 text is in `core/disclosure.js` and `drafts/consent.v4.md`. Do not change it without renewed approval. See `PRIVACY.md` for current processing and controls, and `STORE_LISTING.md` for submission copy.

Real-shop extraction, Chrome extension lifecycle, live KC responses and Stripe handoff require the release owner's browser E2E check. Do not treat mocked tests as those checks. No automated test makes a purchase.
