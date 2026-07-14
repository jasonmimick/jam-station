# Family Radio — design

**Status:** design only. Nothing built. Written 2026-07-13.
**One line:** your dad's Mac in Florida becomes a *radio station* on your network — he goes
on air, you tune in.

---

## Read this first: what I need from you

Six decisions. Everything else in this doc is reasoning you can skim or skip.
My recommendation is in **bold**; the tradeoff is one line.

| # | Decision | My rec | Why it matters |
|---|---|---|---|
| **D1** | Are guest stations **listed** on the public site? | **No — invisible, not just unplayable** | Avoids "why is there a station I can't play," and it's one less thing that can leak. |
| **D2** | Who may **hear** a guest station — anyone on the tailnet, or **named people**? | **Named people** | Easy now, painful to retrofit. The day a friend-of-a-friend joins the tailnet, dad's records shouldn't be a surprise gift. |
| **D3** | Is **live-only the default**, with on-demand strictly opt-in by the broadcaster? | **Yes** | Live is outbound-only (near-zero trust surface). On-demand opens an inbound port. Off by default is the honest default. |
| **D4** | Business shape: do we sell **an always-on node (infrastructure)** rather than **music storage (a locker)**? | **Node, never locker** | This is the difference between "Linode" and "MP3.com, which lost." See §7. **This is the most important decision in the doc.** |
| **D5** | What does dad install — **a small native app** or a full slab node? | **Native menu-bar app** | If it's more than "pick a folder, go on air," this never happens. Slab stays on *your* side of the wire. |
| **D6** | Do I build **slices 1 + 2** next (both need nobody but you)? | **Yes** | They are the entire architecture and are testable with a *fake* dad. See §9. |

**Also needs you, not me:**
- **A1** — Decide the Tailscale model: invite dad into your tailnet as a user, vs. Tailscale
  *node sharing* (he keeps his own tailnet). Node sharing is cleaner for family.
- **A2** — Ask dad if he's actually up for this, and what shape his collection is in
  (folder layout, are files tagged?). Untagged files → the setlist reads "Track 3".
- **A3** — Sanity-check the money question in §7 with someone who knows music licensing
  before you charge anyone a dollar.

---

## 1. The idea

You shared jam-station with your dad. He has a huge music collection. Instead of him
*listening* to your station, **he becomes a station.**

Not "a music node" (a hard drive we pull from) — **a remote broadcasting node**: his Mac
is a *studio* that dials into the transmitter and goes on air. That reframe (yours) is the
whole design, and it's better than the file-server version I first proposed. §3 explains
why.

The end state is not one station with a shared drive. It's **a family radio network**:
N people, N stations, one dial.

---

## 2. What is already true (proven, not assumed)

Useful, because it means most of this isn't new invention:

- **slab peers work over Tailscale, across a WAN.** Proven today: euler ↔ mac-mini deploy,
  ingress, and control all ran over the tailnet.
- **`nowplaying` now reads icecast's mount metadata**, not our queue. Built today to fix a
  real bug (the queue ran a whole track *ahead* of the broadcast, because liquidsoap
  prefetches). **This is exactly the mechanism a guest station needs** — for a station we
  don't drive, icecast metadata is the *only* information we have. The seam converged on
  its own, which is good evidence it's the right one.
- **`playable`** is already a computed, derived flag (never a human toggle). It generalises
  to a guest station as "is his mount connected?" → **ON AIR / OFF AIR**.
- **icecast's `status-json` already gives listener counts.** That's dad's "1 listener
  (Jason)" — free, from an endpoint we already parse.

---

## 3. The core architecture: dad is a studio, not a disk

icecast is a **transmitter**. Source clients are **studios** that connect *to* it and push a
mount. That is how internet radio has always worked — liquidsoap is already doing it.

**Dad in Florida is just another studio dialing in.** He does not send us files. He *goes on
air.*

Three things fall out, and they're the reason this beats the file-server design:

1. **The trust problem disappears.** Dad's node makes **one outbound connection**, with
   **one credential**, to **one mount**. It cannot enumerate your rack, deploy to it, or
   read its state. Least privilege by construction. *(I was about to design a "scoped slab
   peering" feature to solve this. It isn't needed. The broadcast model deleted it.)*
2. **NAT disappears.** Outbound-only → **no port forwarding, no hole punching.** His home
   router just works.
3. **Metadata rides the stream.** icecast carries title/artist from the source, and we
   already read `status-json`. **Dad's now-playing appears in your UI without building
   anything.**

### The honest cost

A broadcast **cannot be seeked**. This is not a bug; it is what "broadcast" means.

| | our stations | dad's station |
|---|---|---|
| who drives the playout | the DJ / us | **dad** |
| setlist ("where am I in the show") | ✅ | ❌ the future doesn't exist yet |
| on-demand (jump / scrub / rewind) | ✅ | ❌ (unless he opts in — §6) |
| skip | ✅ | ❌ it isn't our playout |

The UI already degrades correctly (it hides the show panel when there's no show). It needs
a third station *type*, not a rewrite.

---

## 4. Architectural change #1: `origin` — a new dimension

This is the deepest change, and the easiest to get wrong by conflating two questions.

Today a channel has **`source`** = where the *bytes* live (`archive` / `phishin` /
`library`). Every channel is implicitly **ours** — we pick the show, we queue the tracks,
we can skip.

A guest station inverts that. So we need a second, **orthogonal** dimension:

| | `source` | **`origin`** (new) |
|---|---|---|
| answers | where the bytes live | **who decides what plays** |
| values | archive · phishin · library | **local** · **guest** |

A guest station has **no `source` at all from our side** — we never touch his files.

Everything else is a consequence of `origin = guest`:

- **no queue rows**; `ensure_queue` / `next_track` skip it entirely
- **no skip** — the button is **hidden, not disabled-and-lying**
  *(we shipped a skip button that lied about working once today. Not twice.)*
- **no setlist**, **no on-demand** (unless opted in)
- **`playable`** = his mount is connected → ON AIR / OFF AIR, *not* "broken"
- **`nowplaying`** and **listener count** come from icecast — already built

### ⚠️ The one that will bite us

**Guest channels must be excluded from `/api/channels.liq`** — the mount list *our*
liquidsoap opens. Otherwise our liquidsoap tries to open **dad's** mount and the two
sources fight over it. icecast rejects one of them and you lose an hour to it. Design it
away; don't rely on the error. Guest mounts also get namespaced (`guest-dadmac-jazz`) so a
collision is impossible by construction.

---

## 5. Architectural change #2: two planes (the safety architecture)

Today there is **one icecast, and it is behind the public tunnel.** Dad's records cannot go
through it — that would be an unlicensed public broadcast of commercial recordings (§7).

```
PUBLIC   icecast  ← archive · phishin     → tunnel → jam-station.runslab.run
PRIVATE  icecast  ← library · guest       → tailnet only, NEVER tunneled
```

slab already has the primitive (`public = false` → no host port, no ingress).

**But there's an honest hole:** the brain is a system-mate of *both* icecasts, and the brain
*is* tunneled. Network isolation alone does not save us — **the brain is the bridge, so the
brain must enforce.**

**The brain becomes hostname-scoped, and fails closed:**

- request on `jam-station.runslab.run` → **public plane**: private stations are not even
  *listed* by `/api/channels` (**D1**), and `/stream` 403s them
- request on a tailnet host → private plane: everything
- **anything it cannot positively identify as tailnet is treated as public**

Fail-closed matters more here than anywhere else in the system: the failure mode isn't a
broken feature, it's *accidentally public-broadcasting your dad's record collection.*

**And the rule that keeps it honest: `plane` is derived from `origin`/`source` — never a
human toggle.** Same discipline as `playable`. A switch someone can forget to set is a
switch that will eventually be wrong.

*Upgrade path if this ever carries someone else's music commercially:* **two brains** — a
public one with no route to the private icecast at all. Structurally airtight, but two DBs
and real duplication. Not worth it yet.

---

## 6. Architectural change #3: onboarding, and what dad installs

### The invite (one screen, one click)

**Tailscale pre-auth keys** make joining the network a single non-interactive step.

```
invite → ① join tailnet (pre-auth key)
         ② POST /api/guest/register   (one-time, single-use token)
         ③ ← { mount, icecast_host, source_password }
         ④ pick a folder
         ⑤ GO ON AIR
```

Dad never types a hostname, a mount, or a password.

### Dad's app — the make-or-break

**A single native menu-bar app. Not Docker. Not slab.** (**D5**)

The icecast source protocol is genuinely simple (an HTTP handshake, then MP3 frames + ICY
metadata), so this is a small program, not a platform. **If it is one screen more than
this, none of this happens:**

```
┌──────────────────────────────────┐
│  ⚡ Dad's Station        ● ON AIR │
│  Music folder: ~/Music       [⋯] │
│  1,847 tracks                    │
│  ┌────────────────────────────┐  │
│  │        GO ON AIR           │  │  ← the entire product
│  └────────────────────────────┘  │
│  ▸ Now playing: Kind of Blue     │
│  ▸ 1 listener  (Jason)           │  ← the emotional payload
│  ☐ Also let family browse my     │
│    collection on demand          │  ← his choice, OFF by default (D3)
└──────────────────────────────────┘
```

**"1 listener (Jason)" is the feature.** A dad in Florida seeing that his son is listening
to his records is the entire reason this gets built — and it costs us nothing.

Dad must always have: which folders, who can listen, **who is listening**, and an off
switch. His machine, his call.

### The opt-in inbound capability (on-demand)

The checkbox is the *only* thing that opens an inbound port. It serves `/library` and
`/track/{id}` over the tailnet with a token.

Note: the **browser fetches dad's tracks directly** over the tailnet — not relayed through
the mini. Efficient, and it works because your phone is on the tailnet too. **His binary
must send CORS headers**, or the Web Audio EQ plays silence on his music. (We learned that
one the hard way today.)

---

## 7. The business shape — and the wall

**Your instinct was right, and the pricing falls out of the physics:**

- **Live broadcast**: dad's machine does the work. Costs us nothing. When his laptop sleeps
  his station is simply **off air** — which is *correct radio*, not a failure.
- **On-demand**: the tracks must be there **whenever the listener wants them**, not when dad
  happens to be awake. A radio being off-air is fine. A library that's *missing* is broken.

**So on-demand is not a feature — it is an availability guarantee.** Always-on costs
storage, egress and uptime. That is a real cost, so it is a real price. **Best kind of
pricing: nothing artificial about the line.**

**And you never have to cripple the free tier.** Let dad expose his library from his own
Mac — it will work, *when his Mac is awake*. The user feels the exact gap the paid tier
fills ("dad's collection is offline again") and the upgrade sells itself.

### ⚠️ The wall (D4 — the most important decision here)

**The moment you store and serve someone else's music, you stop being a conduit and become
a host** — and you'd be **charging** for it, which strips away every "private,
personal, non-commercial" mitigation and gives you revenue worth suing for.

This is a well-marked grave: **MP3.com lost** doing roughly this (store users' CDs, stream
them back). Lockers *can* work — iTunes Match, Amazon, Google — but the survivors
**licensed**, and the one that didn't, died.

And the thing everyone actually wants is the hottest version: **you want to scrub *dad's*
tapes.** Dad → his own files is arguably a locker. **Dad's files → you (a different person),
on demand, through a service you are paid for → that is distribution.** Family or not.

### The reframe that fixes it — and it's the better business

> **Don't sell storage of their music. Sell the always-on node.**
>
> *"Run your node on your Mac — free. Or let us host it — $X/mo, always on."*

Same software, two homes. You are then:

- **infrastructure, not a librarian.** You never hold a master copy. His node holds *his*
  files and he controls it. That is the Linode position, not the MP3.com position.
- selling **uptime and hardware** — unambiguous, boring. **Boring is exactly what you want
  when copyright is in the room.**
- **literally selling slab.** This is the wedding you were reaching for: *"add a music
  node"* and *"spin up a slab node"* become the same sentence, and **jam-station becomes the
  demo that sells slab.**

**One hard rule if you go there: never build cross-user dedupe or fingerprint-matching.**
"You have that album? here's our copy" is *precisely* what killed MP3.com. Each node holds
its own bytes, always. It is slower and dumber — **and it is the whole defence.**

**None of the above is legal advice.** It's the shape of the risk. See **A3**.

---

## 8. What changes in slab: almost nothing — and that's the finding

- Private icecast → `public = false`. **Already exists.**
- Tunnel already only maps the brain. **No change.**
- **Dad is not a slab peer.** Outbound-only, one credential, one mount. **The "scoped
  peering" feature I nearly invented is not needed.**

**Slab grows at the paid tier, not here.** The hosted always-on node — the thing you'd
actually charge for — is where slab needs an invite / scoped-join flow, and where slab
becomes the product being sold.

**v1 needs zero slab changes.** That's a clean staging, and it means you can't accidentally
spend a month building slab features in service of a music demo.

---

## 9. Build order (D6)

| # | slice | needs dad? |
|---|---|---|
| **1** | **Split the planes** — public/private icecast, hostname-scoped brain, fail-closed. **Prove a `library` channel is unreachable from the public URL.** | **no** |
| **2** | **Guest station type** — `origin`, no skip, no setlist, ON AIR from icecast. Test with a **fake guest**: a second liquidsoap on euler pushing a mount. | **no** |
| 3 | Dad's client + invite + tailnet pre-auth | yes |
| 4 | On-demand opt-in (the inbound capability) | yes |
| 5 | Hosted always-on node — **the paid tier, where slab gets sold** | — |

**Slices 1 and 2 are the entire architecture, and both are testable with a fake dad.** A
second liquidsoap on euler pushing a mount exercises every code path a real dad would.

That's also the right *emotional* order: **dad's first experience should not be your
debugging.**

---

## 10. Failure modes to design for

| failure | behaviour |
|---|---|
| dad's Mac sleeps | mount drops → **OFF AIR** (not "broken"). Honest state, already have the pattern. |
| dad opens two instances | icecast rejects the second source → client says *"already on air elsewhere."* |
| mount name collision | impossible by construction — guest mounts are namespaced |
| dad's uplink saturates | stream stutters. Consider showing "unstable". |
| his files are untagged | setlist reads "Track 3" — we already do this honestly |
| tailnet down | guest unreachable → OFF AIR |
| **our liquidsoap opens dad's mount** | **must be impossible — exclude guests from `channels.liq` (§4)** |

---

## 11. Open questions I have not resolved

- **Does dad get a DJ?** He curates; the AI DJ drives *our* stations. Probably he just
  shuffles a folder in v1, and "dad's DJ" is a later idea. Not designed.
- **Multiple stations per person?** Dad might want "Dad's Jazz" and "Dad's Bluegrass."
  Falls out naturally (one mount each) but doubles his UI. Deferred.
- **Does dad's station show "up next"?** Only if his client pushes its queue to the brain.
  A nicety, not required. Deferred.
- **Recording / time-shift** ("I missed his set") — this is on-demand by another name, and
  it's the same legal wall. Do not build casually.
