# HUMAN_GATES.md: The Two Irreducible Cloud Gates

## 1. Executive Summary
The workflow operates as an autonomous **GitHub Bounty Hunter** that runs 24/7 in the cloud via GitHub Actions. It scans verified open-source repositories for bounties, clones the target repo, reads the real files, generates context-aware code patches using an LLM, and submits pull requests to claim payouts.

To activate 24/7 autonomous cloud execution, exactly **TWO irreducible human gates** are required:

| Gate | Name | Purpose | Active Time | Where Configured |
| :--- | :--- | :--- | :--- | :--- |
| **Gate 1** | **GitHub PAT & Remote Push** | Cloud hosting, Actions runner permissions & GitHub API quota | ~2 minutes | GitHub Repo + CLI push |
| **Gate 2** | **LLM API Key** | AI code fix synthesis (Gemini or OpenAI) | ~1 minute | GitHub Actions Secrets |

---

## 2. Irreducible Gate 1: Remote Repository Linking & GitHub PAT

### Why It Cannot Be Automated:
- GitHub account creation and remote repository provisioning require human authentication and anti-bot verification.

### Step-by-Step Instructions:

#### Step 1: Create a Remote Repository
1. Navigate to [github.com/new](https://github.com/new).
2. Enter repository name: `tenderpulse-bounty-hunter`.
3. Choose **Private** (recommended) or **Public**.
4. Click **Create repository** (do not initialize with README or license).

#### Step 2: Push Local Code to GitHub
Open a terminal in `c:\Users\Bensa\OneDrive\Desktop\DeepSeek OpenCode Harness\tenderpulse` and run:
```powershell
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/tenderpulse-bounty-hunter.git
git branch -M master
git push -u origin master
```

#### Step 3: Enable Actions Read & Write Permissions
1. In your GitHub repository, go to **Settings** > **Actions** > **General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Check **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

---

## 3. Irreducible Gate 2: LLM API Key (Gemini or OpenAI)

### Why It Cannot Be Automated:
- High-quality code patches require an advanced reasoning model. AI providers (Google AI Studio, OpenAI) require human developer registration and API key generation.

### Step-by-Step Instructions:

1. Obtain an API key from either provider:
   - **Google Gemini (Recommended — Free Tier available):** [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   - **OpenAI:** [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. In your GitHub repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**.
4. Add your secret:
   - Name: `GEMINI_API_KEY` (or `OPENAI_API_KEY`)
   - Secret: Paste your actual API key
5. Click **Add secret**.

*(Optional for local testing)*: You can also paste this key into `tenderpulse/.env` as `GEMINI_API_KEY=...` or `OPENAI_API_KEY=...` to test real LLM patches locally before cloud runs.

---

## 4. Operating Protections & Financial Thresholds
- **24/7 Execution:** GitHub Actions runs live every 6 hours (`0 */6 * * *`).
- **Operating Cost:** **$0.00 / month** on GitHub Actions free tier.
- **Budget Guard:** Hard monthly spend limit of **$5.00** strictly enforced in code. If monthly spend hits $5.00, inference halts immediately until the next calendar month.
- **Spam Guard:** Limited to **1 live PR per cycle**, targeting repositories with **$\ge 10$ stars**, and strictly blocking aggregator spam repos (`bounty-plaza`, `BountyScout`).
- **Revenue Target:** Solving just 1 modest bounty per month ($25.00 to $150.00) nets **$\ge \$20.00 / \text{month}$**, completely fulfilling the Prime Directive.
