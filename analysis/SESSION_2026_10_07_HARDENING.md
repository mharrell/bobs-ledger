# Release-channel hardening, 2026-10-07 (detail)

Moved here from CLAUDE.md on 2026-10-09 by the budget rule — the file was at
63.7 KB of the 65.5 KB a session loads, and its own header documents how that
truncates its tail silently. Verbatim below is the 2026-10-07 session's record
as it stood; the still-live pointers remain in CLAUDE.md's short summary of it.

---

Triggered by a security audit of the whole app after a Reddit thread called it a
"security nightmare". The audit's verdict was that most of that was wrong and
one part was right, and the right part is now fixed:

**1. Releases are SIGNED, and an unproven release is never installed.** This was
the real finding. `update.download_zip` checked a zip's sha256 against a manifest
fetched from the same server, so the check proved integrity and nothing about
authorship — a compromised Cloudflare account (or KV namespace, or this laptop,
or the GitHub account's copy of the same zip) could have shipped code to every
install that answered "y".

* `app/ed25519.py` — RFC 8032 Appendix A's implementation, extracted MECHANICALLY
  from the RFC text (no constant retyped by hand), Ed448/SHA-3 dropped.
  `app/tests/rfc8032_vectors.json` holds section 7.1's five vectors, also
  extracted by script; `test_ed25519.py` runs them, and because Ed25519 is
  deterministic a wrong constant fails rather than merely verifying less.
* `app/release_sig.py` — the policy: a pinned `PUBKEY_B64`, a canonical form that
  covers every manifest field except the signature (so `note`, `created`,
  `zip_bytes` and `zip_sha256` are all inside it), `verify_manifest` returning
  (ok, reason) and failing closed on everything unproven, plus keygen/read.
* `update.verified_manifest()` verifies exactly when an update would be OFFERED —
  not on every start, so an up-to-date install is not nagged about a channel it
  cannot act on. **`--force` is not a bypass**: it overrides the direction guess,
  never the identity check. `--check` refuses what the installer refuses.
* `publish_release.py` gained a **signing gate**: no key, no publish; and a key
  the shipped pin does not match is refused too (that mistake would otherwise
  surface one "REFUSING this update" at a time, on players' machines).
  `telemetry/README.md` has the operator's section, including the cost of losing
  the key: one manual reinstall per player, because there is no bypass flag.
* `update.PROTECTED`, `publish_release.EXCLUDE_FILES` and `.gitignore` all refuse
  the key file, the repo's usual three-place rule for local state.

**2. Size caps.** `download_zip` streamed nothing before: `r.read()` took whatever
the server sent into memory, and extraction had no ceiling. Now the SIGNED
`zip_bytes` is the cap (with `MAX_ZIP_BYTES` as the ceiling for a manifest
without one), and `stage_release` refuses more than `MAX_ENTRIES` entries or
`MAX_TOTAL_BYTES` declared bytes before writing anything.

**THE PIN IS SET AND THE CUTOVER RELEASE IS PUBLISHED (2026-10-07).**
`PUBKEY_B64` pins the key with fingerprint `4d8fc45534ba558d`. The private half
is `%USERPROFILE%\.bobs-ledger-release.key` on this machine — 32 raw bytes, ACL'd
to the user, its name guarded in `.gitignore`, `EXCLUDE_FILES` and `PROTECTED` —
and `HEARTH_SIGNING_KEY` points at it. **It is backed up off this machine
(2026-10-07)**, which was the last outstanding action from this session: losing
the only copy costs every player one manual reinstall, because there is no bypass
flag. Verify any copy by re-deriving the public half — `python app\release_sig.py
--pubkey <the copy>` must print `4d8fc45534ba558d`, and anything else is not the
key. Note for whoever reads this next: the "not backed up yet" line was true for
about an hour, and this repo's own rule is that a stale sentence about the state
of things is the same failure as a stale sentence about the code.

Release `91be599` is signed, published to KV and to the GitHub release, and was
verified from the PLAYER's side rather than from the publish log: the live
manifest verifies against the pinned key, the zip's sha256 and byte count match
the manifest, the pin inside the published zip matches this checkout, the
SHIPPED updater run from inside that zip (from a state reading `3233929`) offers
the update and exits 1 — which is only reachable through a successful
verification — and that same shipped code refuses a manifest whose `note` was
rewritten, printing the key fingerprint in the refusal.

Two things that surprise people publishing here, both hit while doing the above:
`Authentication error [code: 10000]` from the Cloudflare API is intermittent —
re-run it (that attempt died on the zip PUT, before the manifest, so the channel
kept serving the old release and nothing was half-published). And KV's eventual
consistency means `latest.json` can still serve the PREVIOUS manifest right after
a successful publish, so "did it work?" needs a minute of retries, not a
re-publish. Both are in `telemetry/README.md`'s gotchas already; they reproduced
exactly as written.

**3. The history scan (2026-10-07).** The audit's other real point: the privacy
gate scans the ZIP, so a value committed once and replaced with a placeholder
later passes every gate and stays in a public repository forever. Two tools now
answer that, and both are documented here because neither is obvious:

    gitleaks git . --log-opts="--all" --redact --no-banner   # credentials
    python app/history_scan.py                               # identities (--json, --full)

`gitleaks` (installed via winget, 8.30.1) found **5 leaks in 479 commits, all
false positives** — `app/tests/rfc8032_vectors.json` holds fields literally
called `secret_key` (RFC 8032's public test vectors), which its generic-api-key
rule reads as "secret" + high entropy. `.gitleaks.toml` allowlists exactly that
rule, path and shape, and extends the default ruleset rather than replacing it,
so tomorrow's real key in that file is still a finding. Rehearsed: clean after,
on both history and the working tree.

`app/history_scan.py` runs `privacy_scan` (the gate's own verifier, never a
second copy of the patterns) over every blob reachable from every ref, one row
per (value, file) with a blob count, masked unless `--full`, and it does not
ship (`EXCLUDE_FILES`). The baseline on 2026-10-07: **19 places, 38 blob
occurrences, 5 still in the working tree** — one session directory each in
`CLAUDE.md`, `PIVOT.md` and `analysis/SETTLE_UP_BOARDS.md`, plus two `user_path`
false positives (`telemetry/README.md`'s own `C:\Users\<you>` example, and
`telemetry/collector.js`'s detector pattern in a comment). All three
session-dir files are maintainer-only, so nothing personal is in a shipped file.

**The one finding that matters is a BattleTag.** It was committed on 2026-10-02
into two SHIPPED test files (`app/tests/test_share.py`,
`app/tests/test_session_privacy.py`) and removed the same day in `91858dc` —
"Docs for what actually happens, and the gate that caught my own fixtures" — so
the gate did its job while the file was live. It is history-only now, and
`https://api.github.com/repos/mharrell/bobs-ledger` answers **200 to an
unauthenticated request: the repository is public.** Getting it out of history
means `git-filter-repo` and a force-push, which rewrites every commit id — and
the commit shas ARE this project's release version strings and the
`VERSION`/manifest version of every published zip. So: decide whether the tag is
the maintainer's own (it looks like it, from the commit that removed it) and
accept it, or rewrite. Recorded rather than decided.

**DECISION (2026-10-07): NO history rewrite.** The one BattleTag is the
maintainer's own — one distinct value in 479 commits, in two test fixtures, and
the commit that took it out is literally "the gate that caught my own fixtures".
The scan puts the rest of the picture beyond doubt: `player_name`,
`player_entity` and `account_id` findings number **zero** across all of history,
and no `"name"` key in any tracked `analysis/` file carries a person. So the tag
is a self-disclosure of a gaming handle, not a credential, and it is not worth
rewriting 479 commit ids — which are this project's release version strings.

**What was actually published is a separate question, and it is clean too.**
git history is not the only thing shipped: `analysis/` went out in early
releases. Every release on the GitHub Releases page (31 of them, from `2a6fb40`
to `91be599`, enumerated through `api.github.com/repos/mharrell/bobs-ledger/
releases?per_page=100`) carries **zero privacy findings and no `analysis/` at
all**. Caveat worth keeping: that is the GitHub list, and an early KV-only
release would not appear in it, so this measures the audit trail rather than
proving nobody ever received a note.

Two scanner bugs the tests caught, both the kind that under-report quietly:
git stores identical content once, so a report built from `rev-list --objects`
names ONE path while the value may sit in several (`_paths_touching` fixes it);
and one commit subject in this repo carries a BOM, which crashed the report
mid-print on a cp1252 console — the same fix and the same reason as
`publish_release.py`'s. Also worth knowing: the gate DOES scan `.py`
(`privacy_scan.TEXT_SUFFIXES`), which was news to me — it refused the first
version of `test_history_scan.py` because a docstring spelled the tag shape out
literally, so that wording changed.

Suite: 1657 green (11 skipped — the pin-coherence test now RUNS rather than
skipping, which is itself the proof the pin is real), and both directions of the
signing gate were rehearsed against a throwaway key — no key refuses, an unpinned
key refuses, a pinned key passes and round-trips a probe manifest.

Still open from the same audit, in the order worth doing them:

1. **~~The loopback control plane has no auth token.~~ CLOSED 2026-10-08.** The
   Host/Origin/JSON guard is browser-shaped and correct for what it defends
   (cross-site requests), but a local process could still `POST /share` to opt the
   player in, and `GET /analysis` (live board plus the opponent's handle). Every
   request now carries a per-run key (`coach_ui.overlay_url`, `_Handler._authorized`)
   — see "Where THIS session left off" above for the four ways an ad-hoc version
   of that was broken while looking finished.
2. **`analysis/` is in a PUBLIC repository** (confirmed 2026-10-07: the GitHub
   API answers 200 to an unauthenticated request; `analysis/` is 41 tracked
   files). After the history scan this is a BUSINESS decision, not a privacy one:
   the folder carries no opponent identity — measured, not assumed — just one
   session directory per file and the maintainer's own research. "Not shipped"
   only ever meant "not in the zip", which is the reviewer's fair point; the
   remaining question is whether the research notes should be public at all, and
   removing them now would not remove them from history anyway.
3. **The `requests` pin is DONE (2026-10-08, `1ef24be` caps it below 3.x)**; the
   maintainer corpus tools
   (`upload_corpus.py`, `fetch_sessions.py`, `scrape_comps.py`,
   `refresh_trinkets.py`, `hearth_art_extract.py`) still ship to players.
