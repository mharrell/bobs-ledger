// The coach's telemetry collector: a Cloudflare Worker writing bundles to R2.
//
// Why this exists: upload_corpus.py's GitHub transport needs the user to have
// a GitHub account (gh CLI or a PAT). Beta testers shouldn't need either —
// they get a URL and an optional shared key, and the bundle (one gzipped
// JSON file: BattleTag-redacted Power.log + decision log + manifest) lands
// in an R2 bucket the maintainer reads directly.
//
// Deploy once (telemetry/README.md); rotate TELEMETRY_KEY if the URL leaks.

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("POST a corpus bundle here\n", {status: 405});
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
