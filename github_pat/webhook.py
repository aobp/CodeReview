from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(*, secret: str, body: bytes, signature_header: str | None) -> bool:
    if not secret:
        return False
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, provided)
