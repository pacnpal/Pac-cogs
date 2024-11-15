"""Queue persistence management"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional
from .models import QueueItem, QueueMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("QueuePersistence")

class QueuePersistenceManager:
    """Manages persistence of queue state to disk"""

    def __init__(self, persistence_path: str):
        """Initialize the persistence manager
        
        Args:
            persistence_path: Path to the persistence file
        """
        self.persistence_path = persistence_path

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
        try:
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
            }

            # Ensure directory exists
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)

            # Write to temp file first
            temp_path = f"{self.persistence_path}.tmp"
            with open(temp_path, "w") as f:
                json.dump(state, f, default=str)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename
            os.rename(temp_path, self.persistence_path)

        except Exception as e:
            logger.error(f"Error persisting queue state: {str(e)}")
            raise QueueError(f"Failed to persist queue state: {str(e)}")

    def load_queue_state(self) -> Optional[Dict[str, Any]]:
        """Load persisted queue state from disk
        
        Returns:
            Dict containing queue state if successful, None if file doesn't exist
            
        Raises:
            QueueError: If loading fails
        """
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return None

        try:
            with open(self.persistence_path, "r") as f:
                state = json.load(f)

            # Helper function to safely convert items
            def safe_convert_item(item_data: dict) -> Optional[QueueItem]:
                try:
                    if isinstance(item_data, dict):
                        # Ensure datetime fields are properly formatted
                        if 'added_at' in item_data and item_data['added_at']:
                            if isinstance(item_data['added_at'], str):
                                try:
                                    item_data['added_at'] = datetime.fromisoformat(item_data['added_at'])
                                except ValueError:
                                    item_data['added_at'] = datetime.utcnow()
                            elif not isinstance(item_data['added_at'], datetime):
                                item_data['added_at'] = datetime.utcnow()

                        if 'last_retry' in item_data and item_data['last_retry']:
                            if isinstance(item_data['last_retry'], str):
                                try:
                                    item_data['last_retry'] = datetime.fromisoformat(item_data['last_retry'])
                                except ValueError:
                                    item_data['last_retry'] = None
                            elif not isinstance(item_data['last_retry'], datetime):
                                item_data['last_retry'] = None

                        if 'last_error_time' in item_data and item_data['last_error_time']:
                            if isinstance(item_data['last_error_time'], str):
                                try:
                                    item_data['last_error_time'] = datetime.fromisoformat(item_data['last_error_time'])
                                except ValueError:
                                    item_data['last_error_time'] = None
                            elif not isinstance(item_data['last_error_time'], datetime):
                                item_data['last_error_time'] = None

                        # Ensure processing_time is a float
                        if 'processing_time' in item_data:
                            try:
                                if isinstance(item_data['processing_time'], str):
                                    item_data['processing_time'] = float(item_data['processing_time'])
                                elif not isinstance(item_data['processing_time'], (int, float)):
                                    item_data['processing_time'] = 0.0
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
                backup_path = f"{self.persistence_path}.bak.{int(time.time())}"
                try:
                    os.rename(self.persistence_path, backup_path)
                    logger.info(f"Created backup of corrupted state file: {backup_path}")
                except Exception as be:
                    logger.error(f"Failed to create backup of corrupted state file: {str(be)}")
            raise QueueError(f"Failed to load queue state: {str(e)}")

class QueueError(Exception):
    """Base exception for queue-related errors"""
    pass
