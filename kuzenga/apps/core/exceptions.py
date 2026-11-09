class TenantContextMissing(Exception):
    """A tenant-owned record was written without an active tenant context."""


class TenantMismatch(Exception):
    """A record would cross a tenant boundary."""
