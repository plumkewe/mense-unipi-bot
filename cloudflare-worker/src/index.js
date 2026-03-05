/**
 * Cloudflare Worker — mense-unipi-bot scheduler
 *
 * Sostituisce i cron trigger di GitHub Actions, che possono ritardare di ore.
 * Ogni trigger UTC viene eseguito due volte (una per CET, una per CEST); il
 * Worker controlla l'ora italiana reale prima di fare la chiamata API.
 *
 * Secrets richiesti (wrangler secret put):
 *   GITHUB_TOKEN  — Personal Access Token con permesso "workflow"
 */

const GITHUB_OWNER = 'plumkewe';
const GITHUB_REPO  = 'mense-unipi-bot';
const BRANCH       = 'main';

// Orari in ora italiana (Europe/Rome) → workflow da triggerare
const SCHEDULES = [
  { hour: 0,  minute: 0,  workflow: 'update_menu.yml'       },
  { hour: 1,  minute: 21, workflow: 'generate_images.yml'   },
  { hour: 9,  minute: 21, workflow: 'publish_instagram.yml' },
];

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

    for (const schedule of SCHEDULES) {
      if (schedule.hour === hour && schedule.minute === minute) {
        await triggerWorkflow(env.GITHUB_TOKEN, schedule.workflow);
        console.log(`[${now.toISOString()}] Triggered ${schedule.workflow} (Italian time ${hour}:${String(minute).padStart(2, '0')})`);
      }
    }
  },
};
