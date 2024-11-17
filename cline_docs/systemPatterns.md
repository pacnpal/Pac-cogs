# System Patterns

## Import Patterns

### Standard Import Structure

Every non-init Python file should follow this pattern:

```python
try:
    # Try relative imports first
    from ..module.submodule import Component
    from .local_module import LocalComponent
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.module.submodule import Component
    from videoarchiver.current_module.local_module import LocalComponent
```

### TYPE_CHECKING Imports

For type checking imports, use:

```python
if TYPE_CHECKING:
    try:
        from ..module.component import Component
    except ImportError:
        from videoarchiver.module.component import Component
```

### Package-Level Imports

For package-level imports, use:

```python
try:
    from .. import utils
except ImportError:
    from videoarchiver import utils
```

### Import Rules

1. Always try relative imports first
2. Provide absolute import fallbacks
3. Group imports logically:
   - Standard library imports first
   - Third-party imports second
   - Local/relative imports third
4. Use explicit imports over wildcard imports
5. Handle TYPE_CHECKING imports separately
6. Keep __init__.py files simple with direct imports
7. Test imports in both development and production environments

## Module Organization

### Core Module

- Base components and interfaces
- Core functionality implementation
- Command handling
- Event processing
- Error handling
- Lifecycle management

### Database Module

- Database connections
- Query management
- Schema definitions
- Data models
- Migration handling

### FFmpeg Module

- Process management
- Binary handling
- Encoding parameters
- GPU detection
- Video analysis

### Queue Module

- Queue management
- State tracking
- Health monitoring
- Recovery mechanisms
- Cleanup operations

### Utils Module

- Common utilities
- File operations
- Progress tracking
- Permission management
- Message handling

## Development Patterns

### Code Organization

- Keep modules focused and cohesive
- Follow single responsibility principle
- Use clear and consistent naming
- Maintain proper documentation
- Implement proper error handling

### Testing Strategy

- Test in development environment
- Verify in production environment
- Check import resolution
- Validate component interactions
- Monitor error handling

### Error Handling

- Use specific exception types
- Provide detailed error contexts
- Implement graceful degradation
- Log errors appropriately
- Track error patterns

### Component Management

- Register components explicitly
- Track component states
- Monitor health metrics
- Handle cleanup properly
- Manage dependencies carefully

### Documentation

- Maintain clear docstrings
- Update context files
- Document patterns and decisions
- Track changes systematically
- Keep examples current
