"""Data models for the queue system"""

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Optional, List, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("QueueModels")

@dataclass
class QueueMetrics:
    """Metrics tracking for queue performance and health"""

    total_processed: int = 0
    total_failed: int = 0
    avg_processing_time: float = 0.0
    success_rate: float = 0.0
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    last_cleanup: datetime = field(default_factory=datetime.utcnow)
    retries: int = 0
    peak_memory_usage: float = 0.0
    processing_times: List[float] = field(default_factory=list)
    compression_failures: int = 0
    hardware_accel_failures: int = 0

    def update(self, processing_time: float, success: bool, error: str = None):
        """Update metrics with new processing information"""
        self.total_processed += 1
        if not success:
            self.total_failed += 1
            if error:
                self.last_error = error
                self.last_error_time = datetime.utcnow()
                error_type = error.split(":")[0] if ":" in error else error
                self.errors_by_type[error_type] = (
                    self.errors_by_type.get(error_type, 0) + 1
                )
                
                # Track specific error types
                if "compression error" in error.lower():
                    self.compression_failures += 1
                elif "hardware acceleration failed" in error.lower():
                    self.hardware_accel_failures += 1

        # Update processing times with sliding window
        self.processing_times.append(processing_time)
        if len(self.processing_times) > 100:  # Keep last 100 processing times
            self.processing_times.pop(0)

        # Update average processing time
        self.avg_processing_time = (
            sum(self.processing_times) / len(self.processing_times)
            if self.processing_times
            else 0.0
        )

        # Update success rate
        self.success_rate = (
            (self.total_processed - self.total_failed) / self.total_processed
            if self.total_processed > 0
            else 0.0
        )

@dataclass
class QueueItem:
    """Represents a video processing task in the queue"""

    url: str
    message_id: int
    channel_id: int
    guild_id: int
    author_id: int
    added_at: datetime
    priority: int = 0  # Higher number = higher priority
    status: str = "pending"  # pending, processing, completed, failed
    error: Optional[str] = None
    attempt: int = 0
    _processing_time: float = 0.0  # Use private field for processing_time
    size_bytes: int = 0
    last_error: Optional[str] = None
    retry_count: int = 0
    last_retry: Optional[datetime] = None
    processing_times: List[float] = field(default_factory=list)
    last_error_time: Optional[datetime] = None
    hardware_accel_attempted: bool = False
    compression_attempted: bool = False
    original_message: Optional[Any] = None  # Store the original message reference

    @property
    def processing_time(self) -> float:
        """Get processing time as float"""
        return self._processing_time

    @processing_time.setter
    def processing_time(self, value: Any) -> None:
        """Set processing time, ensuring it's always a float"""
        try:
            if isinstance(value, str):
                self._processing_time = float(value)
            elif isinstance(value, (int, float)):
                self._processing_time = float(value)
            else:
                self._processing_time = 0.0
        except (ValueError, TypeError):
            self._processing_time = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary with datetime handling"""
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        if self.added_at:
            data['added_at'] = self.added_at.isoformat()
        if self.last_retry:
            data['last_retry'] = self.last_retry.isoformat()
        if self.last_error_time:
            data['last_error_time'] = self.last_error_time.isoformat()
        # Convert _processing_time to processing_time in dict
        data['processing_time'] = self.processing_time
        data.pop('_processing_time', None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'QueueItem':
        """Create from dictionary with datetime handling"""
        # Convert ISO format strings back to datetime objects
        if 'added_at' in data and isinstance(data['added_at'], str):
            data['added_at'] = datetime.fromisoformat(data['added_at'])
        if 'last_retry' in data and isinstance(data['last_retry'], str):
            data['last_retry'] = datetime.fromisoformat(data['last_retry'])
        if 'last_error_time' in data and isinstance(data['last_error_time'], str):
            data['last_error_time'] = datetime.fromisoformat(data['last_error_time'])
        # Handle processing_time conversion
        if 'processing_time' in data:
            try:
                if isinstance(data['processing_time'], str):
                    data['_processing_time'] = float(data['processing_time'])
                elif isinstance(data['processing_time'], (int, float)):
                    data['_processing_time'] = float(data['processing_time'])
                else:
                    data['_processing_time'] = 0.0
            except (ValueError, TypeError):
                data['_processing_time'] = 0.0
            data.pop('processing_time', None)
        return cls(**data)
