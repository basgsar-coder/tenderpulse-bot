# TenderPulse: Autonomous B2B Tender & Grant Telemetry Engine

TenderPulse is an automated procurement intelligence pipeline designed to ingest, score, deduplicate, and publish high-yield government RFPs, federal grants, and commercial tech contracting leads.

---

## 1. Deployment Architecture: Cloud vs. Local Reality

### Primary Target: Option A — True 24/7 Cloud Execution (DEFAULT)
- **Runtime:** GitHub Actions Scheduled Cron (`.github/workflows/tenderpulse_cron.yml`).
- **Schedule:** Triggers every 4 hours (`0 */4 * * *`).
- **Cost:** $0.00 / month (consumes ~180 minutes of GitHub's 2,000 free monthly minutes).
- **Autonomy:** **True 24/7 execution**. Runs continuously in the cloud independent of whether the user's computer is on, asleep, or offline.
- **Activation:** Push this repository to GitHub via the one-line remote command.

### Secondary Target: Option B — Local Development & Testbed
- **Runtime:** Local Windows Task Scheduler or background process (`run_daemon.ps1`).
- **Limitation:** **Runs ONLY while the host machine is awake and powered on — this is NOT 24/7 autonomy.**
- **Usage:** Strictly intended for dry-run verification, local development, and test suite execution.

---

## 2. Inbound Monetization & Distribution
- **Target Revenue:** $\ge \$20.00 / \text{month}$ net profit (Formula: 1 subscriber @ $29.00/mo - $1.14 fee = $27.86/mo net).
- **Inbound Distribution:** Listed on **RapidAPI Hub** and **Apify Store** to capture inbound developer and enterprise demand without manual cold outreach.
- **Compliance & Hard Limits:** See [HUMAN_GATES.md](file:///c:/Users/Bensa/OneDrive/Desktop/DeepSeek%20OpenCode%20Harness/HUMAN_GATES.md) for full disclosure of KYC bank requirements and realistic approval latency (0–72 hours).
- **Demand Proof:** See [DEMAND_PROOF.md](file:///c:/Users/Bensa/OneDrive/Desktop/DeepSeek%20OpenCode%20Harness/DEMAND_PROOF.md) for 10 verified buyers and 3 direct competitors charging $\ge \$29/\text{mo}$.

---

## 3. Security Hardening
- **Git Protection:** `.env`, `*.key`, `*.pem`, and `tenderpulse.db` are strictly gitignored.
- **Pre-commit Guard:** Enforces automated scanning on every commit. Tracked files containing private keys or secret keys cause commit rejection.
- **Filesystem Security:** `.env` is ACL-restricted (`icacls .env /inheritance:r /grant:r "%USERNAME%:F"`).
