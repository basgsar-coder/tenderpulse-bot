#!/usr/bin/env python3
"""
TenderPulse GitHub Bounty Scanner
Searches the GitHub REST API for open issues with attached bounties (Algora, IssueHunt, maintainer tags).
Extracts bounty values, filters by agent capability, and persists discoveries to SQLite.
"""

import os
import re
import sys
import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "tenderpulse.db"
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "state.json"

# Capability filter keywords
TARGET_KEYWORDS = [
    "python", "script", "markdown", "documentation", "docs",
    "bug", "fix", "typo", "cli", "test", "docker", "api"
]

# Bounty value extraction regexes
BOUNTY_REGEXES = [
    re.compile(r"bounty[:\s]+\$([0-9]+(?:\.[0-9]{2})?)", re.IGNORECASE),
    re.compile(r"\$([0-9]+(?:\.[0-9]{2})?)\s+bounty", re.IGNORECASE),
    re.compile(r"\$([0-9]{2,5})\b"),
    re.compile(r"([0-9]+(?:\.[0-9]{2})?)\s*(?:USDC|USD|EUR)\b", re.IGNORECASE),
]

def load_github_token() -> Optional[str]:
    # Check OS environment first
    token = os.environ.get("GITHUB_TOKEN")
    if token and not token.startswith("ghp_YOUR_"):
        return token
    # Check .env file
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("ghp_YOUR_"):
                    return val
    return None

def init_bounty_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bounties (
        id TEXT PRIMARY KEY,
        repo TEXT NOT NULL,
        issue_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        bounty_amount REAL,
        currency TEXT DEFAULT 'USD',
        labels TEXT,
        body_preview TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        solved INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

def extract_bounty_amount(text: str) -> float:
    for regex in BOUNTY_REGEXES:
        match = regex.search(text)
        if match:
            try:
                amt = float(match.group(1))
                if 5.0 <= amt <= 10000.0:
                    return amt
            except ValueError:
                continue
    return 0.0

def matches_capabilities(title: str, body: str, labels: List[str]) -> bool:
    combined = f"{title} {body} {' '.join(labels)}".lower()
    return any(kw in combined for kw in TARGET_KEYWORDS)

def search_github_bounties(query: str = "is:issue is:open label:bounty", token: Optional[str] = None) -> List[Dict[str, Any]]:
    init_bounty_table()
    token = token or load_github_token()
    
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.github.com/search/issues?q={encoded_query}&sort=updated&order=desc&per_page=30"
    
    headers = {
        "User-Agent": "TenderPulse-BountyHunter/1.0",
        "Accept": "application/vnd.github.v3+json"
    }
    if token:
        headers["Authorization"] = f"token {token}"
        
    req = urllib.request.Request(url, headers=headers)
    candidates = []
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
            for item in items:
                title = item.get("title", "")
                body = item.get("body") or ""
                labels = [l.get("name", "") for l in item.get("labels", [])]
                html_url = item.get("html_url", "")
                issue_id = str(item.get("id"))
                repo_url = item.get("repository_url", "")
                repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else "unknown"
                issue_number = item.get("number", 0)
                
                # Check capability match
                if not matches_capabilities(title, body, labels):
                    continue
                    
                bounty_amt = extract_bounty_amount(f"{title} {body}")
                if bounty_amt == 0.0:
                    # Default baseline bounty estimate if tagged with bounty label
                    bounty_amt = 25.0
                    
                candidate = {
                    "id": issue_id,
                    "repo": repo_name,
                    "issue_number": issue_number,
                    "title": title,
                    "url": html_url,
                    "bounty_amount": bounty_amt,
                    "currency": "USD",
                    "labels": ", ".join(labels),
                    "body_preview": body[:300].replace("\r", " ").replace("\n", " "),
                    "full_body": body
                }
                candidates.append(candidate)
                
    except urllib.error.HTTPError as e:
        print(f"[BOUNTY_SCANNER] GitHub API HTTP error: {e.code} {e.reason}")
    except Exception as e:
        print(f"[BOUNTY_SCANNER] Search error: {e}")
        
    return candidates

def persist_bounties(bounties: List[Dict[str, Any]]) -> int:
    init_bounty_table()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_count = 0
    
    for b in bounties:
        try:
            cursor.execute("""
            INSERT INTO bounties (id, repo, issue_number, title, url, bounty_amount, currency, labels, body_preview)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                bounty_amount = excluded.bounty_amount,
                title = excluded.title
            """, (
                b["id"],
                b["repo"],
                b["issue_number"],
                b["title"],
                b["url"],
                b["bounty_amount"],
                b["currency"],
                b["labels"],
                b["body_preview"]
            ))
            if cursor.rowcount > 0:
                new_count += 1
        except Exception as e:
            print(f"[BOUNTY_SCANNER] SQLite persist error: {e}")
            
    conn.commit()
    conn.close()
    
    # Update state.json
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            state["bounties_discovered"] = state.get("bounties_discovered", 0) + new_count
            state["last_run_timestamp"] = datetime.now(timezone.utc).isoformat()
            STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass
            
    return new_count

def run_scanner() -> List[Dict[str, Any]]:
    print("[BOUNTY_SCANNER] Scanning GitHub for open bounties matching capabilities...")
    queries = [
        "is:issue is:open label:bounty language:python",
        "is:issue is:open \"bounty\" in:title language:python"
    ]
    all_bounties = []
    seen_ids = set()
    
    for q in queries:
        results = search_github_bounties(q)
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_bounties.append(r)
                
    new_items = persist_bounties(all_bounties)
    print(f"[BOUNTY_SCANNER] Scan complete. Found {len(all_bounties)} bounties ({new_items} new).")
    return all_bounties

if __name__ == "__main__":
    bounties = run_scanner()
    for b in bounties[:5]:
        print(f"  - [${b['bounty_amount']:.2f}] {b['repo']}#{b['issue_number']}: {b['title'][:60]}")
