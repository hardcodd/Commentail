"""Redact capability query values in Django's development-server log.

Reverse-proxy access logs and custom exception reporters belong to the host
project and must apply the same redaction before production deployment.
"""

import logging
import re


def redact(value: str) -> str:
    return re.sub(r"([?&]?token=)[^&\s]+", r"\1[redacted]", value)


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
