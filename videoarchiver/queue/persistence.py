"""Queue persistence management"""

import json
import logging
import os
import time
import fcntl
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from .models import QueueItem, QueueMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("QueuePersistence")

class QueuePersistenceManager:
    """Manages persistence of queue state to disk"""

    def __init__(
        self,
        persistence_path: str,
        max_retries: int = 3,
        retry_delay: int = 1,
        backup_interval: int = 3600,  # 1 hour
        max_backups: int = 24  # Keep last 24 backups
    ):
        """Initialize the persistence manager
        
        Args:
            persistence_path: Path to the persistence file
            max_retries: Maximum number of retries for file operations
            retry_delay: Delay between retries in seconds
            backup_interval: Interval between backups in seconds
            max_backups: Maximum number of backup files to keep
        """
        self.persistence_path = persistence_path
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.backup_interval = backup_interval
        self.max_backups = max_backups
        self._last_backup = 0
        self._lock_file = f"{persistence_path}.lock"

    async def persist_queue_state(
        self,
        queue: list[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        metrics: QueueMetrics
    ) -> None:
        """Persist queue state to disk with improved error handling
        
        Args:
            queue: List of pending queue items
            processing: Dict of items currently being processed
            completed: Dict of completed items
            failed: Dict of failed items
            metrics: Queue metrics object
        
        Raises:
            QueueError: If persistence fails
        """
        lock_fd = None
        try:
            # Create state object
            state = {
                "queue": [item.to_dict() for item in queue],
                "processing": {k: v.to_dict() for k, v in processing.items()},
                "completed": {k: v.to_dict() for k, v in completed.items()},
                "failed": {k: v.to_dict() for k, v in failed.items()},
                "metrics": {
                    "total_processed": metrics.total_processed,
                    "total_failed": metrics.total_failed,
                    "avg_processing_time": metrics.avg_processing_time,
                    "success_rate": metrics.success_rate,
                    "errors_by_type": metrics.errors_by_type,
                    "last_error": metrics.last_error,
                    "last_error_time": (
                        metrics.last_error_time.isoformat()
                        if metrics.last_error_time
                        else None
                    ),
                    "compression_failures": metrics.compression_failures,
                    "hardware_accel_failures": metrics.hardware_accel_failures,
                },
                "timestamp": datetime.utcnow().isoformat()
            }

            # Ensure directory exists
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)

            # Acquire file lock
            lock_fd = open(self._lock_file, 'w')
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

            # Write with retries
            for attempt in range(self.max_retries):
                try:
                    # Write to temp file first
                    temp_path = f"{self.persistence_path}.tmp"
                    with open(temp_path, "w") as f:
                        json.dump(state, f, default=str, indent=2)
                        f.flush()
                        os.fsync(f.fileno())

                    # Atomic rename
                    os.rename(temp_path, self.persistence_path)

                    # Create periodic backup if needed
                    current_time = time.time()
                    if current_time - self._last_backup >= self.backup_interval:
                        await self._create_backup()
                        self._last_backup = current_time

                    break
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1}/{self.max_retries} failed: {e}")
                    await asyncio.sleep(self.retry_delay)

        except Exception as e:
            logger.error(f"Error persisting queue state: {str(e)}")
            raise QueueError(f"Failed to persist queue state: {str(e)}")
        finally:
            if lock_fd:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()

    async def _create_backup(self) -> None:
        """Create a backup of the current state file"""
        try:
            if not os.path.exists(self.persistence_path):
                return

            # Create backup
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.persistence_path}.bak.{timestamp}"
            with open(self.persistence_path, "rb") as src, open(backup_path, "wb") as dst:
                dst.write(src.read())
                dst.flush()
                os.fsync(dst.fileno())

            # Clean old backups
            backup_files = sorted([
                f for f in os.listdir(os.path.dirname(self.persistence_path))
                if f.startswith(os.path.basename(self.persistence_path) + ".bak.")
            ])
            while len(backup_files) > self.max_backups:
                old_backup = os.path.join(os.path.dirname(self.persistence_path), backup_files.pop(0))
                try:
                    os.remove(old_backup)
                except Exception as e:
                    logger.warning(f"Failed to remove old backup {old_backup}: {e}")

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")

    def load_queue_state(self) -> Optional[Dict[str, Any]]:
        """Load persisted queue state from disk with retries
        
        Returns:
            Dict containing queue state if successful, None if file doesn't exist
            
        Raises:
            QueueError: If loading fails
        """
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return None

        lock_fd = None
        try:
            # Acquire file lock
            lock_fd = open(self._lock_file, 'w')
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

            # Try loading main file
            state = None
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    with open(self.persistence_path, "r") as f:
                        state = json.load(f)
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"Retry {attempt + 1}/{self.max_retries} failed: {e}")
                    time.sleep(self.retry_delay)

            # If main file failed, try loading latest backup
            if state is None:
                backup_files = sorted([
                    f for f in os.listdir(os.path.dirname(self.persistence_path))
                    if f.startswith(os.path.basename(self.persistence_path) + ".bak.")
                ], reverse=True)

                if backup_files:
                    latest_backup = os.path.join(os.path.dirname(self.persistence_path), backup_files[0])
                    try:
                        with open(latest_backup, "r") as f:
                            state = json.load(f)
                        logger.info(f"Loaded state from backup: {latest_backup}")
                    except Exception as e:
                        logger.error(f"Failed to load backup: {e}")
                        if last_error:
                            raise QueueError(f"Failed to load queue state: {last_error}")
                        raise

            if state is None:
                return None

            # Helper function to safely convert items
            def safe_convert_item(item_data: dict) -> Optional[QueueItem]:
                try:
                    if isinstance(item_data, dict):
                        # Ensure datetime fields are properly formatted
                        for field in ['added_at', 'last_retry', 'last_error_time']:
                            if field in item_data and item_data[field]:
                                if isinstance(item_data[field], str):
                                    try:
                                        item_data[field] = datetime.fromisoformat(item_data[field])
                                    except ValueError:
                                        item_data[field] = datetime.utcnow() if field == 'added_at' else None
                                elif not isinstance(item_data[field], datetime):
                                    item_data[field] = datetime.utcnow() if field == 'added_at' else None

                        # Ensure processing_time is a float
                        if 'processing_time' in item_data:
                            try:
                                item_data['processing_time'] = float(item_data['processing_time'])
                            except (ValueError, TypeError):
                                item_data['processing_time'] = 0.0

                        return QueueItem(**item_data)
                    return None
                except Exception as e:
                    logger.error(f"Error converting queue item: {e}")
                    return None

            # Convert queue items
            queue = []
            for item in state.get("queue", []):
                converted_item = safe_convert_item(item)
                if converted_item:
                    queue.append(converted_item)
            state["queue"] = queue

            # Convert processing items
            processing = {}
            for k, v in state.get("processing", {}).items():
                converted_item = safe_convert_item(v)
                if converted_item:
                    processing[k] = converted_item
            state["processing"] = processing

            # Convert completed items
            completed = {}
            for k, v in state.get("completed", {}).items():
                converted_item = safe_convert_item(v)
                if converted_item:
                    completed[k] = converted_item
            state["completed"] = completed

            # Convert failed items
            failed = {}
            for k, v in state.get("failed", {}).items():
                converted_item = safe_convert_item(v)
                if converted_item:
                    failed[k] = converted_item
            state["failed"] = failed

            logger.info("Successfully loaded persisted queue state")
            return state

        except Exception as e:
            logger.error(f"Error loading persisted queue state: {str(e)}")
            # Create backup of corrupted state file
            if os.path.exists(self.persistence_path):
                backup_path = f"{self.persistence_path}.corrupted.{int(time.time())}"
                try:
                    os.rename(self.persistence_path, backup_path)
                    logger.info(f"Created backup of corrupted state file: {backup_path}")
                except Exception as be:
                    logger.error(f"Failed to create backup of corrupted state file: {str(be)}")
            raise QueueError(f"Failed to load queue state: {str(e)}")
        finally:
            if lock_fd:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()

class QueueError(Exception):
    """Base exception for queue-related errors"""
    pass
