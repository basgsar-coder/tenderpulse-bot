# HUMAN_GATES.md: The Single Irreducible Gate & Remote Deployment

## 1. Executive Summary
The workflow has been refined into an automated **GitHub Bounty Hunter**. All fiat banking, KYC, and merchant account requirements have been eliminated. Payouts for open-source bug bounties (via Algora, IssueHunt, and GitHub Sponsors) disburse directly to your designated payout address or wallet without requiring you to run merchant acquiring infrastructure.

The entire workflow requires **exactly ONE irreducible human setup step**: linking your remote repository and authorizing GitHub Actions.

---

## 2. Gate 1 (The Single Gate): Remote Repository Linking & GitHub PAT

### Why It Cannot Be Automated:
- GitHub account creation and remote repository provisioning require human authentication and anti-bot verification.

### Step-by-Step Instructions (Takes ~2 minutes):

#### Step 1: Create a Repository on GitHub
1. Navigate to [github.com/new](https://github.com/new).
2. Enter repository name (e.g., `tenderpulse-bounty-hunter`) and select **Private** or **Public**.
3. Click **Create repository** (do not initialize with README).

#### Step 2: Push Local Repository to GitHub
Open a terminal in the `tenderpulse` directory and run:
```powershell
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPO_NAME>.git
git branch -M master
git push -u origin master
```

#### Step 3: Enable GitHub Actions Write Permissions
To allow the 24/7 cloud workflow to submit Pull Requests and persist state back to the repository:
1. In your GitHub repository, navigate to **Settings** > **Actions** > **General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Check **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

#### Step 4 (Optional for Local Live Mode): Set GITHUB_TOKEN in `.env`
If you wish to test live submissions locally before cloud scheduling triggers:
1. Generate a Personal Access Token (Classic) at [github.com/settings/tokens](https://github.com/settings/tokens) with `repo` and `workflow` scopes.
2. In `tenderpulse/.env`, set:
   ```env
   GITHUB_TOKEN=ghp_YOUR_TOKEN_HERE
   ```

---

## 3. Autonomous Execution & Cashflow Summary
- **Cloud Execution:** The GitHub Actions workflow (`.github/workflows/bounty_hunter.yml`) executes **live** every 6 hours (`0 */6 * * *`).
- **Cost:** **$0.00 / month** on GitHub free tier.
- **Safety Limit:** Maximum 1 live PR per cycle to prevent spam.
- **Budget Guard:** Hard monthly cap of **$5.00** strictly enforced in `solver.py`.
- **Target Revenue:** 1 solved bounty per month ($25.00–$250.00) nets $\ge \$20.00/\text{month}$, fulfilling the Prime Directive.
