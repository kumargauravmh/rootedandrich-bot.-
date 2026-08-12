# @rootedand.rich — Fully Automated Daily Poster

This repo posts to Instagram automatically, 3 times a day — with **near-$0
recurring cost** and **zero ongoing effort** once it's set up.

## How it works
1. GitHub Actions wakes up on a timer, 3 times a day (free, built into GitHub).
2. It asks Google's free Gemini AI to write a brand-new post — fresh text,
   fresh caption, fresh hashtags, never repeating.
3. If that AI call ever fails for any reason, it safely falls back to one of
   30 pre-written posts instead, so a post always goes out either way.
4. It commits the image to this repo so it has a public URL.
5. It calls Instagram's official Graph API to publish that image + caption.

## One-time setup

Follow the original setup guide (RootedAndRich_Complete_Setup_Guide.md) for
Phases 1–9 (Instagram professional account, Meta developer app, GitHub repo,
Instagram Tester access, IG_USER_ID and IG_ACCESS_TOKEN secrets).

**One additional step for live AI generation:**

1. Go to **aistudio.google.com** and sign in with any Google account —
   genuinely free, no credit card, ever.
2. Click **"Get API key"** → **"Create API key."**
3. Copy the key it gives you.
4. In your GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret.**
5. Name: `GEMINI_API_KEY`, Value: (the key you just copied) → Add secret.

That's it — once this secret exists, every post from here on is freshly
written by AI. If you skip this step entirely, the system still works fine
using the 30 pre-written posts on a 10-day rotation.

## Costs
- GitHub Actions: free
- GitHub image hosting: free
- Instagram Graph API: free
- Gemini AI generation: free (1,500 requests/day allowed; you use 3)
- **Total: $0/month**

