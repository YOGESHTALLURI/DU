# -*- coding: utf-8 -*-
"""Custom exceptions for the Cinqflow application.

Only lightweight exception classes are defined here to avoid circular imports.
"""

class StaleLeaseError(RuntimeError):
    """Raised when an ODS execution lease has expired.

    Workers must catch this exception and abort any ODS mutation attempt.
    """
    pass
