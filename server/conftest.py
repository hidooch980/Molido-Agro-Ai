"""Test-suite configuration.

Abuse limits (fixed-window rate limiting and sign-in lockout) protect real
traffic. The suite drives hundreds of requests from a single test client, so the
limits are raised here and exercised explicitly in test_auth_hardening.py,
where they are monkeypatched per test.
"""
import os

os.environ.setdefault("MOLIDO_AUTH_RATE_LIMIT", "100000")
os.environ.setdefault("MOLIDO_LOGIN_RATE_LIMIT", "100000")
os.environ.setdefault("MOLIDO_MAX_LOGIN_FAILURES", "5")
