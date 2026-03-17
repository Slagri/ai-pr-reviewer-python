"""Dynamically generated RSA key pair for GitHub App JWT tests.

Generated at import time — never stored on disk or committed to git.
This avoids GitGuardian false positives from static PEM content.
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

TEST_PRIVATE_KEY: str = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode()
