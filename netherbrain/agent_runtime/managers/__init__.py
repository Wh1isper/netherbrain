"""Data access managers for the agent runtime.

Each module provides async functions that encapsulate CRUD operations
and business logic.  Managers accept ``AsyncSession`` as a parameter
and raise domain exceptions (``LookupError``, ``ValueError``), never
HTTP exceptions -- that translation is the router's responsibility.
"""
