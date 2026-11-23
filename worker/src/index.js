// CloudVote, partie FaaS : appelle la cloture sur Render toutes les 30 min.

const MAX_ATTEMPTS = 3;
const TIMEOUT_MS = 70_000; // Render Free met ~1 min a se reveiller
const BACKOFF_MS = 15_000;

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
    closeUrl: `${url}/internal/close`,
    secret: env.CLOSE_SECRET,
    maxAttempts: Number(env.MAX_ATTEMPTS) || MAX_ATTEMPTS,
    timeoutMs: Number(env.TIMEOUT_MS) || TIMEOUT_MS,
    backoffMs: env.BACKOFF_MS !== undefined ? Number(env.BACKOFF_MS) : BACKOFF_MS,
  };
}

// Reessayer est sans risque : l'endpoint Render est idempotent.
export async function callClose(env) {
  const cfg = readConfig(env);

  for (let attempt = 1; attempt <= cfg.maxAttempts; attempt++) {
    try {
      const res = await fetch(cfg.closeUrl, {
        method: "POST",
        headers: { Authorization: `Bearer ${cfg.secret}` },
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
      console.warn(`[closer] essai ${attempt} : HTTP ${res.status} ${body.slice(0, 200)}`);
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
