# Offline walkthrough

`visits.json` is a hand-authored fictional fixture, not exported browser history
and not an LLM-generated persona. `cache.json` contains precomputed results from
the real agent and mandate pipeline with explicitly scripted fake providers.
The page labels these as `illustrative-fixture`; they do not establish API usage.
The cache includes the SHA-256 of the exact fixture bytes and each applied mandate.
It is never substituted for a different generated dataset or mandate.

The generated deployment bundle is separate: create it with `browsing.persona`
after review, then supply its DB and validation manifest to the container build.
