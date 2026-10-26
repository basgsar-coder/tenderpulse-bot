# HUMAN_GATES.md: The Single Irreducible Gate

## 1. Executive Summary
Following the authorization to pivot to the **GitHub Bounty Hunter** workflow, all fiat banking, FinCEN KYC, and merchant account requirements have been eliminated. Payouts for open-source bug bounties (via Algora, IssueHunt, and GitHub Sponsors) are disbursed directly by the bounty platforms to your designated payout address or wallet without requiring you to run merchant acquiring infrastructure.

The entire workflow has been reduced to **exactly ONE irreducible human gate**.

---

## 2. Gate 1 (The Single Gate): GitHub Personal Access Token (PAT)

### Why It Cannot Be Automated:
- GitHub requires human-verified accounts with anti-bot/CAPTCHA protection to generate Personal Access Tokens (PATs).
- Programmatic token generation requires pre-existing credentials.

### The Single Irreducible Step:
1. Generate a GitHub Personal Access Token (Classic) at [github.com/settings/tokens](https://github.com/settings/tokens) with the following scopes:
   - `repo` (Full control of private and public repositories)
   - `workflow` (Update GitHub Action workflows)
2. Open [.env](file:///c:/Users/Bensa/OneDrive/Desktop/DeepSeek%20OpenCode%20Harness/tenderpulse/.env) and set:
   ```env
   GITHUB_TOKEN=ghp_YOUR_TOKEN_HERE
   ```
3. Save the file. 

### Why This Gate Solves Everything:
- **Deployment:** The same token enables pushing the local repository to GitHub and triggering the 24/7 GitHub Actions cron.
- **Execution:** The token provides 5,000 requests/hour on the GitHub REST API and authorizes submitting automated fix pull requests to claim bounties.
- **Time Required:** ~2 minutes, one-time action.
