/**
 * Free AI image generator for the pipeline — runs on Cloudflare Workers AI.
 *
 * Request  (POST JSON): { "prompt": "...", "width": 1024, "height": 1792 }
 * Response (200 JSON) : { "image_base64": "<base64 JPEG/PNG>" }
 *
 * Optional protection: set a secret named ACCESS_KEY on the worker, then put
 * the URL in config.yaml as  https://<name>.<you>.workers.dev/?key=<ACCESS_KEY>
 *
 * Errors are returned as non-200 with Cloudflare's original message so the
 * pipeline can spot "4006" (daily free quota used) and skip this worker.
 */
const DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell";

function toBase64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return Response.json({ ok: true, usage: "POST {prompt,width,height}" });
    }
    if (env.ACCESS_KEY && new URL(request.url).searchParams.get("key") !== env.ACCESS_KEY) {
      return Response.json({ error: "unauthorized" }, { status: 401 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return Response.json({ error: "body must be JSON" }, { status: 400 });
    }
    const prompt = String(body.prompt || "").slice(0, 2048);
    if (!prompt) return Response.json({ error: "prompt is required" }, { status: 400 });

    const model = env.MODEL || DEFAULT_MODEL;
    const input = model.includes("flux-1-schnell")
      ? { prompt, steps: 8 } // schnell: fixed 1024x1024, the pipeline crops to 9:16
      : { prompt, width: body.width || 1024, height: body.height || 1792 };

    try {
      const out = await env.AI.run(model, input);
      let image_base64;
      if (out && typeof out.image === "string") {
        image_base64 = out.image; // flux-1-schnell returns base64 already
      } else {
        // SDXL-style models return a binary PNG stream
        image_base64 = toBase64(new Uint8Array(await new Response(out).arrayBuffer()));
      }
      return Response.json({ image_base64 });
    } catch (err) {
      return Response.json({ error: String(err && err.message ? err.message : err) }, { status: 500 });
    }
  },
};
