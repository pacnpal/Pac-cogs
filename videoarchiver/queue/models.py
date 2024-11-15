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
class QueueItem:
    """Represents an item in the video processing queue"""
    
    url: str
    message_id: str
    channel_id: str
    user_id: str
    added_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"
    retries: int = 0
    last_retry: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    processing_time: float = 0.0
    output_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Convert string dates to datetime objects after initialization"""
        if isinstance(self.added_at, str):
            try:
                self.added_at = datetime.fromisoformat(self.added_at)
            except ValueError:
                self.added_at = datetime.utcnow()
        elif not isinstance(self.added_at, datetime):
            self.added_at = datetime.utcnow()

        if isinstance(self.last_retry, str):
            try:
                self.last_retry = datetime.fromisoformat(self.last_retry)
            except ValueError:
                self.last_retry = None
        elif not isinstance(self.last_retry, datetime):
            self.last_retry = None

        if isinstance(self.last_error_time, str):
            try:
                self.last_error_time = datetime.fromisoformat(self.last_error_time)
            except ValueError:
                self.last_error_time = None
        elif not isinstance(self.last_error_time, datetime):
            self.last_error_time = None

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
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'QueueItem':
        """Create from dictionary with datetime handling"""
        return cls(**data)

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

    def __post_init__(self):
        """Convert string dates to datetime objects after initialization"""
        # Handle last_error_time conversion
        if isinstance(self.last_error_time, str):
            try:
                self.last_error_time = datetime.fromisoformat(self.last_error_time)
            except (ValueError, TypeError):
                self.last_error_time = None
        elif not isinstance(self.last_error_time, datetime):
            self.last_error_time = None

        # Handle last_cleanup conversion
        if isinstance(self.last_cleanup, str):
            try:
                self.last_cleanup = datetime.fromisoformat(self.last_cleanup)
            except (ValueError, TypeError):
                self.last_cleanup = datetime.utcnow()
        elif not isinstance(self.last_cleanup, datetime):
            self.last_cleanup = datetime.utcnow()

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

    def to_dict(self) -> dict:
        """Convert to dictionary with datetime handling"""
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        if self.last_error_time:
            data['last_error_time'] = self.last_error_time.isoformat()
        if self.last_cleanup:
            data['last_cleanup'] = self.last_cleanup.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'QueueMetrics':
        """Create from dictionary with datetime handling"""
        # Convert ISO format strings back to datetime objects
        if 'last_error_time' in data and isinstance(data['last_error_time'], str):
            try:
                data['last_error_time'] = datetime.fromisoformat(data['last_error_time'])
            except ValueError:
                data['last_error_time'] = None
        if 'last_cleanup' in data and isinstance(data['last_cleanup'], str):
            try:
                data['last_cleanup'] = datetime.fromisoformat(data['last_cleanup'])
            except ValueError:
                data['last_cleanup'] = datetime.utcnow()
        return cls(**data)
