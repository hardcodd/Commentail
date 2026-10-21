"""Redact capability query values in Django's development-server log.

Reverse-proxy access logs and custom exception reporters belong to the host
project and must apply the same redaction before production deployment.
"""

import logging
import re


def redact(value: str) -> str:
    # Django decodes parameter names before lookup. Match their percent-encoded
    # spellings too, without decoding/reformatting unrelated log content.
    return re.sub(
        r"([?&]?(?:t|%74)(?:o|%6[fF])(?:k|%6[bB])(?:e|%65)(?:n|%6[eE])=)[^&\s]+",
        r"\1[redacted]",
        value,
    )


class CapabilityFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact(value) if isinstance(value, str) else value
                for value in record.args
            )
        return True
