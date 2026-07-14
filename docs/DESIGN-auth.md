# Auth — invite, approve, magic link + code

**Status:** design only. Nothing built. 2026-07-13.
**One line:** email is the identity. You approve people. No third-party identity provider,
no passwords, no lock-in.

**Explicitly NOT using:** Clerk, Auth0, OAuth, or any hosted identity provider. You own the
whole auth path. There is nothing to migrate off later.

---

## The flow (Jason's design)

```
① Jason shares a link         →  text / email / group chat
                                 https://jam-station.runslab.run/join?i=<invite>

② Visitor requests access     →  email + name  ("I'm your cousin Bob")
                                 → creates a PENDING request

③ Jason gets an email         →  "Bob (bob@x.com) wants in."   [Review]
                                 → lands on a page → he approves

④ Bob gets an email with TWO ways in:
      • a MAGIC LINK   → click → signed in on THIS device
      • an 8-char CODE → type it on ANY device        ← the important half

⑤ Session cookie, 30 days     →  HttpOnly, Secure, SameSite=Lax

⑥ After 30 days               →  re-verify by email. No re-approval — approval is once.
```

**Approval happens once. Verification is routine.** That distinction is the whole ergonomics
of the thing.

---

## Why the CODE (not just a magic link) is the load-bearing idea

This is the best part of your design and it solves a real, common failure:

> You open the email in **Gmail on your phone**. You click the link. You are now signed in
> **on your phone** — but you wanted to listen on your **laptop**.

Magic links sign in *the device that opened the email*. That is frequently the wrong device.

**The code fixes it:** the email carries both, and the code can be typed into whatever
device you actually want to use. Same login attempt, two redemption paths.

---

## ⚠️ The gotcha that will break a naive build: email clients PREFETCH links

Outlook Safe Links, Gmail's proxy, and corporate scanners will **GET every link in your
email before the human ever sees it.**

That means a naive design silently self-destructs:

- an **approve** link that approves on GET → **auto-approved by a scanner**
- a **magic link** that is single-use and consumes on GET → **burned before Bob clicks it**,
  and Bob sees "this link has expired"

**The fix — never perform an action on GET:**

| link | GET does | the action is |
|---|---|---|
| **Approve** | shows *"Approve Bob (bob@x.com)?"* + a button | a **POST** |
| **Magic link** | shows *"Sign in as bob@x.com"* + a button | a **POST** |

Prefetchers issue GETs, not POSTs. One extra click, and it is immune.

**And the code is the belt to that braces:** even if a scanner somehow burns the link, Bob
can still type the code. The two mechanisms cover each other.

---

## Portability: how mail gets sent

**This is the part you asked for, and the answer is SMTP.**

**Every provider speaks SMTP.** Gmail, Fastmail, iCloud, Resend, Postmark, SES, Mailgun, a
self-hosted Postfix. Support SMTP and you support all of them, forever.

```
interface EmailSender:
    send(to, subject, text, html) -> ok | error

backends:
    smtp      ← THE portable one. host / port / user / pass / from
    console   ← dev: print to stdout, no mail at all
    (resend | postmark | ses | mailgun — optional HTTP APIs, only if you ever want
     their analytics/deliverability extras. Not required.)
```

Swapping providers = changing three env vars. **No code change, no lock-in.**

```
MAIL_BACKEND=smtp
SMTP_HOST=...   SMTP_PORT=587   SMTP_USER=...   SMTP_PASS=...
MAIL_FROM="jam-station <jam@runslab.run>"
```

### ⚠️ Do NOT send mail directly from the mac-mini

It will land in spam or be dropped outright:

- **residential IPs are on blocklists** — permanently, not because of anything you did
- most ISPs **block outbound port 25**
- no **SPF / DKIM / DMARC** → spam folder

**So: the interface is SMTP, but the transport is a real provider's SMTP endpoint.** You get
portability *and* deliverability, with no contradiction.

And you're well set up for it: **you own `runslab.run` and its DNS is on Cloudflare.** Add
SPF/DKIM/DMARC there and mail from `jam@runslab.run` is properly authenticated and lands in
the inbox.

> **The rule:** portable *interface* (SMTP), reputable *transport* (any provider),
> authenticated *domain* (runslab.run).

---

## Who can even ask (spam control)

The `/join` page **requires a valid invite token**. No token → no signup form.

Without this, `/join` is a public form that lets **anyone on the internet flood your inbox**
with approval requests.

- Invite links are **reusable and revocable** — so you can text one to the family group chat
  and kill it later.
- Optionally single-use, if you want to know exactly who you handed it to.
- Rate-limit request submissions by IP regardless.

---

## Data model

```
members
  email        TEXT PK       -- lowercased. THE identity. no usernames, no passwords.
  name         TEXT
  role         TEXT          -- owner | member | broadcaster
  status       TEXT          -- pending | approved | revoked
  created_at, approved_at, approved_by

invites
  token_hash   TEXT PK
  label        TEXT          -- "family group chat"
  created_by, expires_at, revoked_at

login_attempts               -- one row per "let me in" request
  token_hash   TEXT          -- the magic link
  code_hash    TEXT          -- the typeable code
  email        TEXT
  expires_at   TEXT          -- 15 minutes
  used_at      TEXT          -- single use
  attempts     INT           -- lock after 5

sessions                     -- SERVER-SIDE, so they can be revoked
  id_hash      TEXT PK
  email        TEXT
  created_at, expires_at     -- 30 days
  last_seen, user_agent      -- enables "sign out my other devices"

station_access               -- (schema now, feature later)
  station      TEXT
  email        TEXT          -- absent = all approved members
```

**Store hashes, never the raw tokens/codes.** A database leak must not be a set of working
logins.

**Server-side sessions, not JWTs** — because the entire point is that **you can revoke
access.** A stateless JWT can't be revoked without a blocklist, at which point you have a
sessions table anyway, but worse.

---

## Codes: make them safe *and* typeable

- **8 chars, unambiguous alphabet** (no `0/O`, no `1/I/L`) — e.g. `K7M2-9XPQ`
- **15 minute** expiry
- **5 attempts**, then the attempt is dead and a new email is required
- tied to the **email** — an attacker must know the address *and* win the guess

A 6-digit numeric code is 1M combinations. With rate limiting that's *probably* fine, but 8
alphanumeric chars is trillions and costs the user nothing extra. Take the free win.

---

## "Broadcast node" vs "affiliate node" (your terms)

| | **broadcast center** (your mac-mini) | **affiliate node** (dad's Mac) |
|---|---|---|
| runs | brain, icecast, member list, sends the mail | a source client — broadcasts *into* the center |
| owns | **membership for the whole network** | **their own station** |
| controls | who is in the network at all | *(later)* who may hear **their** station |

**v1: the center owns membership; every approved member can hear every private station.**

`station_access` is in the schema so a broadcaster can later restrict *their own* station to
named people — **without a migration.** Design it in, build it when someone asks.

---

## The principle

> **Identity enhances. It never gates.**

**Nobody logs in to listen to the radio.**

| | anonymous (today's experience) | signed in |
|---|---|---|
| public stations (archive tapes) | ✅ | ✅ |
| favourites | localStorage, **per-browser** | **follow you across devices** |
| listen history | ✗ | **what *you* heard** |
| private / family stations | ✗ | ✅ |
| dad sees | `1 listener` | **"Jason is listening"** |

So this is **additive**. The app keeps working untouched for anyone who never signs in.

---

## What identity unlocks (and why it isn't optional)

Three things are **already broken or hollow** without it:

1. **Your favourites don't follow you — today.** localStorage means your phone and your
   laptop have two different lists *right now*.
2. **"Recently played" is the station's log, not yours.** You flagged this as confusing
   hours ago. "What *I* heard" is impossible without identity.
3. **"1 listener" is a number, not a name.** icecast gives counts for free — it does **not**
   give you *"Jason."* And **dad seeing that his son is listening is the entire emotional
   point of the family network.**

### The architectural consequence

For dad to see a **name**, the listener must pass through something that knows who they are.

**Listeners already go through the brain's `/stream` proxy** (built for CORS/Web Audio).
That proxy is therefore the **identity chokepoint**.

> **The brain must remain the listening path.** If listeners ever hit icecast directly, named
> listeners become impossible.

Then dad's app simply asks the brain *"who's listening to my mount?"* → **"Jason."**

---

## Open questions

- **Does the owner need to sign in to approve?** The approve link is signed + single-use and
  lands in *his* inbox. I lean **no login** (one tap from a phone) — but the action must be a
  POST behind a confirm page (see the prefetch gotcha).
- **Household / shared devices?** A kitchen speaker isn't a person. Probably a long-lived
  device token, not a member. Not designed.
- **Does dad approve his own listeners, or does the center?** v1: the center. `station_access`
  makes the other answer possible later.
