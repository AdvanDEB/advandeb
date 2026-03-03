#!/usr/bin/env python3
"""
Seed an administrator user into MongoDB.

Usage (from app/backend/):
    python scripts/seed_admin.py
"""
import os
import sys
import getpass
from datetime import datetime
from pathlib import Path

# Load .env from app/backend/
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

import bcrypt
from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "advandeb")


def main():
    email = input("Admin email: ").strip()
    if not email:
        print("Email is required.")
        sys.exit(1)

    full_name = input("Full name (optional): ").strip() or None
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    client = MongoClient(MONGODB_URI)
    db = client[MONGODB_DB_NAME]
    users = db.users

    if users.find_one({"email": email}):
        print(f"User {email} already exists.")
        sys.exit(1)

    users.insert_one({
        "email": email,
        "full_name": full_name,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "roles": ["administrator"],
        "capabilities": [],
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    })

    print(f"Admin user '{email}' created.")
    client.close()


if __name__ == "__main__":
    main()
