// Netlify Serverless Function: Resolve stream direto (MP4 / MP3) para YouTube, TikTok, Instagram, X, etc.

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json; charset=utf-8",
};

function extractYouTubeId(url) {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) {
      return u.pathname.slice(1).split("/")[0];
    }
    if (u.searchParams.get("v")) {
      return u.searchParams.get("v");
    }
    const shortsMatch = u.pathname.match(/\/(shorts|embed|live)\/([^/?&]+)/);
    if (shortsMatch) return shortsMatch[2];
  } catch (_) {}
  return null;
}

async function fetchWithTimeout(resource, options = {}, timeout = 6000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(resource, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(id);
    return response;
  } catch (err) {
    clearTimeout(id);
    throw err;
  }
}

export async function handler(event) {
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 200, headers: CORS_HEADERS, body: "" };
  }

  try {
    const body = event.body ? JSON.parse(event.body) : event.queryStringParameters || {};
    const targetUrl = (body.url || "").trim();
    const mode = body.mode || "video"; // "video" | "audio"
    const quality = body.quality || "1080"; // "2160", "1080", "720", "480"

    if (!targetUrl) {
      return {
        statusCode: 400,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "URL obrigatória." }),
      };
    }

    const ytId = extractYouTubeId(targetUrl);

    // 1. TikTok Direct Resolver via TikWM
    if (targetUrl.toLowerCase().includes("tiktok.com")) {
      try {
        const tikRes = await fetchWithTimeout(
          `https://www.tikwm.com/api/?url=${encodeURIComponent(targetUrl)}`,
          {},
          5500
        );
        const tikJson = await tikRes.json();
        if (tikJson && tikJson.data) {
          const d = tikJson.data;
          const downloadUrl = mode === "audio" ? d.music : d.hdplay || d.play;
          if (downloadUrl) {
            return {
              statusCode: 200,
              headers: CORS_HEADERS,
              body: JSON.stringify({
                status: "stream",
                downloadUrl,
                filename: `${(d.title || "tiktok_video").slice(0, 60)}.${
                  mode === "audio" ? "mp3" : "mp4"
                }`,
                provider: "TikWM Direct",
              }),
            };
          }
        }
      } catch (_) {}
    }

    // 2. YouTube Direct Stream via Piped / Invidious Instances
    if (ytId) {
      const pipedInstances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.moomoo.me",
        "https://api-piped.mha.fi",
      ];

      for (const base of pipedInstances) {
        try {
          const r = await fetchWithTimeout(`${base}/streams/${ytId}`, {}, 4200);
          if (!r.ok) continue;
          const data = await r.json();

          if (mode === "audio" && Array.isArray(data.audioStreams) && data.audioStreams.length > 0) {
            const sortedAudio = [...data.audioStreams].sort(
              (a, b) => (b.bitrate || 0) - (a.bitrate || 0)
            );
            const bestAudio = sortedAudio[0];
            if (bestAudio && bestAudio.url) {
              return {
                statusCode: 200,
                headers: CORS_HEADERS,
                body: JSON.stringify({
                  status: "stream",
                  downloadUrl: bestAudio.url,
                  filename: `${(data.title || ytId).slice(0, 80)}.mp3`,
                  provider: "Piped Stream",
                }),
              };
            }
          }

          if (mode !== "audio" && Array.isArray(data.videoStreams) && data.videoStreams.length > 0) {
            // Procura streams que já possuem áudio integrado (videoOnly === false)
            const muxed = data.videoStreams.filter((s) => s.videoOnly === false && s.url);
            const pool = muxed.length > 0 ? muxed : data.videoStreams.filter((s) => s.url);
            if (pool.length > 0) {
              const chosen =
                pool.find((s) => (s.quality || "").includes(quality)) || pool[0];
              return {
                statusCode: 200,
                headers: CORS_HEADERS,
                body: JSON.stringify({
                  status: "stream",
                  downloadUrl: chosen.url,
                  filename: `${(data.title || ytId).slice(0, 80)}.mp4`,
                  provider: "Piped Stream",
                }),
              };
            }
          }
        } catch (_) {}
      }

      // Invidious fallback
      const invidiousInstances = [
        "https://inv.tux.pizza",
        "https://invidious.nerdvpn.de",
        "https://invidious.jing.rocks",
      ];

      for (const base of invidiousInstances) {
        try {
          const r = await fetchWithTimeout(`${base}/api/v1/videos/${ytId}`, {}, 4000);
          if (!r.ok) continue;
          const data = await r.json();
          if (mode === "audio" && Array.isArray(data.adaptiveFormats)) {
            const audios = data.adaptiveFormats.filter((f) =>
              (f.type || "").startsWith("audio/")
            );
            if (audios.length > 0 && audios[0].url) {
              return {
                statusCode: 200,
                headers: CORS_HEADERS,
                body: JSON.stringify({
                  status: "stream",
                  downloadUrl: audios[0].url,
                  filename: `${(data.title || ytId).slice(0, 80)}.mp3`,
                  provider: "Invidious Direct",
                }),
              };
            }
          } else if (Array.isArray(data.formatStreams) && data.formatStreams.length > 0) {
            const best = data.formatStreams[data.formatStreams.length - 1];
            if (best && best.url) {
              return {
                statusCode: 200,
                headers: CORS_HEADERS,
                body: JSON.stringify({
                  status: "stream",
                  downloadUrl: best.url,
                  filename: `${(data.title || ytId).slice(0, 80)}.mp4`,
                  provider: "Invidious Direct",
                }),
              };
            }
          }
        } catch (_) {}
      }
    }

    // 3. Fallback Cloud Transcoder Engine (Loader.to / OceanSaver / Cobalt Compatible)
    const formatParam = mode === "audio" ? "mp3" : quality === "2160" ? "4k" : quality || "1080";
    const externalEngineUrl = `https://loader.to/api/button/?url=${encodeURIComponent(
      targetUrl
    )}&f=${encodeURIComponent(formatParam)}&color=2cc985`;

    return {
      statusCode: 200,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        status: "external_engine",
        engineUrl: externalEngineUrl,
        downloadUrl: externalEngineUrl,
        provider: "Cloud Transcoder",
      }),
    };
  } catch (err) {
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        error: "Erro ao resolver stream de download.",
        details: err.message,
      }),
    };
  }
}
