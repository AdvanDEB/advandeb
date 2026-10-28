"""
JWT issue/verify in app/core/auth.py.

The library moved from python-jose to PyJWT. The two vectors below were issued
by python-jose 3.3.0 with the same claims the login route sets, so they pin
the property that matters for the switch: sessions issued before it still
verify after it.
"""
from datetime import timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.core import auth
from app.core.config import settings

KEY = "legacy-vector-secret-key-at-least-32-characters"

# python-jose 3.3.0, HS256, KEY, exp 2100-01-01
JOSE_ACCESS = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiI2NGI3ZjBjMmExYjJjM2Q0ZTVmNjA3MTgiLCJlbWFpbCI6ImxlZ2FjeUBleGFtcGxlLm9yZyIsInR5cGUiOiJhY2Nlc3MiLCJleHAiOjQxMDI0NDQ4MDB9."
    "ODBrplCs7VGKxcNLE4jKkN_FT7zbbCnKRtYpPuTIzis"
)
JOSE_REFRESH = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiI2NGI3ZjBjMmExYjJjM2Q0ZTVmNjA3MTgiLCJqdGkiOiIwMTIzNDU2Nzg5YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZiIsInR5cGUiOiJyZWZyZXNoIiwiZXhwIjo0MTAyNDQ0ODAwfQ."
    "kLVBkVTsZkNvKBSEXM5d13je9tmIRVLcvURKbMK7Us8"
)


@pytest.fixture(autouse=True)
def _jwt_settings(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", KEY)
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")


def _rejected(token, expected_type="access"):
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(token, expected_type=expected_type)
    return exc.value.status_code == 401


def test_tokens_issued_by_python_jose_still_verify():
    access = auth.verify_token(JOSE_ACCESS)
    assert access["sub"] == "64b7f0c2a1b2c3d4e5f60718"
    assert access["email"] == "legacy@example.org"

    refresh = auth.verify_token(JOSE_REFRESH, expected_type="refresh")
    assert refresh["jti"] == "0123456789abcdef0123456789abcdef"


def test_access_token_round_trip():
    token = auth.create_access_token({"sub": "u1", "email": "a@example.org"})
    payload = auth.verify_token(token)
    assert payload["sub"] == "u1"
    assert payload["type"] == "access"
    assert isinstance(payload["exp"], int)


def test_refresh_tokens_carry_a_unique_jti():
    first = auth.verify_token(auth.create_refresh_token({"sub": "u1"}), expected_type="refresh")
    second = auth.verify_token(auth.create_refresh_token({"sub": "u1"}), expected_type="refresh")
    assert first["jti"] != second["jti"]


def test_token_type_is_enforced():
    assert _rejected(JOSE_REFRESH, expected_type="access")
    assert _rejected(JOSE_ACCESS, expected_type="refresh")


def test_expired_token_is_rejected():
    token = auth.create_access_token({"sub": "u1"}, expires_delta=timedelta(seconds=-1))
    assert _rejected(token)


def test_tampered_or_foreign_tokens_are_rejected():
    head, body, sig = JOSE_ACCESS.split(".")
    assert _rejected(f"{head}.{body}.{sig[:-2]}AA")
    assert _rejected(jwt.encode({"sub": "u1", "type": "access"}, "some-other-key-" * 3, algorithm="HS256"))
    assert _rejected("not-a-jwt")


def test_unsigned_token_is_rejected():
    unsigned = jwt.encode({"sub": "u1", "type": "access"}, None, algorithm="none")
    assert _rejected(unsigned)
