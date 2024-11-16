"""Module for managing database connections"""

import logging
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional
import threading
from queue import Queue, Empty

logger = logging.getLogger("DBConnectionManager")

class ConnectionManager:
    """Manages SQLite database connections and connection pooling"""

    def __init__(self, db_path: Path, pool_size: int = 5):
        """Initialize the connection manager
        
        Args:
            db_path: Path to the SQLite database file
            pool_size: Maximum number of connections in the pool
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._connection_pool: Queue[sqlite3.Connection] = Queue(maxsize=pool_size)
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # Initialize connection pool
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """Initialize the connection pool"""
        try:
            for _ in range(self.pool_size):
                conn = self._create_connection()
                if conn:
                    self._connection_pool.put(conn)
        except Exception as e:
            logger.error(f"Error initializing connection pool: {e}")
            raise

    def _create_connection(self) -> Optional[sqlite3.Connection]:
        """Create a new database connection with proper settings"""
        try:
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                timeout=30.0  # 30 second timeout
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
            logger.error(f"Error creating database connection: {e}")
            return None

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection from the pool
        
        Yields:
            sqlite3.Connection: A database connection
            
        Raises:
            sqlite3.Error: If unable to get a connection
        """
        conn = None
        try:
            # Check if we have a transaction-bound connection
            conn = getattr(self._local, 'transaction_connection', None)
            if conn is not None:
                yield conn
                return

            # Get connection from pool or create new one
            try:
                conn = self._connection_pool.get(timeout=5.0)
            except Empty:
                logger.warning("Connection pool exhausted, creating new connection")
                conn = self._create_connection()
                if not conn:
                    raise sqlite3.Error("Failed to create database connection")

            yield conn

        except Exception as e:
            logger.error(f"Error getting database connection: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise

        finally:
            if conn and not hasattr(self._local, 'transaction_connection'):
                try:
                    conn.rollback()  # Reset connection state
                    self._connection_pool.put(conn)
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
                    try:
                        conn.close()
                    except Exception:
                        pass

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Start a database transaction
        
        Yields:
            sqlite3.Connection: A database connection for the transaction
            
        Raises:
            sqlite3.Error: If unable to start transaction
        """
        if hasattr(self._local, 'transaction_connection'):
            raise sqlite3.Error("Nested transactions are not supported")

        conn = None
        try:
            # Get connection from pool
            try:
                conn = self._connection_pool.get(timeout=5.0)
            except Empty:
                logger.warning("Connection pool exhausted, creating new connection")
                conn = self._create_connection()
                if not conn:
                    raise sqlite3.Error("Failed to create database connection")

            # Bind connection to current thread
            self._local.transaction_connection = conn

            # Start transaction
            conn.execute("BEGIN")

            yield conn

            # Commit transaction
            conn.commit()

        except Exception as e:
            logger.error(f"Error in database transaction: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise

        finally:
            if conn:
                try:
                    # Remove thread-local binding
                    delattr(self._local, 'transaction_connection')
                    
                    # Return connection to pool
                    self._connection_pool.put(conn)
                except Exception as e:
                    logger.error(f"Error cleaning up transaction: {e}")
                    try:
                        conn.close()
                    except Exception:
                        pass

    def close_all(self) -> None:
        """Close all connections in the pool"""
        with self._lock:
            while not self._connection_pool.empty():
                try:
                    conn = self._connection_pool.get_nowait()
                    try:
                        conn.close()
                    except Exception as e:
                        logger.error(f"Error closing connection: {e}")
                except Empty:
                    break
