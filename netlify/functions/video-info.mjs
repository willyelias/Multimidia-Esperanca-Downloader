// Netlify Serverless Function: Obtém metadados do vídeo ou playlist (YouTube, TikTok, Instagram, X, Vimeo, etc.)

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

function detectPlatform(url) {
  const lower = url.toLowerCase();
  if (lower.includes("youtube.com") || lower.includes("youtu.be")) return "YouTube";
  if (lower.includes("tiktok.com")) return "TikTok";
  if (lower.includes("instagram.com")) return "Instagram";
  if (lower.includes("twitter.com") || lower.includes("x.com")) return "Twitter / X";
  if (lower.includes("facebook.com") || lower.includes("fb.watch")) return "Facebook";
  if (lower.includes("vimeo.com")) return "Vimeo";
  if (lower.includes("soundcloud.com")) return "SoundCloud";
  if (lower.includes("twitch.tv")) return "Twitch";
  return "Web Video";
}

async function fetchWithTimeout(resource, options = {}, timeout = 6500) {
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
    let targetUrl = event.queryStringParameters?.url;
    if (!targetUrl && event.body) {
      const parsed = JSON.parse(event.body);
      targetUrl = parsed.url;
    }

    if (!targetUrl) {
      return {
        statusCode: 400,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "URL não informada." }),
      };
    }

    targetUrl = targetUrl.trim();
    const platform = detectPlatform(targetUrl);
    const ytId = extractYouTubeId(targetUrl);

    // 1. Se for TikTok, tenta API TikWM para obter dados completos e link sem marca d'água
    if (platform === "TikTok") {
      try {
        const tikRes = await fetchWithTimeout(
          `https://www.tikwm.com/api/?url=${encodeURIComponent(targetUrl)}`
        );
        const tikJson = await tikRes.json();
        if (tikJson && tikJson.data) {
          const d = tikJson.data;
          return {
            statusCode: 200,
            headers: CORS_HEADERS,
            body: JSON.stringify({
              title: d.title || "Vídeo do TikTok",
              author: d.author?.nickname || d.author?.unique_id || "TikTok",
              thumbnail: d.cover || d.origin_cover,
              duration: d.duration || 0,
              platform,
              url: targetUrl,
              directVideoUrl: d.play,
              directAudioUrl: d.music,
            }),
          };
        }
      } catch (_) {}
    }

    // 2. Se for YouTube, tenta Piped API para metadados detalhados + durações + streams
    if (ytId) {
      const pipedInstances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.moomoo.me",
      ];

      for (const base of pipedInstances) {
        try {
          const r = await fetchWithTimeout(`${base}/streams/${ytId}`, {}, 4000);
          if (r.ok) {
            const data = await r.json();
            if (data && data.title) {
              return {
                statusCode: 200,
                headers: CORS_HEADERS,
                body: JSON.stringify({
                  id: ytId,
                  title: data.title,
                  author: data.uploader || "YouTube",
                  thumbnail:
                    data.thumbnailUrl ||
                    `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg`,
                  duration: data.duration || 0,
                  platform: "YouTube",
                  url: targetUrl,
                }),
              };
            }
          }
        } catch (_) {}
      }
    }

    // 3. Fallback universal via NoEmbed / OEmbed (funciona para YouTube, Vimeo, SoundCloud, Twitter, etc.)
    try {
      const noembedRes = await fetchWithTimeout(
        `https://noembed.com/embed?url=${encodeURIComponent(targetUrl)}`,
        {},
        5000
      );
      if (noembedRes.ok) {
        const oe = await noembedRes.json();
        if (oe && !oe.error && oe.title) {
          return {
            statusCode: 200,
            headers: CORS_HEADERS,
            body: JSON.stringify({
              id: ytId,
              title: oe.title,
              author: oe.author_name || platform,
              thumbnail:
                oe.thumbnail_url ||
                (ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null),
              duration: 0,
              platform,
              url: targetUrl,
            }),
          };
        }
      }
    } catch (_) {}

    // 4. Fallback garantido para YouTube ID
    if (ytId) {
      return {
        statusCode: 200,
        headers: CORS_HEADERS,
        body: JSON.stringify({
          id: ytId,
          title: `Vídeo do YouTube (${ytId})`,
          author: "YouTube",
          thumbnail: `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg`,
          duration: 0,
          platform: "YouTube",
          url: targetUrl,
        }),
      };
    }

    return {
      statusCode: 200,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        title: `Mídia de ${platform}`,
        author: platform,
        thumbnail: null,
        duration: 0,
        platform,
        url: targetUrl,
      }),
    };
  } catch (err) {
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        error: "Falha ao processar informações do link.",
        details: err.message,
      }),
    };
  }
}
