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

// Tolleranza in minuti per il matching dei cron
const TOLERANCE_MINUTES = 10;

// Orari in ora italiana (Europe/Rome) → workflow da triggerare
const SCHEDULES = [
  { hour: 0,  minute: 0,  workflow: 'update_menu.yml'       },
  { hour: 1,  minute: 21, workflow: 'generate_images.yml'   },
  { hour: 9,  minute: 17, workflow: 'publish_instagram.yml' },
];

/**
 * Calcola la differenza in minuti tra due orari (gestisce il wrap a mezzanotte).
 */
function minutesDiff(h1, m1, h2, m2) {
  const t1 = h1 * 60 + m1;
  const t2 = h2 * 60 + m2;
  const diff = Math.abs(t1 - t2);
  // Gestisci il wrap a mezzanotte (es. 23:58 vs 00:02 = 4 minuti, non 1436)
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
    // Ora italiana reale (gestisce automaticamente CET/CEST)
    const now  = new Date();
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
        console.log(`[${now.toISOString()}] Triggered ${schedule.workflow} (Italian time ${hour}:${String(minute).padStart(2, '0')}, scheduled ${schedule.hour}:${String(schedule.minute).padStart(2, '0')}, tolerance ±${TOLERANCE_MINUTES}min)`);
        triggered = true;
      }
    }

    if (!triggered) {
      console.log(`[${now.toISOString()}] Nessun workflow da triggerare (Italian time ${hour}:${String(minute).padStart(2, '0')})`);
    }
  },
};
