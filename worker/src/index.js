/**
 * CloudVote — Partie FaaS
 * Cloudflare Worker déclenché par un Cron Trigger (toutes les 30 minutes).
 * Il appelle l'endpoint sécurisé de clôture du service de reporting sur Render :
 *     POST {RENDER_URL}/internal/close
 *     Authorization: Bearer {CLOSE_SECRET}
 *
 * Le Worker n'a aucun endpoint public : toute requête HTTP reçoit 404.
 */

const MAX_ATTEMPTS = 3; // nombre maximal d'appels par exécution
const TIMEOUT_MS = 70_000; // Render Free peut mettre ~1 min à se réveiller
const BACKOFF_MS = 15_000; // attente entre deux essais : 15 s, puis 30 s

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Erreur définitive : inutile de réessayer (mauvais secret, mauvaise config). */
class FatalError extends Error {}

function readConfig(env) {
  const url = (env.RENDER_URL || "").replace(/\/+$/, "");
  if (!url.startsWith("http")) {
    throw new FatalError("RENDER_URL manquant ou invalide");
  }
  if (!env.CLOSE_SECRET) {
    throw new FatalError("CLOSE_SECRET manquant (wrangler secret put CLOSE_SECRET)");
  }
  return {
    closeUrl: `${url}/internal/close`,
    secret: env.CLOSE_SECRET,
    maxAttempts: Number(env.MAX_ATTEMPTS) || MAX_ATTEMPTS,
    timeoutMs: Number(env.TIMEOUT_MS) || TIMEOUT_MS,
    backoffMs: env.BACKOFF_MS !== undefined ? Number(env.BACKOFF_MS) : BACKOFF_MS,
  };
}

/**
 * Appelle l'endpoint de clôture avec réessais.
 * Réessayer un POST est sans risque car l'endpoint Render est idempotent :
 * un deuxième appel ne recompte jamais les bulletins déjà comptés.
 */
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
        throw new FatalError(
          `refusé (${res.status}) : CLOSE_SECRET différent entre le Worker et Render`
        );
      }
      console.warn(`[closer] essai ${attempt} : HTTP ${res.status} ${body.slice(0, 200)}`);
    } catch (err) {
      if (err instanceof FatalError) throw err;
      console.warn(`[closer] essai ${attempt} : ${err.name} — ${err.message}`);
    }

    if (attempt < cfg.maxAttempts) await sleep(attempt * cfg.backoffMs);
  }

  // Lever une erreur marque l'exécution du cron comme « échouée » dans le tableau de bord.
  throw new Error(`[closer] échec après ${cfg.maxAttempts} essais`);
}

export default {
  /** Exécuté par le Cron Trigger défini dans wrangler.toml. */
  async scheduled(controller, env, ctx) {
    console.log(
      `[closer] cron "${controller.cron}" — ${new Date(controller.scheduledTime).toISOString()}`
    );
    ctx.waitUntil(callClose(env));
  },

  /** Aucun déclenchement public possible. */
  async fetch() {
    return new Response("Not found", { status: 404 });
  },
};
