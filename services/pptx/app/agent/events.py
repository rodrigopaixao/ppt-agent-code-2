"""Keep credentials out of activity lines and error messages."""

import re

SECRETS = re.compile(r"sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{30,}|ya29\.[0-9A-Za-z._-]{20,}")


def redact(value: str) -> str:
    return SECRETS.sub("[redacted]", value)
