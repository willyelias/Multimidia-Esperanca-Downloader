// Netlify Serverless Function: Inicia e acompanha a conversão limpa via JSON (Sem iframes, sem anúncios)
// Retorna link direto com Content-Disposition: attachment para download automático no computador.

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json; charset=utf-8",
};

const API_DOMAINS = ["p.savenow.to", "p.lbserver.xyz"];

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
    const query = event.queryStringParameters || {};
    const body = event.body ? JSON.parse(event.body) : {};
    const action = body.action || query.action || (query.jobId || body.jobId ? "progress" : "init");

    // --- ETAPA 2: CONSULTAR PROGRESSO DO JOB ---
    if (action === "progress") {
      const jobId = body.jobId || query.jobId;
      const customProgressUrl = body.progressUrl || query.progressUrl;

      if (!jobId && !customProgressUrl) {
        return {
          statusCode: 400,
          headers: CORS_HEADERS,
          body: JSON.stringify({ error: "jobId obrigatório para consultar progresso." }),
        };
      }

      const urlsToTry = [];
      if (customProgressUrl) urlsToTry.push(customProgressUrl);
      for (const dom of API_DOMAINS) {
        urlsToTry.push(`https://${dom}/api/progress?id=${encodeURIComponent(jobId)}`);
      }

      for (const progUrl of urlsToTry) {
        try {
          const r = await fetchWithTimeout(
            progUrl,
            {
              headers: {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                Accept: "application/json",
              },
            },
            5000
          );
          if (!r.ok) continue;
          const data = await r.json();

          // progress vem de 0 a 1000
          const rawProg = typeof data.progress === "number" ? data.progress : 0;
          const percent = Math.min(100, Math.max(5, Math.round(rawProg / 10)));
          const isFinished = Boolean(data.download_url && Number(data.success) === 1);

          let finalDownloadUrl = data.download_url || null;
          if (
            !finalDownloadUrl &&
            Array.isArray(data.alternative_download_urls) &&
            data.alternative_download_urls.length > 0
          ) {
            finalDownloadUrl = data.alternative_download_urls[0].url || null;
          }

          return {
            statusCode: 200,
            headers: CORS_HEADERS,
            body: JSON.stringify({
              status: isFinished ? "completed" : "processing",
              progress: isFinished ? 100 : percent,
              downloadUrl: finalDownloadUrl,
              statusText: data.text || (isFinished ? "Concluído!" : "Processando mídia..."),
              error: Number(data.success) === 0 && data.text && rawProg === 1000 ? data.text : null,
            }),
          };
        } catch (_) {}
      }

      return {
        statusCode: 200,
        headers: CORS_HEADERS,
        body: JSON.stringify({
          status: "processing",
          progress: 25,
          downloadUrl: null,
          statusText: "Preparando arquivo...",
        }),
      };
    }

    // --- ETAPA 1: INICIAR DOWNLOAD / TRANSCODIFICAÇÃO ---
    const targetUrl = (body.url || query.url || "").trim();
    const mode = body.mode || query.mode || "video"; // "video" | "audio"
    const quality = String(body.quality || query.quality || "1080");
    const trimStart = body.trimStart || query.trimStart || "";
    const trimEnd = body.trimEnd || query.trimEnd || "";

    if (!targetUrl) {
      return {
        statusCode: 400,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "URL obrigatória." }),
      };
    }

    // 1. Se for TikTok, tenta resolução instantânea sem marca d'água via TikWM
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
          const directUrl = mode === "audio" ? d.music : d.hdplay || d.play;
          if (directUrl) {
            return {
              statusCode: 200,
              headers: CORS_HEADERS,
              body: JSON.stringify({
                status: "completed",
                progress: 100,
                downloadUrl: directUrl,
                title: d.title || "TikTok Video",
                thumbnail: d.cover || d.origin_cover || null,
                filename: `${(d.title || "tiktok_media").slice(0, 60)}.${
                  mode === "audio" ? "mp3" : "mp4"
                }`,
              }),
            };
          }
        }
      } catch (_) {}
    }

    // 2. Inicia job JSON direto nos servidores de transcodificação (Suporta YouTube, Instagram, Facebook, X, Vimeo, etc.)
    const formatParam =
      mode === "audio"
        ? "mp3"
        : quality === "2160"
        ? "4k"
        : ["1080", "720", "480", "360"].includes(quality)
        ? quality
        : "1080";

    for (const domain of API_DOMAINS) {
      try {
        const apiUrl = new URL(`https://${domain}/api/v2/download`);
        apiUrl.searchParams.set("button", "1");
        apiUrl.searchParams.set("format", formatParam);
        apiUrl.searchParams.set("url", targetUrl);
        if (trimStart) apiUrl.searchParams.set("start_time", trimStart);
        if (trimEnd) apiUrl.searchParams.set("end_time", trimEnd);

        const r = await fetchWithTimeout(
          apiUrl.toString(),
          {
            headers: {
              "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
              Accept: "application/json",
            },
          },
          6000
        );

        if (!r.ok) continue;
        const data = await r.json();

        if (data && data.id) {
          return {
            statusCode: 200,
            headers: CORS_HEADERS,
            body: JSON.stringify({
              status: "polling",
              jobId: data.id,
              progressUrl:
                data.progress_url || `https://${domain}/api/progress?id=${encodeURIComponent(data.id)}`,
              title: data.title || data.info?.title || null,
              thumbnail: data.thumbnail_url || data.info?.image || null,
              progress: 10,
            }),
          };
        }
      } catch (_) {}
    }

    return {
      statusCode: 502,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        error: "Não foi possível iniciar o processamento deste link no momento. Verifique se o vídeo é público.",
      }),
    };
  } catch (err) {
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        error: "Erro interno ao processar download.",
        details: err.message,
      }),
    };
  }
}
