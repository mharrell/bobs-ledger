// The coach's telemetry collector + release server: a Cloudflare Worker on KV.
//
// Two jobs, one deployment:
//   POST /            — ingest a corpus bundle (BattleTag-redacted log +
//                       decision log + manifest) into KV under corpus/.
//   GET  /release/latest.json — the update manifest (version, note, zip
//                       sha256). Public: version info is not sensitive.
//   GET  /release/latest.zip  — 302 to the current release archive, so a
//                       download is ONE clickable URL. The README used to
//                       tell players to fetch latest.json and read
//                       "zip_name" out of it, which is an API instruction
//                       dressed up as a user instruction: the zip name
//                       carries a commit sha nobody can guess.
//   GET  /release/<name>.zip — the release archive. Public: it IS the
//                       install path (the hygiene pass, ee5cd93, keeps
//                       local data out of the zip), and update.py checks
//                       it on every start — a key here would 403 every
//                       fresh install's first update, silently.
//
// The shared key (X-Telemetry-Key) throttles CORPUS INGEST only. Deploy
// once (telemetry/README.md); rotate TELEMETRY_KEY if the URL leaks.

//: A distilled session report is ~16 KB (154 advisories). This is the
//: ceiling a client may send, and the only thing standing between the ingest
//: and a stranger's 25 MiB KV value.
const MAX_REPORT_BYTES = 512 * 1024;

//: A coarse net for the shapes we know to be personal, applied to the
//: DECOMPRESSED text. The real control is the client's whitelist distiller;
//: this catches the case where that client is wrong or old. Deliberately
//: patterns, not a sanitizer: the worker has no business editing data.
const PERSONAL_PATTERNS = [
  /#\d{4,}/,                          // a BattleTag discriminator
  // One or TWO backslashes: the text being searched is JSON, where a path
  // arrives escaped as C:\\Users\\name. The first version of this pattern
  // only matched the unescaped form and a test report carrying
  // C:\Users\Someone\log.txt went straight through (2026-10-03).
  /[A-Za-z]:\\{1,2}Users\\{1,2}/i,    // a local user path
  /Hearthstone_\d{4}_\d{2}_\d{2}/,    // a session directory name
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET") {
      // The maintainer's view of what players have sent. Keyed, unlike the
      // releases: a report is aggregate game data rather than public
      // information, and browsing everyone's sessions is not something the
      // open internet needs. Same secret that throttles corpus ingest.
      if (url.pathname === "/sessions"
          || url.pathname.startsWith("/sessions/")) {
        if (!env.TELEMETRY_KEY
            || request.headers.get("X-Telemetry-Key") !== env.TELEMETRY_KEY) {
          return new Response("bad key\n", {status: 403});
        }
        if (url.pathname === "/sessions") {
          const listing = await env.BUCKET.list({prefix: "sessions/",
                                                 limit: 1000});
          return new Response(JSON.stringify({
            keys: listing.keys.map((k) => k.name),
            truncated: listing.list_complete === false}),
            {headers: {"Content-Type": "application/json",
                       "Cache-Control": "no-cache"}});
        }
        const name = url.pathname.slice("/sessions/".length);
        // Only the shape we write: <date>/<report_id>.json.gz
        if (!/^\d{4}-\d{2}-\d{2}\/[\w-]+\.json\.gz$/.test(name)) {
          return new Response("bad name\n", {status: 400});
        }
        const got = await env.BUCKET.get(`sessions/${name}`,
                                         {type: "arrayBuffer"});
        if (got == null) {
          return new Response("no such report\n", {status: 404});
        }
        return new Response(got, {
          headers: {"Content-Type": "application/gzip",
                    "Cache-Control": "no-cache"}});
      }
      // A bare visit says what this is and offers the download, instead of
      // a 405 aimed at developers. Someone who follows the URL out of
      // curiosity is a user, not an API client.
      if (url.pathname === "/" || url.pathname === "") {
        const manifest = await env.BUCKET.get("release/latest.json");
        let version = null;
        let note = null;
        if (manifest != null) {
          try {
            const m = JSON.parse(manifest);
            version = m.version;
            note = m.note;
          } catch (e) { /* fall through to the plain page */ }
        }
        const line = version
          ? `latest release: ${version}${note ? " — " + note : ""}\n`
          : "no release published yet\n";
        return new Response(
          "Bob's Ledger — a Hearthstone Battlegrounds coach\n\n" +
          line +
          "\nDownload:  /release/latest.zip  (always the current version)\n" +
          "Manifest:  /release/latest.json\n" +
          "\nThis endpoint also accepts corpus uploads (POST, maintainer's key).\n",
          {headers: {"Content-Type": "text/plain; charset=utf-8",
                     "Cache-Control": "no-cache"}});
      }
      const m = url.pathname.match(/^\/release\/([\w.-]+)$/);
      if (!m) {
        return new Response("POST a corpus bundle, or GET /release/latest.json\n",
                            {status: 405});
      }
      const name = m[1];
      if (name === "latest.json") {
        // Public: a version string, a note, and a hash. Nothing personal.
        // KV get returns the VALUE directly (no R2-style .text()).
        const manifest = await env.BUCKET.get("release/latest.json");
        if (manifest == null) return new Response("no release\n",
                                                  {status: 404});
        return new Response(manifest, {
          headers: {"Content-Type": "application/json",
                    "Cache-Control": "no-cache"},
        });
      }
      if (name === "latest.zip") {
        const manifest = await env.BUCKET.get("release/latest.json");
        if (manifest == null) return new Response("no release\n",
                                                  {status: 404});
        let zipName = null;
        try {
          zipName = JSON.parse(manifest).zip_name;
        } catch (e) { /* malformed manifest: fall through to the 404 */ }
        if (!zipName) return new Response("no release\n", {status: 404});
        // Relative Location, so it is right on any hostname.
        return new Response(null, {
          status: 302,
          headers: {"Location": `/release/${zipName}`,
                    "Cache-Control": "no-cache"},
        });
      }
      if (name.endsWith(".zip")) {
        // The release archive: public — it is the install path (see the
        // header). Binary: KV must be read as an arrayBuffer (default
        // text mangles bytes).
        const zip = await env.BUCKET.get(`release/${name}`,
                                         {type: "arrayBuffer"});
        if (zip == null) return new Response("no such release\n",
                                             {status: 404});
        // Content-Disposition decides the filename the browser saves, and
        // therefore the folder Windows offers to extract. The versioned name
        // ("bobs-ledger-<sha>.zip") made a player's folder look like build
        // output; the ROUTE keeps that name because the manifest points at it
        // and update.py downloads by that path — only the display name
        // changes (2026-10-03).
        //
        // `headers:` is load-bearing. This response was written as
        // `new Response(zip, {"Content-Type": ..., "Cache-Control": ...})`,
        // which sets NOTHING: ResponseInit has no Content-Type property, so
        // both were silently dropped and the release downloaded as whatever
        // the URL said. Whoever next adds a header here, put it inside the
        // wrapper. (The other three responses in this file already do.)
        return new Response(zip, {
          headers: {
            "Content-Type": "application/zip",
            // Both forms: plain for everything in practice, RFC 5987 for a
            // client that wants it percent-encoded.
            "Content-Disposition":
              "attachment; filename=\"Bob's Ledger.zip\"; "
              + "filename*=UTF-8''Bob%27s%20Ledger.zip",
            "Cache-Control": "no-cache"}});
      }
      return new Response("no such release\n", {status: 404});
    }

    // A player's anonymized session report. NO KEY, deliberately: the coach
    // ships as a zip anyone can read, so a secret in the client is not a
    // secret. What stands in for one is that the payload is small,
    // self-describing and - by construction on the client - carries no
    // identities: the distiller emits only fields it names, and refuses to
    // send a report its own verifier rejects.
    //
    // This handler still does not take that on trust. It caps the size,
    // refuses anything that is not one of our reports, and greps the text for
    // the shapes we know are personal.
    //
    // Not implemented here: rate limiting. That belongs to Cloudflare's rate
    // limiting rules (see telemetry/README.md) - a Worker is stateless and
    // KV writes are too scarce to spend counting writes.
    if (request.method === "POST" && url.pathname === "/session") {
      // Refuse an oversized body from its declared length, before reading it.
      const declared = Number(request.headers.get("Content-Length") || 0);
      if (declared > MAX_REPORT_BYTES) {
        return new Response("not a session report\n", {status: 413});
      }
      const body = await request.arrayBuffer();
      if (body.byteLength > MAX_REPORT_BYTES) {
        return new Response("not a session report\n", {status: 413});
      }
      // Too small is a malformed report, not an oversized one: the first
      // version answered 413 to a 64-byte body, which sends whoever is
      // debugging it looking for a size problem that is not there.
      if (body.byteLength < 64) {
        return new Response("not a session report\n", {status: 400});
      }
      let text = null;
      try {
        const stream = new Response(body).body
          .pipeThrough(new DecompressionStream("gzip"));
        text = await new Response(stream).text();
      } catch (e) {
        return new Response("not a session report\n", {status: 400});
      }
      let manifest = null;
      try {
        const obj = JSON.parse(text);
        if (obj.schema === 1 && Array.isArray(obj.advisories)
            && obj.manifest && typeof obj.manifest.report_id === "string") {
          manifest = obj.manifest;
        }
      } catch (e) { /* falls through to the 400 below */ }
      if (manifest === null) {
        return new Response("not a session report\n", {status: 400});
      }
      if (PERSONAL_PATTERNS.some((re) => re.test(text))) {
        return new Response("report carries personal data\n", {status: 400});
      }
      const day = new Date().toISOString().slice(0, 10);
      await env.BUCKET.put(`sessions/${day}/${manifest.report_id}.json.gz`,
                           body);
      return new Response("stored\n");
    }

    if (request.method !== "POST") {
      return new Response("POST a corpus bundle, or GET /release/latest.json\n",
                          {status: 405});
    }    // The shared key is a throttle, not an identity: it keeps strangers
    // from writing to the bucket if the URL circulates. Optional to set.
    if (env.TELEMETRY_KEY
        && request.headers.get("X-Telemetry-Key") !== env.TELEMETRY_KEY) {
      return new Response("bad key\n", {status: 403});
    }
    const name = (request.headers.get("X-Bundle-Name")
                  || `bundle-${Date.now()}.json.gz`)
      .replace(/[^\w.\-]/g, "_");
    const body = await request.arrayBuffer();
    if (body.byteLength < 32 || body.byteLength > 64 * 1024 * 1024) {
      return new Response("not a corpus bundle\n", {status: 413});
    }
    await env.BUCKET.put(`corpus/${name}`, body);
    return new Response(`stored corpus/${name} (${body.byteLength} bytes)\n`);
  },
};
