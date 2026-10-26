#!/usr/bin/env python3
"""
TenderPulse Autonomous Credential & Environment Provisioner
Generates internal CSPRNG secrets and application config with zero human input.
Removes all synthetic/fake EVM wallet generation.
"""

import os
import sys
import secrets
import hashlib
import sqlite3
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
DB_FILE = BASE_DIR / "tenderpulse.db"

def generate_secrets():
    api_master_key = "tp_" + secrets.token_hex(24)
    jwt_secret = secrets.token_hex(32)
    webhook_secret = "whsec_" + secrets.token_hex(20)
    
    config = {
        "APP_NAME": "TenderPulse Autonomous Bounty Hunter",
        "APP_ENV": "production",
        "RUN_MODE": "autonomous_cloud",
        "API_MASTER_KEY": api_master_key,
        "JWT_SECRET": jwt_secret,
        "WEBHOOK_SECRET": webhook_secret,
        "MONTHLY_BUDGET_CAP": "5.00",
        "TARGET_MONTHLY_NET": "20.00",
        "MAX_SUBMISSIONS_PER_DAY": "3"
    }
    
    if not ENV_FILE.exists():
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            for k, v in config.items():
                f.write(f"{k}={v}\n")
            f.write("# BOUNTY_BOT_TOKEN=ghp_YOUR_TOKEN_HERE (Required for live submissions)\n")
            f.write("# GEMINI_API_KEY=your_key_here\n")
            f.write("# OPENAI_API_KEY=your_key_here\n")
        print(f"[PROVISION] .env generated at {ENV_FILE}")
    else:
        print(f"[PROVISION] .env already exists at {ENV_FILE}")
        
    return config

def init_database():
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
        bounty_amount REAL,
        currency TEXT DEFAULT 'USD',
        platform TEXT,
        claim_url TEXT,
        labels TEXT,
        body_preview TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        solved INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id TEXT NOT NULL,
        repo TEXT NOT NULL,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        pr_or_comment_url TEXT,
        status TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()
    print(f"[PROVISION] SQLite database initialized with WAL mode at {DB_FILE}")

if __name__ == "__main__":
    generate_secrets()
    init_database()
    print("[PROVISION] Provisioning complete.")
