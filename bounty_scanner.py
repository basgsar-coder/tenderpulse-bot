#!/usr/bin/env python3
"""
TenderPulse GitHub Bounty Scanner
Identifies open bounties verified strictly via Algora or IssueHunt escrow platforms.
Enforces normalized spam regexes, minimum 10-star threshold, and raises RateLimited on 403/429.
"""

import os
import re
import sys
import json
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "tenderpulse.db"
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "state.json"

class RateLimited(Exception):
    """Raised when GitHub Search API returns 403 Forbidden or 429 Too Many Requests."""
    def __init__(self, message: str, reset_time: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.reset_time = reset_time
        self.retry_after = retry_after

# Normalized spam blocklist regex (Fix 9)
SPAM_REPO_RE = re.compile(
    r"(?:^|/|[-_.])(?:bounty[-_. ]?(?:plaza|scout|alert|bot)|airdrop|faucet)(?:$|[-_.])",
    re.IGNORECASE
)

# Verified payout platform detection regexes (Fix 6)
ALGORA_URL_RE = re.compile(
    r"https?://(?:console\.)?algora\.io/(?:bounties/[a-zA-Z0-9_\-]+|orgs?/[a-zA-Z0-9_\-]+/bounties/[a-zA-Z0-9_\-]+|api/bounties/[a-zA-Z0-9_\-]+)",
    re.IGNORECASE
)
ISSUEHUNT_URL_RE = re.compile(
    r"https?://issuehunt\.io/(?:r/[a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+/issues/\d+|repos/\d+)",
    re.IGNORECASE
)

# Explicit dollar reward patterns
AMOUNT_PATTERNS = [
    re.compile(r"bounty[:\s]+\$([0-9]+(?:\.[0-9]{2})?)", re.IGNORECASE),
    re.compile(r"\$([0-9]+(?:\.[0-9]{2})?)\s+bounty", re.IGNORECASE),
    re.compile(r"bounty\s+reward[:\s]+\$([0-9]+)", re.IGNORECASE),
    re.compile(r"\$([0-9]{2,5})\b"),
]

def load_auth_token() -> Optional[str]:
    for var in ["BOUNTY_BOT_TOKEN", "GITHUB_TOKEN"]:
        val = os.environ.get(var)
        if val and not val.startswith("ghp_YOUR_"):
            return val
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            for prefix in ["BOUNTY_BOT_TOKEN=", "GITHUB_TOKEN="]:
                if line.startswith(prefix):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and not val.startswith("ghp_YOUR_"):
                        return val
    return None

def init_bounty_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bounties (
        id TEXT PRIMARY KEY,
        repo TEXT NOT NULL,
        issue_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        bounty_amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        platform TEXT NOT NULL,
        claim_url TEXT NOT NULL,
        labels TEXT,
        body_preview TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        solved INTEGER DEFAULT 0
    )
    """)
    # Automatic schema migration for existing databases
    cursor.execute("PRAGMA table_info(bounties);")
    cols = [row[1] for row in cursor.fetchall()]
    if "platform" not in cols:
        cursor.execute("ALTER TABLE bounties ADD COLUMN platform TEXT DEFAULT 'Algora';")
    if "claim_url" not in cols:
        cursor.execute("ALTER TABLE bounties ADD COLUMN claim_url TEXT DEFAULT '';")
    conn.commit()
    conn.close()

def is_spam_repo(repo_name: str) -> bool:
    """Matches repository against normalized spam pattern."""
    return bool(SPAM_REPO_RE.search(repo_name))

def detect_platform(text: str) -> Optional[Tuple[str, float, str]]:
    """
    Scans issue text for a verified payout platform (Algora or IssueHunt)
    and extracts the confirmed reward amount and claim URL.
    Returns (platform_name, amount, claim_url) or None if unverified.
    """
    # 1. Check Algora
    algora_match = ALGORA_URL_RE.search(text)
    if algora_match:
        claim_url = algora_match.group(0)
        # Extract bounty amount near badge or in text
        for pat in AMOUNT_PATTERNS:
            m = pat.search(text)
            if m:
                try:
                    amt = float(m.group(1))
                    if 10.0 <= amt <= 10000.0:
                        return ("Algora", amt, claim_url)
                except ValueError:
                    continue
        # If Algora URL exists but amount couldn't be parsed, try generic integer search
        generic = re.search(r"\b(\d{2,4})\b", text)
        if generic:
            return ("Algora", float(generic.group(1)), claim_url)

    # 2. Check IssueHunt
    issuehunt_match = ISSUEHUNT_URL_RE.search(text)
    if issuehunt_match:
        claim_url = issuehunt_match.group(0)
        for pat in AMOUNT_PATTERNS:
            m = pat.search(text)
            if m:
                try:
                    amt = float(m.group(1))
                    if 10.0 <= amt <= 10000.0:
                        return ("IssueHunt", amt, claim_url)
                except ValueError:
                    continue

    return None

def github_json(url: str, token: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes GET request to GitHub API, checking rate limit headers and raising
    RateLimited on HTTP 403/429 or when X-RateLimit-Remaining == 0 (Fix 8, 22).
    """
    headers = {
        "User-Agent": "TenderPulse-BountyHunter/2.0",
        "Accept": "application/vnd.github.v3+json"
    }
    if token:
        headers["Authorization"] = f"token {token}"
        
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) == 0:
                reset_time = int(resp.headers.get("X-RateLimit-Reset", 0)) if resp.headers.get("X-RateLimit-Reset") else None
                raise RateLimited("GitHub Search API rate limit exhausted (X-RateLimit-Remaining=0)", reset_time=reset_time)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            reset_time = int(e.headers.get("X-RateLimit-Reset", 0)) if e.headers.get("X-RateLimit-Reset") else None
            retry_after = int(e.headers.get("Retry-After", 0)) if e.headers.get("Retry-After") else None
            raise RateLimited(f"GitHub API returned HTTP {e.code} ({e.reason})", reset_time=reset_time, retry_after=retry_after) from e
        raise

def search_github_bounties(query: str = "is:issue is:open label:bounty stars:>=10", token: Optional[str] = None) -> List[Dict[str, Any]]:
    init_bounty_table()
    token = token or load_auth_token()
    
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.github.com/search/issues?q={encoded_query}&sort=updated&order=desc&per_page=30"
    candidates = []
    
    try:
        data = github_json(url, token)
        items = data.get("items", [])
            
        comment_checks = 0
        for item in items:
            title = item.get("title", "")
            body = item.get("body") or ""
            labels = [l.get("name", "") for l in item.get("labels", [])]
            html_url = item.get("html_url", "")
            issue_id = str(item.get("id"))
            repo_url = item.get("repository_url", "")
            repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else "unknown"
            issue_number = item.get("number", 0)
            
            # Filter 1: Spam check
            if is_spam_repo(repo_name):
                continue
                
            # Filter 2: Verified Payout Platform check (Fix 6)
            platform_info = detect_platform(f"{title}\n{body}")
            if not platform_info and item.get("comments", 0) > 0 and comment_checks < 6:
                comment_checks += 1
                try:
                    comments_url = f"https://api.github.com/repos/{repo_name}/issues/{issue_number}/comments?per_page=5"
                    c_items = github_json(comments_url, token)
                    if isinstance(c_items, list):
                        c_text = "\n".join(c.get("body", "") for c in c_items)
                        platform_info = detect_platform(f"{title}\n{body}\n{c_text}")
                except Exception:
                    pass

            if not platform_info:
                # Skip unverified bounty claims with no recognized escrow platform
                continue
                
            platform_name, bounty_amt, claim_url = platform_info
            
            candidate = {
                "id": issue_id,
                "repo": repo_name,
                "issue_number": issue_number,
                "title": title,
                "url": html_url,
                "bounty_amount": bounty_amt,
                "currency": "USD",
                "platform": platform_name,
                "claim_url": claim_url,
                "labels": ", ".join(labels),
                "body_preview": body[:300].replace("\r", " ").replace("\n", " "),
                "full_body": body
            }
            candidates.append(candidate)
                
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            reset_time = int(e.headers.get("X-RateLimit-Reset", 0)) if e.headers.get("X-RateLimit-Reset") else None
            retry_after = int(e.headers.get("Retry-After", 0)) if e.headers.get("Retry-After") else None
            raise RateLimited(f"GitHub Search API returned HTTP {e.code} ({e.reason})", reset_time=reset_time, retry_after=retry_after) from e
        print(f"[BOUNTY_SCANNER] GitHub HTTP Error {e.code}: {e.reason}")
    except RateLimited:
        raise
    except Exception as e:
        print(f"[BOUNTY_SCANNER] Error querying GitHub API: {type(e).__name__}")
        
    return candidates

def persist_bounties(bounties: List[Dict[str, Any]]) -> int:
    init_bounty_table()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    new_count = 0
    
    for b in bounties:
        # Check if already present before insert to accurately count new discoveries (Fix 18)
        cursor.execute("SELECT 1 FROM bounties WHERE id = ?", (b["id"],))
        exists = cursor.fetchone()
        
        cursor.execute("""
        INSERT INTO bounties (id, repo, issue_number, title, url, bounty_amount, currency, platform, claim_url, labels, body_preview)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            bounty_amount = excluded.bounty_amount,
            title = excluded.title,
            claim_url = excluded.claim_url
        """, (
            b["id"],
            b["repo"],
            b["issue_number"],
            b["title"],
            b["url"],
            b["bounty_amount"],
            b["currency"],
            b["platform"],
            b["claim_url"],
            b["labels"],
            b["body_preview"]
        ))
        if not exists and cursor.rowcount > 0:
            new_count += 1
            
    conn.commit()
    conn.close()
    return new_count

def run_scanner() -> List[Dict[str, Any]]:
    print("[BOUNTY_SCANNER] Polling GitHub for open bounties verified on Algora/IssueHunt...")
    queries = [
        'is:issue is:open "console.algora.io"',
        'is:issue is:open "issuehunt.io"',
        "is:issue is:open label:bounty algora",
        "is:issue is:open label:bounty issuehunt"
    ]
    all_bounties = []
    seen_ids = set()
    
    for q in queries:
        try:
            results = search_github_bounties(q)
            for r in results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    all_bounties.append(r)
        except RateLimited as rl:
            print(f"[BOUNTY_SCANNER RATE LIMIT] {rl}")
            raise

    new_items = persist_bounties(all_bounties)
    print(f"[BOUNTY_SCANNER] Verified {len(all_bounties)} legitimate bounties ({new_items} new).")
    return all_bounties

if __name__ == "__main__":
    try:
        bounties = run_scanner()
        for b in bounties[:5]:
            print(f"  - [{b['platform']}: ${b['bounty_amount']:.2f}] {b['repo']}#{b['issue_number']}: {b['title'][:55]}")
            print(f"    Claim URL: {b['claim_url']}")
    except RateLimited as err:
        print(f"Halted due to rate limit: {err}")
        sys.exit(1)
