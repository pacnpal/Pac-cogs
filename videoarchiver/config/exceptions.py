"""Configuration related exceptions"""

class ConfigurationError(Exception):
    """Base exception for configuration related errors"""
    pass

class ValidationError(ConfigurationError):
    """Raised when configuration validation fails"""
    pass

class PermissionError(ConfigurationError):
    """Raised when there are permission issues with configuration"""
    pass

class LoadError(ConfigurationError):
    """Raised when configuration loading fails"""
    pass

class SaveError(ConfigurationError):
    """Raised when configuration saving fails"""
    pass

class MigrationError(ConfigurationError):
    """Raised when configuration migration fails"""
    pass

class SchemaError(ConfigurationError):
    """Raised when configuration schema is invalid"""
    pass
