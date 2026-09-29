# Telemetry collector (optional)

The no-Github-account transport for corpus bundles. A beta user needs
exactly two things: the collector **URL** and (optionally) the shared
**key**. You need a one-time Cloudflare deploy.

## What a bundle is

`package_corpus.py` produces one gzipped JSON file per session: the
BattleTag-redacted Power.log (a ~1M-line privacy scan found BattleTags are
the only personal data Hearthstone writes), the session's decision log, and
a manifest (raw-log sha256, coach version, counts). Nothing else is in it —
`package_corpus.py --inspect <bundle>` proves that on any bundle.

## Deploy (maintainer, once)

1. `npm create cloudflare@latest telemetry-worker` (or `npx wrangler init`)
   and copy `collector.js` in as the worker's main module.
2. Create an R2 bucket (`npx wrangler r2 bucket create hearth-telemetry`)
   and bind it as `BUCKET` in `wrangler.toml`:
   ```toml
   name = "telemetry-collector"
   main = "collector.js"
   compatibility_date = "2026-09-01"
   [[r2_buckets]]
   binding = "BUCKET"
   bucket_name = "hearth-telemetry"
   ```
3. `npx wrangler secret put TELEMETRY_KEY` (a long random string).
4. `npx wrangler deploy` — note the `*.workers.dev` URL.

Free tier is ample: bundles are a few MB, one per play session.

## Hand to a beta user

Two lines for their environment (or bake into a `.env` note):

```
HEARTH_TELEMETRY_URL=https://telemetry-collector.<you>.workers.dev
HEARTH_TELEMETRY_KEY=<the key from step 3>
```

Then sharing a session is:

```
python upload_corpus.py --latest
```

No GitHub account, no PAT — a plain HTTPS POST.

## Reading what came in

`npx wrangler r2 object get hearth-telemetry/corpus/<name>.json.gz`, or
browse the bucket in the dashboard. Every object is a complete,
self-describing bundle (`--inspect` reads them too).

## Alternatives that need no deploy

- `python package_corpus.py <Power.log>` and send the bundle file itself
  (email/Discord — it is one file by design).
- The GitHub transport (the maintainer's own path): `gh` CLI or
  `GH_TELEMETRY_TOKEN`.
