// jam-watch: is jam-listen up, and does every live station actually send audio?
// Runs every 30 min (cron) and on demand at GET /check. Notifies only when the
// state changes (down / back up), plus a reminder every 12 h while still down.

const REMIND_MS = 12 * 3600 * 1000
const WEEKLY_CRON = '0 13 * * 1'   // Mondays 8:00 New York (EST)
const MAX_STATIONS = 12 // free plan allows 50 subrequests per run

async function probe(site) {
  const problems = []
  let dial
  try {
    const r = await fetch(`${site}/api/dial`, { signal: AbortSignal.timeout(15000) })
    if (!r.ok) return { ok: false, problems: [`jam-listen /api/dial returned ${r.status}`], stations: {} }
    dial = await r.json()
  } catch (e) {
    return { ok: false, problems: [`jam-listen unreachable: ${e.message}`], stations: {} }
  }
  const slugs = Object.keys(dial).slice(0, MAX_STATIONS)
  if (!slugs.length) problems.push('no station has anything playing')
  const stations = {}
  await Promise.all(slugs.map(async (slug) => {
    try {
      const r = await fetch(`${site}/stream/${slug}`, { signal: AbortSignal.timeout(15000) })
      if (!r.ok) { stations[slug] = `HTTP ${r.status}`; r.body?.cancel(); return }
      const reader = r.body.getReader()
      let got = 0
      while (got < 4096) {
        const { value, done } = await reader.read()
        if (done) break
        got += value.length
      }
      reader.cancel()
      stations[slug] = got >= 4096 ? 'ok' : `only ${got} bytes`
    } catch (e) {
      stations[slug] = `error: ${e.message}`
    }
  }))
  for (const [slug, s] of Object.entries(stations)) if (s !== 'ok') problems.push(`${slug}: ${s}`)
  return { ok: problems.length === 0, problems, stations }
}

async function notify(env, title, body, tags) {
  if (!env.NTFY_TOPIC) return
  await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, {
    method: 'POST',
    headers: { Title: title, Tags: tags, Click: env.SITE },
    body,
  })
}

async function run(env) {
  let res = await probe(env.SITE)
  if (!res.ok) {
    // a station toggle restarts liquidsoap for ~30 s; don't page for that
    await new Promise((r) => setTimeout(r, 40000))
    res = await probe(env.SITE)
  }
  const now = Date.now()
  const prev = JSON.parse((await env.STATE.get('state')) || '{"ok":true}')
  let next = prev
  if (!res.ok && prev.ok) {
    next = { ok: false, since: now, notified: now }
    await notify(env, 'jam stations DOWN', res.problems.join('\n'), 'rotating_light')
  } else if (!res.ok && now - (prev.notified || 0) > REMIND_MS) {
    const hrs = Math.round((now - prev.since) / 3600000)
    next = { ...prev, notified: now }
    await notify(env, `jam stations still down (${hrs} h)`, res.problems.join('\n'), 'warning')
  } else if (res.ok && !prev.ok) {
    const mins = Math.round((now - prev.since) / 60000)
    next = { ok: true }
    await notify(env, 'jam stations back up', `down ${mins} min; ${Object.keys(res.stations).length} stations streaming`, 'white_check_mark')
  }
  if (next !== prev) await env.STATE.put('state', JSON.stringify(next))
  return { ...res, checked: new Date(now).toISOString(), down_since: next.ok ? null : new Date(next.since).toISOString() }
}

// ---------------------------------------------------------------- weekly usage summary
// Mondays: hours per station for the last 7 days, from jam-listen's admin usage report
// (jam-station docs/DESIGN-usage-reports.md). Needs the ADMIN_TOKEN secret.

const fmtH = (h) => (h >= 1 ? `${h.toFixed(1)} h` : `${Math.round(h * 60)} min`)

async function weekly(env, send = true) {
  const r = await fetch(`${env.SITE}/api/admin/usage?days=7`, {
    headers: { 'X-Admin-Token': env.ADMIN_TOKEN || '' }, signal: AbortSignal.timeout(20000),
  })
  if (!r.ok) throw new Error(`usage report returned ${r.status}`)
  const u = await r.json()
  const played = u.channels.filter((c) => c.hours > 0)
  const unplayed = u.channels.filter((c) => c.continuous && !c.hours)
  const lines = [
    `${fmtH(u.total_hours)} listened this week.`,
    ...played.slice(0, 8).map((c) => `${c.name}: ${fmtH(c.hours)}`),
  ]
  if (u.clients.length) lines.push('', 'By app: ' + u.clients.map((c) => `${c.name} ${fmtH(c.hours)}`).join(', '))
  if (unplayed.length) lines.push('', `Always-on, not played: ${unplayed.map((c) => c.name).join(', ')}`)
  const body = lines.join('\n')
  if (send) await notify(env, 'jam stations: weekly listening', body, 'bar_chart')
  return body
}

export default {
  async scheduled(ev, env, ctx) {
    if (ev.cron === WEEKLY_CRON) ctx.waitUntil(weekly(env))
    else ctx.waitUntil(run(env))
  },
  async fetch(req, env) {
    const url = new URL(req.url)
    if (url.pathname === '/check') {
      const out = await run(env)
      return Response.json(out, { status: out.ok ? 200 : 503 })
    }
    if (url.pathname === '/weekly') {
      // preview; ?send=1 pushes it too. Admin token only: it reads usage and can push.
      if (!env.ADMIN_TOKEN || req.headers.get('X-Admin-Token') !== env.ADMIN_TOKEN) {
        return new Response('jam-watch: GET /check\n', { status: 404 })
      }
      try {
        return new Response(await weekly(env, url.searchParams.get('send') === '1') + '\n')
      } catch (e) {
        return new Response(`${e.message}\n`, { status: 502 })
      }
    }
    return new Response('jam-watch: GET /check, GET /weekly\n', { status: 404 })
  },
}
