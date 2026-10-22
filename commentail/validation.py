"""Bounds for untrusted identifiers before conversion or ORM lookup."""


def valid_identifier(value: str) -> bool:
    """Accept positive decimal IDs representable by a database BigAutoField."""
    return (
        bool(value)
        and len(value) <= 19
        and value.isdecimal()
        and 0 < int(value) <= 2**63 - 1
    )
