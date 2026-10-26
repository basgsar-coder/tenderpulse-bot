# HUMAN_GATES.md: Red Team Hardened Cloud Deployment Gates

## 1. Overview & Security Architecture
TenderPulse is an automated 24/7 **GitHub Bounty Hunter** that discovers verified open-source bounties (Algora & IssueHunt), validates patches against target repositories via `git apply --check`, enforces strict monthly budget limits ($5.00), and posts resolution pull requests.

To activate 24/7 cloud execution on GitHub Actions, the user must provide two secrets:

| Secret Name | Purpose | Scope / Source | Where to Configure |
| :--- | :--- | :--- | :--- |
| **`BOUNTY_BOT_TOKEN`** | Submit PRs and comments to external bounty repos | GitHub Classic PAT with `public_repo` scope | GitHub Repository Secrets |
| **`GEMINI_API_KEY`** (or `OPENAI_API_KEY`) | LLM code patch synthesis engine | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | GitHub Repository Secrets |

---

## 2. Gate 1: Remote Repository Linking & BOUNTY_BOT_TOKEN

### Why It Cannot Be Automated:
- GitHub Actions default `GITHUB_TOKEN` is strictly scoped to the host repository; submitting comments or PRs to *third-party* open-source repositories requires an authenticated Personal Access Token (`BOUNTY_BOT_TOKEN`).

### Step-by-Step Instructions:

#### Step 1: Create a Repository on GitHub
1. Navigate to [github.com/new](https://github.com/new).
2. Enter repository name: `tenderpulse-bounty-hunter` (Private recommended).
3. Click **Create repository**.

#### Step 2: Push Local Code to GitHub
Open a terminal in `c:\Users\Bensa\OneDrive\Desktop\DeepSeek OpenCode Harness\tenderpulse` and run:
```powershell
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/tenderpulse-bounty-hunter.git
git branch -M master
git push -u origin master
```

#### Step 3: Generate & Add BOUNTY_BOT_TOKEN
1. Navigate to [github.com/settings/tokens](https://github.com/settings/tokens) > **Generate new token (classic)**.
2. Select scope: **`public_repo`** (Access public repositories).
3. Generate and copy the token.
4. In your GitHub repository, navigate to **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
   - Name: `BOUNTY_BOT_TOKEN`
   - Secret: Paste the token.
   - Click **Add secret**.

---

## 3. Gate 2: LLM API Key (Gemini or OpenAI)

1. Obtain an API key:
   - **Google Gemini (Free tier available):** [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   - **OpenAI:** [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. In your GitHub repository, go to **Settings** > **Secrets and variables** > **Actions** > **New repository secret**:
   - Name: `GEMINI_API_KEY` (or `OPENAI_API_KEY`)
   - Secret: Paste your API key.
   - Click **Add secret**.

---

## 4. Operational Guardrails
- **Execution Schedule:** Every 6 hours (`0 */6 * * *`).
- **Timeout Protection:** 20-minute workflow execution cap.
- **Concurrency Lock:** Cancels overlapping runner collisions.
- **Budget Guard:** Hard monthly cap of **$5.00** strictly locked with file locking and fail-closed state validation.
- **Submission Limits:** Maximum **3 submissions per day** and **7-day cooldown per repository**.
- **Payout Notification:** Every solved bounty outputs a manual claim link: `[PAYOUT] Manual claim required for {platform}: {claim_url}`.
