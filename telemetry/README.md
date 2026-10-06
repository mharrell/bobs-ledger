# Telemetry collector (DEPLOYED 2026-10-01)

Bob's Ledger's no-GitHub-account transport for corpus bundles is **live**:
`https://hearth-telemetry-collector.bobs-ledger.workers.dev`
(subdomain `bobs-ledger` — renamed from mharrell-coach the same day by
DELETE + re-PUT of the subdomain; the old URL no longer resolves — KV
contents are unaffected), KV namespace
`abd7803c581b4470a2834e92ae0006a2`, worker `hearth-telemetry-collector`.

A beta user who only INSTALLS needs nothing but the URL — the release zip
is public (`GET /release/<name>.zip`, the install path since 2026-10-02;
the hygiene pass keeps local data out of releases). READING the corpus back is
what needs the shared key; uploading does not (`fetch_sessions.py`'s own line:
"reading is keyed; sending is not"). The key goes in the ENVIRONMENT — nothing
on this side reads a file, and `.dev.vars` is only ever mentioned in
`publish_release.py`'s exclusion list, which is why looking for it on disk
wastes a session:

```
# Windows, this account, for every new shell
setx HEARTH_TELEMETRY_KEY "<the shared key — rotate freely via printf | wrangler secret put>"
# HEARTH_TELEMETRY_URL already defaults to this, so it is only needed elsewhere
# https://hearth-telemetry-collector.bobs-ledger.workers.dev
```

then `python app\fetch_sessions.py --stats` counts what is stored,
`python app\fetch_sessions.py --list` names every key, and
`python app\upload_corpus.py --latest` is a plain HTTPS POST. No GitHub
account, no PAT. Fetch into a directory outside this repo, or check
`.gitignore` first: what comes back is other people's data.

## What a bundle is

`package_corpus.py` produces one gzipped JSON file per session: the
redacted Power.log, that session's decision log, and a manifest (raw-log
sha256, coach version, counts). One session's bundle measured 1.1–1.6 MB.
`package_corpus.py --inspect <bundle>` proves the contents on any bundle.

Two corrections to the old note here, both found on 2026-10-03: BattleTags are
not the only personal data the log writes — Battlegrounds also writes most
opponents as a bare handle with no discriminator, which a BattleTag scan
cannot see — and the DECISION log carries the opponent's handle too, in
`analysis.opp_comp.name`. `sanitize_decisions` strips that by name before the
bundle is built, because `privacy_scan` does not flag it.

## Session reports (consented, from players)

The collector also accepts the coach's distilled session summaries — a
different trade from a corpus bundle: about 16 KB, consented on the welcome
card, and carrying no names by construction.

```
POST /session                          no key — see below
GET  /sessions                         maintainer's key: the listing
GET  /sessions/<date>/<id>.json.gz     maintainer's key: one report
```

`POST /session` is deliberately unauthenticated. The coach ships as a zip
anyone can read, so a secret in the client would not be a secret; what stands
in for one is a 512 KB cap, a shape check (schema + advisories + report_id),
and a coarse net for BattleTag discriminators, local user paths and session
directory names. Reading is keyed, because browsing everyone's sessions is not
something the open internet needs.

**Rate limiting IS implemented, as a Worker binding** — not as a dashboard
rule, and the difference is not cosmetic: WAF rate limiting rules are
**zone-scoped**, and a `workers.dev` hostname is not a zone in this account,
so there is no Security/WAF page for this Worker at all (2026-10-03; the
earlier note here sent the maintainer looking for one).

`deploy/wrangler.toml` defines a `ratelimits` binding (20 requests / 60s) and
collector.js checks it first thing on `POST /session`, before the body is even
read, keyed on the caller's address used purely as a counter key. Verified
live: 45 concurrent requests produced 28 × 429 and 17 accepted. Two properties
worth remembering:

- The limit is **per Cloudflare location**, so it stops one source flooding
  from one place — the case that protects the 1 GB namespace and the 1,000
  writes/day. A distributed attacker gets N × the allowance; it is a throttle,
  not a wall. A genuinely global cap needs a custom domain plus a zone WAF
  rule, or a KV counter, which costs a write per upload.
- It behaves like a **token bucket**, not a fixed window: a sequential hammer
  ~1s apart never trips it, because 20-per-60s refills one token every 3
  seconds. Test it concurrently.

Retrieve reports with `python fetch_sessions.py` (needs
`HEARTH_TELEMETRY_URL` and `HEARTH_TELEMETRY_KEY`); it skips what is already on
disk, and `--list` shows what is there without downloading.

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

- **A publish that reports success is not yet live, and the gap has fooled a
  verification pass.** Measured 2026-10-06, twice in a row: `publish_release.py`
  printed `uploaded release/latest.json` and `published`, and a read of
  `GET /release/latest.json` seconds later still returned the PREVIOUS version —
  its old `created`, its old `zip_bytes` — while a retry ~30 s later returned the
  new one. This is KV's eventual consistency, not a failed upload, and the two
  are indistinguishable from the client side. So: verify against the public URL
  after publishing, RETRY the read before concluding anything failed, and never
  treat the publish log line as proof. The zip is often readable before the
  manifest is (`GET /release/<name>.zip` fetches an object that was never
  overwritten), so the manifest is the one to poll.
- **User-Agent matters**: workers.dev bot filtering 403s the default
  `Python-urllib` UA before the worker runs. `upload_corpus.put_url` sends
  `hearth-coach-telemetry/1.0` — keep a real UA on any new client. (Every
  hand-written verification script needs it too: the first read of the manifest
  in that 2026-10-06 pass died on a bare 403 for exactly this reason.)
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
