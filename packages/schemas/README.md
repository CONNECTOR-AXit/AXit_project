# Generated API schemas

These files are generated from `apps/api/app/contracts.py` by
`tools/generate_contracts.py`. Do not hand edit them; run the generator and
then verify freshness with:

```text
python tools/generate_contracts.py --check
```

They intentionally expose runtime UUID identities only. Development fixture
aliases, storage keys, raw originals, parser credentials, and lease tokens are
not part of this public contract.
