"""Source-bridge exceptions."""


class StaleManualSchemaError(Exception):
    """Raised when manually-edited facts-schema drifts from current spec hash (D8)."""
