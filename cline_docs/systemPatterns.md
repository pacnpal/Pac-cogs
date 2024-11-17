# System Patterns

## Import Patterns

### Relative Imports

- Use relative imports by default to maintain package structure
- Single dot (.) for imports from same directory
- Double dots (..) for imports from parent directory
- Example: `from .base import VideoArchiver`

### Fallback Import Pattern

When loading in different environments (development vs Red-DiscordBot):

```python
try:
    # Try relative imports first
    from ..utils.exceptions import ComponentError
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.utils.exceptions import ComponentError
```

### Package Structure

- Each module has __init__.py to mark it as a package
- Core package imports are kept simple and direct
- Avoid circular imports by using proper hierarchy

## Component Management

- Components are loaded in dependency order
- Each component is registered and tracked
- State changes and errors are logged
- Health checks ensure system stability

## Error Handling

- Detailed error contexts are maintained
- Component errors include severity levels
- Graceful degradation when possible
- Clear error messages for debugging

## Initialization Flow

1. Package imports are resolved
2. Core components are initialized
3. Dependencies are checked and ordered
4. Components are initialized in dependency order
5. Health checks are established
6. System enters ready state

## Development Patterns

- Always maintain relative imports where possible
- Use fallback patterns for environment compatibility
- Keep package structure clean and hierarchical
- Document import patterns and their rationale
- Test in both development and production environments
