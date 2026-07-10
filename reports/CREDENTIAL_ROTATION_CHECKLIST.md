# Credential Rotation Checklist — committed-secrets exposure (2026-07-10)

**Author:** cc5 · **Status:** OPEN — every item below requires human action unless marked done
**Trigger:** alert-bot cred rotation revealed that real `.env` files were tracked in the pushed GitHub repo (`attix-intelligence/attix-credit-spreads`) since **2026-03-13**.
**Containment already applied (cc5, 2026-07-10):** files untracked + `.gitignore` hardened (commit `2005008`, pushed); scanner alert channel repointed to the gateway bot and verified end-to-end. **Git history still contains every value below** — untracking stops new exposure only.

> ⚠️ No secret values appear in this file. Everything is referenced by env-var name + last-4 characters. The full values are in git history (hence this checklist) and in the local untracked `.env.*` files on the worker box.

---

## 1. Exposed credentials inventory

Exposure = present in git history of the GitHub repo; visible to anyone with repo read access (repo is private; audit collaborator list + any CI/token access as part of remediation).

| # | Credential | Where committed | Last-4 | In history since | Exposure window |
|---|---|---|---|---|---|
| 1 | `RAILWAY_ADMIN_TOKEN` | `.env.sync` | `…2026` | 2026-03-22 (`441b9e8`) | ~3.5 months |
| 2 | GitHub PAT (in local git remote URL, **not** in repo) | `.git/config` on worker box (and any clone using the same remote URL) | `…bvbz` | n/a (local) | box-access scope |
| 3 | `ALPACA_API_KEY`/`_SECRET` pair A (champion + exp036) | `.env.champion`, `.env.exp036` | key `…4OYQ` / secret `…gTCh` | 2026-03-13 (`70c8519`) | ~4 months |
| 4 | Alpaca pair B (exp059) | `.env.exp059` | `…FOAH` / `…jzJ1` | 2026-03-15 (`db03dab`) | ~4 months |
| 5 | Alpaca pair C (exp154) | `.env.exp154` | `…LSCR` / `…Qp4J` | 2026-03-15 | ~4 months |
| 6 | Alpaca pair D (exp305) | `.env.exp305` | `…ELCB` / `…uiZX` | 2026-03-15 | ~4 months |
| 7 | Alpaca pair E (exp400) | `.env.exp400` | `…JJ23` / `…xYNo` | 2026-03-20 (`d5e6319`) | ~3.5 months |
| 8 | Alpaca pair F (exp401) | `.env.exp401` | `…JGJ4` / `…GKwb` | 2026-03-13 (`70c8519`, per `8117236` "add Telegram bot credentials to exp400/exp401") | ~4 months |
| 9 | Alpaca pair G (expv8a) | `.env.expv8a` | `…KRY3` / `…5e4h` | 2026-05-27 (`8c7a6e8`) | ~6 weeks |
| 10 | `POLYGON_API_KEY` (one key, shared across files) | `.env.champion`, `.env.exp036/059/154/305`, `.env.expv8a` | `…YDCH` | 2026-03-13 | ~4 months |
| 11 | `TELEGRAM_BOT_TOKEN` (repo alert bot) | `.env.champion` | `…wIME` | 2026-03-13 | ~4 months; bot also **blocked by Carlos**, so alerts using it were silently failing (403) |

Not exposed in the repo but referenced for completeness: the OpenClaw **gateway bot token** now lives in the local untracked `.env.champion` (interim alert route, added 2026-07-10). It must never be committed — the new `.gitignore` rules cover it, but keep it in mind during any future env-file restructuring.

## 2. Rotation actions, in priority order

**P0 — infrastructure control (do first):**
1. **Rotate `RAILWAY_ADMIN_TOKEN`** (`…2026`). This is an admin-scope token for the deployment platform running the live Tradier executor — the highest-blast-radius item on this list. Revoke in Railway dashboard → generate new → update wherever `.env.sync` consumers run.
2. **Rotate the GitHub PAT** (`…bvbz`). It is embedded in the remote URL in local `.git/config` (worker box). Revoke at github.com/settings/tokens, mint a fine-grained replacement (repo-scoped), update the remote URL (`git remote set-url origin https://<newtoken>@github.com/attix-intelligence/attix-credit-spreads.git`) on every box/clone that uses it.

**P1 — market/broker keys:**
3. **Rotate all 7 Alpaca paper key pairs** (rows 3–9): Alpaca dashboard → each paper account → regenerate API keys. These are paper accounts (no direct funds risk) but grant order-placement + full trade/position/history read on the fleet. After rotation, update the local untracked `.env.*` files and the matching per-experiment Railway env vars (see §3).
4. **Rotate `POLYGON_API_KEY`** (`…YDCH`): polygon.io dashboard → API keys. One key is shared program-wide, so coordinate the swap (local `.env.*` + Railway) to avoid a data blackout for the paper scanners.

**P2 — messaging:**
5. **Revoke the old alert bot token** (`…wIME`) via @BotFather (`/revoke`). Note: rotation does not fix delivery — Carlos blocked the bot itself. Either keep alerts on the gateway-bot route (current interim state), have Carlos unblock the old bot after revoke+reissue, or mint a fresh bot. Decide the permanent alert route and record it in the runbook.

## 3. Railway env-var updates after rotation

Deployed workers read **Railway-injected env vars**, not the committed files — deploys were never reading the exposed copies, but several of the same values are (or may be) mirrored in Railway service env. After each rotation above, update the corresponding vars on the affected services (attix-worker per-experiment unmasking pattern):

- `ALPACA_API_KEY_<EXP>` / `ALPACA_API_SECRET_<EXP>` for each rotated pair (e.g. `…_EXP800`, `…_EXP400`, …)
- `POLYGON_API_KEY` (all scanner services)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (whichever alert route is chosen in §2.5)
- Any consumer of the old `RAILWAY_ADMIN_TOKEN`

Then restart/redeploy affected services and watch the first scan cycle for auth failures. **Do not touch the Tradier live service env (`TRADIER_PROD_TOKEN`) — it was not part of this exposure** (verify separately that it appears nowhere in git history before closing this checklist: `git log -S TRADIER_PROD_TOKEN --oneline -- ':!*.md'` should show config-name references only, no values).

## 4. Git-history scrub (optional but recommended)

Untracking removed the files from HEAD only; all values remain retrievable from history (`git show 70c8519:.env.champion` etc.).

- **If all P0–P2 rotations are completed, scrubbing is defense-in-depth, not urgent** — the historical values become dead. Rotation is the primary control; treat scrub as cleanup.
- To scrub: `git filter-repo --invert-paths --path .env.champion --path .env.exp036 --path .env.exp059 --path .env.exp154 --path .env.exp305 --path .env.exp400 --path .env.exp401 --path .env.expv8a --path .env.sync` (or BFG), then force-push and have **every** working clone re-clone — this rewrites all SHAs after 2026-03-13, which breaks the SHA references used throughout the experiment reports. Given the repo is private and rotation kills the values, weigh that cost; if scrubbing, do it in a single coordinated window across all cc sessions.
- Also audit: GitHub repo collaborator list, any GitHub Actions/apps with repo read, and existing forks/clones.

## 5. Verification / close-out

- [ ] Railway admin token rotated + consumers updated
- [ ] GitHub PAT revoked + remote URLs updated on all boxes
- [ ] 7 Alpaca pairs rotated + local `.env.*` + Railway vars updated + scanners auth OK on next cycle
- [ ] Polygon key rotated + updated everywhere + data fetch OK
- [ ] Old Telegram bot token revoked; permanent alert route decided and documented
- [ ] `TRADIER_PROD_TOKEN` confirmed absent from git history
- [ ] Collaborator/app access audit done
- [ ] (Optional) history scrub decision recorded; if yes, executed + all clones refreshed
- [x] Env files untracked + `.gitignore` hardened (`2005008`, 2026-07-10, cc5)
- [x] Alert delivery restored via gateway bot, verified end-to-end (2026-07-10, cc5)
