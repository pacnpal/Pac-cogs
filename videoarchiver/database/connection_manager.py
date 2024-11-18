"""Module for managing database connections"""

import logging
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional, Dict, Any, TypedDict, ClassVar, Union
from enum import Enum, auto
import threading
from queue import Queue, Empty
from datetime import datetime

try:
    # Try relative imports first
    from ..utils.exceptions import DatabaseError, ErrorContext, ErrorSeverity
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.utils.exceptions import DatabaseError, ErrorContext, ErrorSeverity

logger = logging.getLogger("DBConnectionManager")

class ConnectionState(Enum):
    """Connection states"""
    AVAILABLE = auto()
    IN_USE = auto()
    CLOSED = auto()
    ERROR = auto()

class ConnectionStatus(TypedDict):
    """Type definition for connection status"""
    state: str
    created_at: str
    last_used: str
    error: Optional[str]
    transaction_count: int
    pool_size: int
    available_connections: int

class ConnectionMetrics(TypedDict):
    """Type definition for connection metrics"""
    total_connections: int
    active_connections: int
    idle_connections: int
    failed_connections: int
    total_transactions: int
    failed_transactions: int
    average_transaction_time: float

class ConnectionInfo:
    """Tracks connection information"""

    def __init__(self) -> None:
        self.created_at = datetime.utcnow()
        self.last_used = self.created_at
        self.transaction_count = 0
        self.error_count = 0
        self.total_transaction_time = 0.0
        self.state = ConnectionState.AVAILABLE

    def update_usage(self) -> None:
        """Update connection usage statistics"""
        self.last_used = datetime.utcnow()
        self.transaction_count += 1

    def record_error(self) -> None:
        """Record a connection error"""
        self.error_count += 1
        self.state = ConnectionState.ERROR

    def get_average_transaction_time(self) -> float:
        """Get average transaction time"""
        if self.transaction_count == 0:
            return 0.0
        return self.total_transaction_time / self.transaction_count

class DatabaseConnectionManager:
    """Manages SQLite database connections and connection pooling"""

    DEFAULT_POOL_SIZE: ClassVar[int] = 5
    CONNECTION_TIMEOUT: ClassVar[float] = 30.0
    POOL_TIMEOUT: ClassVar[float] = 5.0

    def __init__(self, db_path: Path, pool_size: int = DEFAULT_POOL_SIZE) -> None:
        """
        Initialize the connection manager.
        
        Args:
            db_path: Path to the SQLite database file
            pool_size: Maximum number of connections in the pool
            
        Raises:
            DatabaseError: If initialization fails
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._connection_pool: Queue[sqlite3.Connection] = Queue(maxsize=pool_size)
        self._connection_info: Dict[int, ConnectionInfo] = {}
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # Initialize connection pool
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """
        Initialize the connection pool.
        
        Raises:
            DatabaseError: If pool initialization fails
        """
        try:
            for _ in range(self.pool_size):
                conn = self._create_connection()
                if conn:
                    self._connection_pool.put(conn)
                    self._connection_info[id(conn)] = ConnectionInfo()
        except Exception as e:
            error = f"Failed to initialize connection pool: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "ConnectionManager",
                    "initialize_pool",
                    {"pool_size": self.pool_size},
                    ErrorSeverity.CRITICAL
                )
            )

    def _create_connection(self) -> Optional[sqlite3.Connection]:
        """
        Create a new database connection with proper settings.
        
        Returns:
            New database connection or None if creation fails
            
        Raises:
            DatabaseError: If connection creation fails
        """
        try:
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                timeout=self.CONNECTION_TIMEOUT
            )
            
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            
            # Set journal mode to WAL for better concurrency
            conn.execute("PRAGMA journal_mode = WAL")
            
            # Set synchronous mode to NORMAL for better performance
            conn.execute("PRAGMA synchronous = NORMAL")
            
            # Enable extended result codes for better error handling
            conn.execute("PRAGMA extended_result_codes = ON")
            
            return conn
            
        except sqlite3.Error as e:
            error = f"Failed to create database connection: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "ConnectionManager",
                    "create_connection",
                    {"path": str(self.db_path)},
                    ErrorSeverity.HIGH
                )
            )

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection from the pool.
        
        Yields:
            Database connection
            
        Raises:
            DatabaseError: If unable to get a connection
        """
        conn = None
        start_time = datetime.utcnow()
        try:
            # Check if we have a transaction-bound connection
            conn = getattr(self._local, 'transaction_connection', None)
            if conn is not None:
                yield conn
                return

            # Get connection from pool or create new one
            try:
                conn = self._connection_pool.get(timeout=self.POOL_TIMEOUT)
            except Empty:
                logger.warning("Connection pool exhausted, creating new connection")
                conn = self._create_connection()
                if not conn:
                    raise DatabaseError(
                        "Failed to create database connection",
                        context=ErrorContext(
                            "ConnectionManager",
                            "get_connection",
                            None,
                            ErrorSeverity.HIGH
                        )
                    )

            # Update connection info
            conn_info = self._connection_info.get(id(conn))
            if conn_info:
                conn_info.update_usage()
                conn_info.state = ConnectionState.IN_USE

            yield conn

        except Exception as e:
            error = f"Error getting database connection: {str(e)}"
            logger.error(error, exc_info=True)
            if conn:
                try:
                    conn.rollback()
                    if id(conn) in self._connection_info:
                        self._connection_info[id(conn)].record_error()
                except Exception:
                    pass
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "ConnectionManager",
                    "get_connection",
                    None,
                    ErrorSeverity.HIGH
                )
            )

        finally:
            if conn and not hasattr(self._local, 'transaction_connection'):
                try:
                    conn.rollback()  # Reset connection state
                    self._connection_pool.put(conn)
                    
                    # Update connection info
                    if id(conn) in self._connection_info:
                        conn_info = self._connection_info[id(conn)]
                        conn_info.state = ConnectionState.AVAILABLE
                        duration = (datetime.utcnow() - start_time).total_seconds()
                        conn_info.total_transaction_time += duration
                        
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
                    try:
                        conn.close()
                        if id(conn) in self._connection_info:
                            self._connection_info[id(conn)].state = ConnectionState.CLOSED
                    except Exception:
                        pass

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Start a database transaction.
        
        Yields:
            Database connection for the transaction
            
        Raises:
            DatabaseError: If unable to start transaction
        """
        if hasattr(self._local, 'transaction_connection'):
            raise DatabaseError(
                "Nested transactions are not supported",
                context=ErrorContext(
                    "ConnectionManager",
                    "transaction",
                    None,
                    ErrorSeverity.HIGH
                )
            )

        conn = None
        start_time = datetime.utcnow()
        try:
            # Get connection from pool
            try:
                conn = self._connection_pool.get(timeout=self.POOL_TIMEOUT)
            except Empty:
                logger.warning("Connection pool exhausted, creating new connection")
                conn = self._create_connection()
                if not conn:
                    raise DatabaseError(
                        "Failed to create database connection",
                        context=ErrorContext(
                            "ConnectionManager",
                            "transaction",
                            None,
                            ErrorSeverity.HIGH
                        )
                    )

            # Update connection info
            if id(conn) in self._connection_info:
                conn_info = self._connection_info[id(conn)]
                conn_info.update_usage()
                conn_info.state = ConnectionState.IN_USE

            # Bind connection to current thread
            self._local.transaction_connection = conn

            # Start transaction
            conn.execute("BEGIN")

            yield conn

            # Commit transaction
            conn.commit()

        except Exception as e:
            error = f"Error in database transaction: {str(e)}"
            logger.error(error, exc_info=True)
            if conn:
                try:
                    conn.rollback()
                    if id(conn) in self._connection_info:
                        self._connection_info[id(conn)].record_error()
                except Exception:
                    pass
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "ConnectionManager",
                    "transaction",
                    None,
                    ErrorSeverity.HIGH
                )
            )

        finally:
            if conn:
                try:
                    # Remove thread-local binding
                    delattr(self._local, 'transaction_connection')
                    
                    # Return connection to pool
                    self._connection_pool.put(conn)
                    
                    # Update connection info
                    if id(conn) in self._connection_info:
                        conn_info = self._connection_info[id(conn)]
                        conn_info.state = ConnectionState.AVAILABLE
                        duration = (datetime.utcnow() - start_time).total_seconds()
                        conn_info.total_transaction_time += duration
                        
                except Exception as e:
                    logger.error(f"Error cleaning up transaction: {e}")
                    try:
                        conn.close()
                        if id(conn) in self._connection_info:
                            self._connection_info[id(conn)].state = ConnectionState.CLOSED
                    except Exception:
                        pass

    def close_all(self) -> None:
        """
        Close all connections in the pool.
        
        Raises:
            DatabaseError: If cleanup fails
        """
        with self._lock:
            try:
                while not self._connection_pool.empty():
                    try:
                        conn = self._connection_pool.get_nowait()
                        try:
                            conn.close()
                            if id(conn) in self._connection_info:
                                self._connection_info[id(conn)].state = ConnectionState.CLOSED
                        except Exception as e:
                            logger.error(f"Error closing connection: {e}")
                    except Empty:
                        break
            except Exception as e:
                error = f"Failed to close all connections: {str(e)}"
                logger.error(error, exc_info=True)
                raise DatabaseError(
                    error,
                    context=ErrorContext(
                        "ConnectionManager",
                        "close_all",
                        None,
                        ErrorSeverity.HIGH
                    )
                )

    def get_status(self) -> ConnectionStatus:
        """
        Get current connection manager status.
        
        Returns:
            Connection status information
        """
        active_connections = sum(
            1 for info in self._connection_info.values()
            if info.state == ConnectionState.IN_USE
        )
        
        return ConnectionStatus(
            state="healthy" if active_connections < self.pool_size else "exhausted",
            created_at=min(
                info.created_at.isoformat()
                for info in self._connection_info.values()
            ),
            last_used=max(
                info.last_used.isoformat()
                for info in self._connection_info.values()
            ),
            error=None,
            transaction_count=sum(
                info.transaction_count
                for info in self._connection_info.values()
            ),
            pool_size=self.pool_size,
            available_connections=self.pool_size - active_connections
        )

    def get_metrics(self) -> ConnectionMetrics:
        """
        Get connection metrics.
        
        Returns:
            Connection metrics information
        """
        total_transactions = sum(
            info.transaction_count
            for info in self._connection_info.values()
        )
        total_errors = sum(
            info.error_count
            for info in self._connection_info.values()
        )
        total_time = sum(
            info.total_transaction_time
            for info in self._connection_info.values()
        )
        
        return ConnectionMetrics(
            total_connections=len(self._connection_info),
            active_connections=sum(
                1 for info in self._connection_info.values()
                if info.state == ConnectionState.IN_USE
            ),
            idle_connections=sum(
                1 for info in self._connection_info.values()
                if info.state == ConnectionState.AVAILABLE
            ),
            failed_connections=sum(
                1 for info in self._connection_info.values()
                if info.state == ConnectionState.ERROR
            ),
            total_transactions=total_transactions,
            failed_transactions=total_errors,
            average_transaction_time=total_time / total_transactions if total_transactions > 0 else 0.0
        )
