from __future__ import annotations


class KeelModelError(Exception):
    pass


class ValidationError(KeelModelError):
    pass


class ConfigurationError(KeelModelError):
    pass


class PermissionDenied(KeelModelError):
    pass


class NotFoundError(KeelModelError):
    pass


class ConflictError(KeelModelError):
    pass


class PersistenceError(KeelModelError):
    pass
