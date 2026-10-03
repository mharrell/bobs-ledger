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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET") {
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
          "\nDownload:  https://github.com/mharrell/bobs-ledger/releases/latest\n" +
          "Direct zip: /release/latest.zip\n" +
          "Manifest:   /release/latest.json\n" +
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
        return new Response(zip, {"Content-Type": "application/zip",
                                  "Cache-Control": "no-cache"});
      }
      return new Response("no such release\n", {status: 404});
    }

    if (request.method !== "POST") {
      return new Response("POST a corpus bundle, or GET /release/latest.json\n",
                          {status: 405});
    }
    // The shared key is a throttle, not an identity: it keeps strangers
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
