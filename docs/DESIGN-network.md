# Network — affiliates, carriage, and what a node actually costs

**Status:** ideation + measured numbers. Nothing built. 2026-07-13.
**One line:** don't build a server with guests. Build a **network of sovereign stations that
choose to carry each other** — and tell everyone honestly what it costs to run one.

---

## 1. Radio already has the words. Use them.

You said **"affiliate."** That isn't a metaphor — it's the actual model, and broadcast radio
solved this decades ago.

An **affiliate** is an *independent station* that **chooses to carry** some of a network's
programming, and also airs its own local stuff. **It is not a branch office. It is
sovereign.**

That hands us the primitive:

> ### Carriage is two independent, consensual decisions
> 1. **I offer** my station to you — *(outbound: who may hear/carry me)*
> 2. **You carry** my station — *(inbound: what appears on your dial)*

Both sides opt in, **per station**. Never "join my network and get everything."

### Why sovereignty is not a nicety

In the star model (v1), **dad's friends would have to be approved by Jason.** That is absurd,
and it will not survive contact with a real family.

Make dad a *sovereign station* with his own members, and **his friends are his business.**
You two simply agree to carry each other.

**Sovereignty is what makes this a network instead of a server with guests.**

---

## 2. Staging — don't skip ahead

| | stage | what it unlocks |
|---|---|---|
| **1** | **Star** — you're the center; dad broadcasts *into* you | what's designed today |
| **2** | **Sovereign** — dad becomes his own center, with his own members | **the unlock** |
| **3** | **Pairwise carriage** — you each choose what to carry from the other | the network |
| **4** | **Networks / circles** — "the family", "the taper crew" | only if someone asks |

**Do not build 4 until 2 and 3 prove anyone wants it.** The affiliate handshake is the same
primitive at 2 stations or 200 — so **you never have to guess the end state now.**

### On "regions"

Skip geography. It's charming, and it *does* fit the radio metaphor (markets!), but
**geography is not why your family connects — relationship is.** Radio already has the better
word: a **network** is just a set of stations that carry each other, and a station can belong
to several. *"The family"* and *"the taper crew"* are **networks, not regions.**

---

## 3. Subdomains: the real product, and the real trap

`dad.jamstation.fm` is a **call sign**. It's an *address* — how you tell someone to tune in.
**People will pay for a name.** It's also the natural hook for the hosted node: you provide
the address, the DNS, the tunnel, the uptime.

### ⚠️ But this is exactly where it can go wrong

**A public, password-gated website streaming your dad's CD collection is a *weaker* legal
position than a private VPN.**

A tailnet is defensible as *"our private network."* A subdomain **you** host, with DNS in
**your** name, streaming commercial records to whoever you've let in — **that is a service.**
And the moment you hand out subdomains and run the tunnels, **you are the network operator.**

> **Growth is the risk here, not the goal.**
> Two family members sharing CDs over a VPN is *private*.
> Two hundred strangers on subdomains you administer is a **pirate radio network with your
> name on the DNS.**

---

## 4. The strategic fork — this is the whole game

**The public/private plane split isn't just a technical boundary. It's the business
boundary.** Sort by **content**, not by feature:

| | **PUBLIC lane** | **PRIVATE lane** |
|---|---|---|
| content | **Archive tapes · Creative Commons · original** | **your own records** |
| reach | subdomains, discovery, growth, **money** | tailnet, approved members |
| legality | **clean forever** | private, small, family |
| scale | as big as you like | **deliberately never** |

**Same software. The content source decides the lane** — and `source` / `origin` / `plane`
already encode exactly that. Nothing new to invent.

### And there's a whole legitimate product hiding in the left column

**A network of curated stations playing taper-friendly live music.** Archive.org is
effectively infinite, it is **100% legal**, and *nobody has built a good one.* Each person
curates a station; stations affiliate; it grows. **That can be a real business — subdomains,
discovery, money, all of it.**

Meanwhile dad's CD collection stays in the right column: private, forever, never touching
your DNS.

> **The mistake would be blurring them** — letting personal collections leak into the public
> network because the software made it easy. Which is exactly why the plane split must be
> **structural and derived**, never a toggle someone can flip.

---

## 5. What a node actually costs (measured, not guessed)

This is a **feature**, not a footnote. It's the honest counterpart to the paid tier: most
companies hide what the free option really costs. **Showing it makes the upsell a real
choice instead of a trick.**

### Measured on your mac-mini, right now

Machine: **Macmini9,1 (M1, 8 cores)** — running the **whole** station, 15 channels:

| container | CPU | RAM |
|---|---|---|
| `jam-radio` (liquidsoap — **15 MP3 encoders**) | **55.5%** | 479 MB |
| `jam-icecast` | 1.0% | 11 MB |
| `jam-brain` (API, UI, DJ) | 0.1% | 94 MB |

**≈ 0.57 of one core, out of 8 → about 7% of the machine.**
So **one channel ≈ 3.7% of a core.** *(Note: encoding at 256kbps costs roughly twice what
128 did — a real, accepted cost of the quality bump.)*

### Power and money

M1 mini: **~6.8W idle, ~39W max**. Under this load: **~12W**.

```
12W × 24h × 30d ÷ 1000 = 8.6 kWh/month
8.6 kWh × $0.17/kWh     ≈ $1.47 / month      ← whole machine, dedicated, 24/7
```

**Two numbers, and both are honest — they answer different questions:**

| | | |
|---|---|---|
| **Total** | machine dedicated to this, running 24/7 | **≈ $1.47 / mo** |
| **Marginal** | the mini is on anyway; what does the *station* add? (~5W over idle) | **≈ $0.64 / mo** |

### Dad's cost (an affiliate broadcasting ONE station)

One encoder ≈ **3.7% of a core**, a few watts.

> **≈ $0.37 / month.** Less if he isn't on air 24/7.

**That number removes the objection entirely.** "Will this cost me anything?" — *about
thirty-seven cents a month.*

### Bandwidth

| | |
|---|---|
| **Affiliate (dad) uploads** | **256 kbps constant while on air** → ~115 MB/hr → **~83 GB/mo** if 24/7 |
| **Center (your mini) egress** | 256 kbps **× each listener** |

**The key economic asymmetry:** dad's upload is **constant regardless of how many people
listen** — he pushes *once* to icecast. **The center fans out.** So the center is the one
that bears listener bandwidth, and the affiliate's cost is flat and tiny.

*(83 GB is ~7% of a 1.2 TB Comcast cap. Fine — but worth showing him, not hiding.)*

### What the feature looks like

**In dad's app:**
```
Your station
  On air        6h today
  CPU           4% of one core
  Memory        38 MB
  Power         ~3W   ·   ~$0.37 / month
  Upload        256 kbps   ·   2.1 GB today
```

**In the owner/slab view:**
```
This node
  15 stations encoding
  CPU     0.6 cores  (7% of machine)
  Power   ~12W  ·  $1.47 / month
  If the machine is on anyway:  $0.64 / month
```

### How to measure it honestly

1. **Best — real power:** macOS `powermetrics --samplers cpu_power` gives actual CPU package
   power in mW. Needs sudo.
2. **Good — model table:** `sysctl hw.model` → known idle/max watts per Mac, interpolated by
   CPU%. *(An estimate. **Label it as one.**)*
3. **Fallback:** let them type in their machine's watts.
4. **Electricity rate:** a setting. Default to a national average (~$0.17/kWh US), because
   real rates swing from $0.10 to $0.40.

> **Do not present an estimate as a measurement.** The entire value of this feature is that
> it is *trustworthy*.

### And this is the honest upsell

> **Run it yourself:** ~$1.50/mo of electricity — **and your Mac can never sleep.**
> **We host it:** $X/mo, always on.

**The paid tier is not competing with $1.50 of electricity.** It's competing with *"my laptop
can never sleep"* — which is the exact availability problem from `DESIGN-family-radio.md` §7.
The cost display doesn't undercut the upsell; **it makes it legible.**

### 💡 This is a slab feature, not just a jam-station one

slab is *"the localhost hyperscaler."* **Nobody tells you what your rack costs to run.**

```
$ slab status
  rack: 2 nodes · 24 apps · 14W · ~$2.10/month
```

That fits the rack metaphor exactly, it's genuinely useful, and **it is a differentiator no
cloud provider can copy** — because on their side, the cost *is* the bill. On yours, it's
electricity, and it's almost nothing. **That's the entire pitch of self-hosting, expressed as
a number.**

---

## 6. Open questions

- **Does an affiliate need the center at all,** or can two sovereign stations carry each other
  directly? (Direct is purer; a center makes discovery and membership easier. Probably: direct
  carriage, optional center for discovery.)
- **Who pays for listener bandwidth** when dad's station is carried on *your* center and *your*
  listeners hear it? (Today: you. At scale: this is exactly why the center is the thing worth
  charging for.)
- **Can a station be carried without being *listed*?** (Unlisted stations — you can tune in
  with a link but it isn't on the dial. Probably yes; it's how people will actually share.)
