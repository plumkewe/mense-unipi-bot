/**
 * Cloudflare Worker — mense-unipi-bot scheduler
 *
 * Sostituisce i cron trigger di GitHub Actions, che possono ritardare di ore.
 * Ogni trigger UTC viene eseguito due volte (una per CET, una per CEST); il
 * Worker controlla l'ora italiana reale prima di fare la chiamata API.
 *
 * Il matching usa una tolleranza di ±10 minuti per gestire ritardi dei cron
 * di Cloudflare Workers (che non garantiscono esecuzione al minuto esatto).
 *
 * Secrets richiesti (wrangler secret put):
 *   GITHUB_TOKEN  — Personal Access Token con permesso "workflow"
 */

const GITHUB_OWNER = 'plumkewe';
const GITHUB_REPO  = 'mense-unipi-bot';
const BRANCH       = 'main';

// Mappa diretta per associare ciascun cron (sia CEST che CET) al relativo workflow.
// In questo modo l'esecuzione del trigger garantisce sempre il lancio del workflow corretto,
// evitando che disallineamenti di fuso o tolleranze rigide scartino le run.
const CRON_TO_WORKFLOW = {
  // update_menu (00:00 IT)
  '0 22 * * *':  'update_menu.yml',        // CEST
  '0 23 * * *':  'update_menu.yml',        // CET

  // generate_images (01:21 IT)
  '21 23 * * *': 'generate_images.yml',    // CEST
  '21 0 * * *':  'generate_images.yml',    // CET

  // publish_instagram (09:17 IT)
  '17 7 * * *':  'publish_instagram.yml',  // CEST
  '17 8 * * *':  'publish_instagram.yml',  // CET
};

// Orari in ora italiana (Europe/Rome) → fallback se event.cron non corrisponde
const SCHEDULES = [
  { hour: 0,  minute: 0,  workflow: 'update_menu.yml'       },
  { hour: 1,  minute: 21, workflow: 'generate_images.yml'   },
  { hour: 9,  minute: 17, workflow: 'publish_instagram.yml' },
];

// Tolleranza in minuti per il fallback
const TOLERANCE_MINUTES = 20;

/**
 * Calcola la differenza in minuti tra due orari (gestisce il wrap a mezzanotte).
 */
function minutesDiff(h1, m1, h2, m2) {
  const t1 = h1 * 60 + m1;
  const t2 = h2 * 60 + m2;
  const diff = Math.abs(t1 - t2);
  return Math.min(diff, 1440 - diff);
}

async function triggerWorkflow(token, workflow, inputs = {}) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept':        'application/vnd.github+json',
      'Content-Type':  'application/json',
      'User-Agent':    'mense-unipi-bot-cloudflare-worker',
    },
    body: JSON.stringify({ ref: BRANCH, inputs }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GitHub API ${res.status}: ${body}`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date();
    const cron = event?.cron;

    // 1. Risoluzione primaria diretta tramite cron trigger
    if (cron && CRON_TO_WORKFLOW[cron]) {
      const workflow = CRON_TO_WORKFLOW[cron];
      await triggerWorkflow(env.GITHUB_TOKEN, workflow);
      console.log(`[${now.toISOString()}] Triggered ${workflow} via cron "${cron}"`);
      return;
    }

    // 2. Fallback con orario italiano reale (Europe/Rome)
    const parts = new Intl.DateTimeFormat('it-IT', {
      timeZone: 'Europe/Rome',
      hour:     '2-digit',
      minute:   '2-digit',
      hour12:   false,
    }).formatToParts(now);

    const hour   = parseInt(parts.find(p => p.type === 'hour').value,   10);
    const minute = parseInt(parts.find(p => p.type === 'minute').value, 10);

    let triggered = false;

    for (const schedule of SCHEDULES) {
      if (minutesDiff(schedule.hour, schedule.minute, hour, minute) <= TOLERANCE_MINUTES) {
        await triggerWorkflow(env.GITHUB_TOKEN, schedule.workflow);
        console.log(`[${now.toISOString()}] Triggered ${schedule.workflow} via fallback (Italian time ${hour}:${String(minute).padStart(2, '0')}, scheduled ${schedule.hour}:${String(schedule.minute).padStart(2, '0')})`);
        triggered = true;
      }
    }

    if (!triggered) {
      console.log(`[${now.toISOString()}] Nessun workflow da triggerare (cron: "${cron}", Italian time ${hour}:${String(minute).padStart(2, '0')})`);
    }
  },
};
