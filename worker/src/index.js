// CloudVote, partie FaaS : appelle la cloture sur Render toutes les 30 min.

const MAX_ATTEMPTS = 5;
const TIMEOUT_MS = 70_000; // Render Free met ~1 min a se reveiller
const BACKOFF_MS = 15_000;

// En-tetes d'une requete HTTP "classique" (Render rejetait la requete nue du Worker)
const BASE_HEADERS = {
  "User-Agent": "cloudvote-closer/1.0 (+Cloudflare Workers)",
  Accept: "application/json",
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Erreur definitive : inutile de reessayer.
class FatalError extends Error {}

function readConfig(env) {
  const url = (env.RENDER_URL || "").replace(/\/+$/, "");
  if (!url.startsWith("http")) {
    throw new FatalError("RENDER_URL manquant ou invalide");
  }
  if (!env.CLOSE_SECRET) {
    throw new FatalError("CLOSE_SECRET manquant");
  }
  return {
    baseUrl: url,
    closeUrl: `${url}/internal/close`,
    secret: env.CLOSE_SECRET,
    maxAttempts: Number(env.MAX_ATTEMPTS) || MAX_ATTEMPTS,
    timeoutMs: Number(env.TIMEOUT_MS) || TIMEOUT_MS,
    backoffMs: env.BACKOFF_MS !== undefined ? Number(env.BACKOFF_MS) : BACKOFF_MS,
  };
}

// Resume lisible d'une reponse en echec : en-tetes utiles + texte de la page (sans HTML).
function describe(res, body) {
  const h = (name) => res.headers.get(name) || "-";
  const text = body
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200);
  return `HTTP ${res.status} | server=${h("server")} rndr-id=${h("rndr-id")} origin=${h("x-render-origin-server")} | ${text}`;
}

// Reveille Render avec un GET /health avant la cloture (resultat ignore).
async function wakeUp(cfg) {
  try {
    const res = await fetch(`${cfg.baseUrl}/health`, {
      headers: BASE_HEADERS,
      signal: AbortSignal.timeout(cfg.timeoutMs),
    });
    const body = await res.text();
    console.log(`[closer] reveil /health : ${res.ok ? `HTTP ${res.status}` : describe(res, body)}`);
  } catch (err) {
    console.warn(`[closer] reveil /health : ${err.name}: ${err.message}`);
  }
}

// Reessayer est sans risque : l'endpoint Render est idempotent.
export async function callClose(env) {
  const cfg = readConfig(env);
  await wakeUp(cfg);

  for (let attempt = 1; attempt <= cfg.maxAttempts; attempt++) {
    try {
      const res = await fetch(cfg.closeUrl, {
        method: "POST",
        headers: {
          ...BASE_HEADERS,
          "Content-Type": "application/json",
          Authorization: `Bearer ${cfg.secret}`,
        },
        body: "{}",
        signal: AbortSignal.timeout(cfg.timeoutMs),
      });
      const body = await res.text();

      if (res.ok) {
        console.log(`[closer] OK (essai ${attempt}) : ${body}`);
        return { ok: true, attempt, body };
      }
      if (res.status === 401 || res.status === 403) {
        throw new FatalError(`refuse (${res.status}) : CLOSE_SECRET incorrect`);
      }
      console.warn(`[closer] essai ${attempt} : ${describe(res, body)}`);
    } catch (err) {
      if (err instanceof FatalError) throw err;
      console.warn(`[closer] essai ${attempt} : ${err.name}: ${err.message}`);
    }

    if (attempt < cfg.maxAttempts) await sleep(attempt * cfg.backoffMs);
  }

  // Marque l'execution en echec dans le tableau de bord.
  throw new Error(`[closer] echec apres ${cfg.maxAttempts} essais`);
}

export default {
  async scheduled(controller, env, ctx) {
    console.log(`[closer] cron "${controller.cron}"`);
    ctx.waitUntil(callClose(env));
  },

  // Pas de declenchement public.
  async fetch() {
    return new Response("Not found", { status: 404 });
  },
};
