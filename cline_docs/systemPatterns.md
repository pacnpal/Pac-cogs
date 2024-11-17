# System Patterns

## High-Level Architecture

The videoarchiver module is organized into several key components:

- processor: Handles core processing logic
- queue: Manages video processing queue
- database: Handles data persistence
- ffmpeg: Manages video processing
- utils: Provides utility functions
- core: Contains core bot functionality
- config: Manages configuration

## Cyclic Dependencies Analysis

### Current Dependency Chain

1. VideoProcessor (core.py)
   - Imports MessageHandler, QueueHandler, CleanupManager under TYPE_CHECKING
   - Creates instances of these handlers in __init__

2. MessageHandler (message_handler.py)
   - Imports ConfigManager, URLExtractor
   - No circular imports detected

3. QueueHandler (queue_handler.py)
   - Imports utils, database, config_manager
   - No circular imports detected

4. CleanupManager (cleanup_manager.py)
   - Imports QueueHandler under TYPE_CHECKING
   - No problematic circular dependencies

### Mitigation Strategies Used

1. TYPE_CHECKING conditional imports
   - Used effectively in core.py and cleanup_manager.py
   - Prevents runtime circular imports
   - Maintains type safety during development

2. Late imports
   - Used in VideoProcessor.__init__ to avoid circular dependencies
   - Handlers are imported only when needed

3. Forward references
   - Type hints use string literals for types that aren't yet defined

## Core Technical Patterns

1. Component Initialization Pattern
   - Core processor initializes handlers
   - Handlers are loosely coupled through interfaces
   - Dependencies are injected through constructor

2. Message Processing Pipeline
   - Message validation
   - URL extraction
   - Queue management
   - Progress tracking

3. Cleanup Management
   - Staged cleanup process
   - Multiple cleanup strategies
   - Resource tracking and monitoring

## Data Flow

1. Message Processing Flow
   - Message received → MessageHandler
   - Validation → URL Extraction
   - Queue addition → Processing

2. Video Processing Flow
   - Queue item → Download
   - Processing → Archival
   - Cleanup → Completion

## Key Technical Decisions

1. Dependency Management
   - Use of TYPE_CHECKING for circular import prevention
   - Late initialization of components
   - Clear separation of concerns between handlers

2. Error Handling
   - Each component has dedicated error types
   - Comprehensive error tracking
   - Graceful degradation

3. State Management
   - Clear state transitions
   - Progress tracking
   - Health monitoring

4. Resource Management
   - Staged cleanup process
   - Multiple cleanup strategies
   - Resource tracking

## Recommendations

1. Current Structure
   - The current architecture effectively manages dependencies
   - No immediate issues requiring refactoring

2. Future Improvements
   - Consider using dependency injection container
   - Implement interface segregation for cleaner dependencies
   - Add more comprehensive health checks
