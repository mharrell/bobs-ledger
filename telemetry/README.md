# Telemetry collector (DEPLOYED 2026-10-01)

Bob's Ledger's no-GitHub-account transport for corpus bundles is **live**:
`https://hearth-telemetry-collector.bobs-ledger.workers.dev`
(subdomain `bobs-ledger` — renamed from mharrell-coach the same day by
DELETE + re-PUT of the subdomain; the old URL no longer resolves — KV
contents are unaffected), KV namespace
`abd7803c581b4470a2834e92ae0006a2`, worker `hearth-telemetry-collector`.

A beta user who only INSTALLS needs nothing but the URL — the release zip
is public (`GET /release/<name>.zip`, the install path since 2026-10-02;
the hygiene pass keeps local data out of releases). UPLOADING a corpus
bundle needs the shared key, i.e. exactly two lines:

```
HEARTH_TELEMETRY_URL=https://hearth-telemetry-collector.bobs-ledger.workers.dev
HEARTH_TELEMETRY_KEY=<the shared key — rotate freely via printf | wrangler secret put>
```

then `python upload_corpus.py --latest` is a plain HTTPS POST. No GitHub
account, no PAT.

## What a bundle is

`package_corpus.py` produces one gzipped JSON file per session: the
BattleTag-redacted Power.log (a ~1M-line privacy scan found BattleTags are
the only personal data Hearthstone writes), that session's decision log,
and a manifest (raw-log sha256, coach version, counts). One session's
bundle measured 1.1–1.6 MB. `package_corpus.py --inspect <bundle>` proves
the contents on any bundle.

## How it was deployed (for redeploys)

1. `npx wrangler login` (browser OAuth).
2. `npx wrangler kv namespace create BUCKET` — KV, not R2: no payment card
   required, and one-session bundles are 1–6 MB (KV value cap 25 MB).
3. The workers.dev SUBDOMAIN must be registered before the first deploy
   (wrangler auto-registers from the folder name and fails); it is also
   doable via `PUT /accounts/<id>/workers/subdomain`. Ours: bobs-ledger.
   RENAMING later is DELETE-then-PUT on that same endpoint (a direct PUT
   409s with "account already has an associated subdomain"); the new
   subdomain's TLS cert takes a minute to provision after the switch.
4. `npx wrangler deploy` with `deploy/wrangler.toml` (KV binding BUCKET).
5. `printf '%s' "$KEY" | npx wrangler secret put TELEMETRY_KEY` — use
   printf, NOT echo: echo's trailing newline is stored with the secret and
   every request 403s (found live, 2026-10-01).

## Gotchas learned on the first live run

- **User-Agent matters**: workers.dev bot filtering 403s the default
  `Python-urllib` UA before the worker runs. `upload_corpus.put_url` sends
  `hearth-coach-telemetry/1.0` — keep a real UA on any new client.
- `npx wrangler kv key list` needs `--remote` to see production (v4
  defaults to local dev storage).

## Reading what came in

`npx wrangler kv key list --namespace-id abd7803c581b4470a2834e92ae0006a2 --remote`,
then `npx wrangler kv key get --namespace-id ... --remote "corpus/<name>"`.
Every object is a complete, self-describing bundle (`--inspect` reads them).

## Alternatives that need no deploy

- `python package_corpus.py <Power.log>` and send the bundle file itself
  (email/Discord — it is one file by design).
- The GitHub transport (the maintainer's own path): `gh` CLI or
  `GH_TELEMETRY_TOKEN`.
