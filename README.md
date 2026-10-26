# TenderPulse: Autonomous GitHub Bounty Hunter

TenderPulse is an autonomous system engineered to operate 24/7 via GitHub Actions. It scans verified open-source repositories for issues tagged with bounties, clones the target codebase, reads referenced source files, generates contextual unified diff patches via LLM (Gemini / OpenAI), and submits pull requests to claim rewards.

---

## 1. System Architecture

```text
GitHub Search API (stars:>=10, spam-filtered)
       │
       ▼
bounty_scanner.py ───► SQLite DB (tenderpulse.db)
       │
       ▼
solver.py ───────────► clones target repo (shallow depth=1)
       │               reads target source file context
       │               evaluates $5.00 monthly budget guard
       │               queries LLM (Gemini / OpenAI)
       │               generates valid unified diff (.patch)
       ▼
main.py ─────────────► submits Pull Request / fix comment to GitHub
       │
       ▼
GitHub Actions ──────► commits telemetry & state back to repo
```

---

## 2. Key Safeguards & Defenses

1. **Anti-Spam Repository Blocklist:** Automatically skips known bounty aggregators and spam clones (`bounty-plaza`, `BountyScout`, etc.) and enforces a strict `stars:>=10` threshold.
2. **Hard Monthly Budget Guard ($5.00):** Every LLM call verifies `state.json`. If monthly spend exceeds **$5.00 USD**, inference halts immediately to protect operating margin.
3. **Repository Depth Control:** Clones with `--depth 1` into isolated temporary directories and automatically cleans up upon completion.
4. **Credential Security:** `.env`, private keys, and databases are strictly gitignored and OS ACL-restricted. Local git pre-commit hooks reject commits containing exposed secrets.
5. **Rate Limiting:** Live submissions are capped at **1 PR per 6-hour cycle** to prevent aggressive submission volume.

---

## 3. The Two Human Gates to Cloud Activation

To activate 24/7 execution in GitHub Actions:

### Gate 1: Remote Repository Linking (~2 minutes)
1. Create a repository on [github.com/new](https://github.com/new).
2. Push local code:
   ```powershell
   git remote add origin https://github.com/<YOUR_USER>/<REPO>.git
   git branch -M master
   git push -u origin master
   ```
3. Enable Actions permissions in GitHub: **Settings** > **Actions** > **General** > **Workflow permissions** > **Read and write permissions** (and check "Allow GitHub Actions to create and approve pull requests").

### Gate 2: LLM API Key (~1 minute)
1. Get a Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free tier available) or OpenAI key.
2. Add to GitHub: **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
   - Name: `GEMINI_API_KEY` (or `OPENAI_API_KEY`)
   - Value: `<YOUR_KEY>`

---

## 4. Local CLI Usage

```powershell
# Run unit test suite (12 tests)
python -m unittest discover tests/

# Execute local dry-run cycle (scans live GitHub bounties, generates patches)
python main.py --dry-run --limit 1

# Execute live submission locally (requires GITHUB_TOKEN in .env)
python main.py --live --limit 1
```
