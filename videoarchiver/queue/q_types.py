"""Shared types for queue management"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum, auto

class QueuePriority(Enum):
    """Priority levels for queue processing"""
    HIGH = auto()
    NORMAL = auto()
    LOW = auto()

class ProcessingStrategy(Enum):
    """Processing strategies"""
    SEQUENTIAL = "sequential"  # Process items one at a time
    CONCURRENT = "concurrent"  # Process multiple items concurrently
    BATCHED = "batched"      # Process items in batches
    PRIORITY = "priority"    # Process based on priority

@dataclass
class QueueMetrics:
    """Type definition for queue metrics"""
    total_items: int
    processing_time: float
    success_rate: float
    error_rate: float
    average_size: float

@dataclass
class ProcessingMetrics:
    """Metrics for processing operations"""
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    retried: int = 0
    avg_processing_time: float = 0.0
    peak_concurrent_tasks: int = 0
    last_processed: Optional[datetime] = None
    error_counts: Dict[str, int] = None

    def __post_init__(self):
        if self.error_counts is None:
            self.error_counts = {}
