"""
Repository-wide pytest setup: keep production configuration out of tests.

The app and the KB library now find app/backend/.env by absolute path (no
longer "whatever .env is in the current directory"). That file is the
production one, so without this every test run — from any directory — would
read production database names and credentials. ADVANDEB_ENV_FILE="" turns the
file off for the whole session; the two settings the app refuses to import
without get throwaway values, as CI already provides.

This runs before any test module is imported: it is the rootdir conftest.
"""
import os

os.environ["ADVANDEB_ENV_FILE"] = ""
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-not-for-production-0123")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
