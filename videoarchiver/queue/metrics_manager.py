"""Module for managing queue metrics"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any, Set
from datetime import datetime, timedelta
import json

logger = logging.getLogger("QueueMetricsManager")

class MetricCategory(Enum):
    """Categories of metrics"""
    PROCESSING = "processing"
    PERFORMANCE = "performance"
    ERRORS = "errors"
    HARDWARE = "hardware"
    MEMORY = "memory"
    ACTIVITY = "activity"

class ErrorCategory(Enum):
    """Categories of errors"""
    NETWORK = "network"
    TIMEOUT = "timeout"
    PERMISSION = "permission"
    MEMORY = "memory"
    HARDWARE = "hardware"
    COMPRESSION = "compression"
    STORAGE = "storage"
    OTHER = "other"

@dataclass
class ProcessingMetrics:
    """Processing-related metrics"""
    total_processed: int = 0
    total_failed: int = 0
    success_rate: float = 0.0
    avg_processing_time: float = 0.0
    _total_processing_time: float = 0.0
    _processing_count: int = 0

    def update(self, processing_time: float, success: bool) -> None:
        """Update processing metrics"""
        self.total_processed += 1
        if not success:
            self.total_failed += 1
        
        self._total_processing_time += processing_time
        self._processing_count += 1
        
        self.success_rate = (
            (self.total_processed - self.total_failed)
            / self.total_processed
            if self.total_processed > 0
            else 0.0
        )
        self.avg_processing_time = (
            self._total_processing_time / self._processing_count
            if self._processing_count > 0
            else 0.0
        )

@dataclass
class ErrorMetrics:
    """Error-related metrics"""
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    errors_by_category: Dict[ErrorCategory, int] = field(default_factory=dict)
    recent_errors: List[Dict[str, Any]] = field(default_factory=list)
    error_patterns: Dict[str, int] = field(default_factory=dict)
    max_recent_errors: int = 100

    def record_error(self, error: str, category: Optional[ErrorCategory] = None) -> None:
        """Record an error occurrence"""
        # Track by exact error
        self.errors_by_type[error] = self.errors_by_type.get(error, 0) + 1
        
        # Track by category
        if category is None:
            category = self._categorize_error(error)
        self.errors_by_category[category] = self.errors_by_category.get(category, 0) + 1
        
        # Track recent errors
        self.recent_errors.append({
            "error": error,
            "category": category.value,
            "timestamp": datetime.utcnow().isoformat()
        })
        if len(self.recent_errors) > self.max_recent_errors:
            self.recent_errors.pop(0)
        
        # Update error patterns
        pattern = self._extract_error_pattern(error)
        self.error_patterns[pattern] = self.error_patterns.get(pattern, 0) + 1

    def _categorize_error(self, error: str) -> ErrorCategory:
        """Categorize an error message"""
        error_lower = error.lower()
        
        if any(word in error_lower for word in ["network", "connection", "dns"]):
            return ErrorCategory.NETWORK
        elif "timeout" in error_lower:
            return ErrorCategory.TIMEOUT
        elif any(word in error_lower for word in ["permission", "access", "denied"]):
            return ErrorCategory.PERMISSION
        elif "memory" in error_lower:
            return ErrorCategory.MEMORY
        elif "hardware" in error_lower:
            return ErrorCategory.HARDWARE
        elif "compression" in error_lower:
            return ErrorCategory.COMPRESSION
        elif any(word in error_lower for word in ["disk", "storage", "space"]):
            return ErrorCategory.STORAGE
        return ErrorCategory.OTHER

    def _extract_error_pattern(self, error: str) -> str:
        """Extract general pattern from error message"""
        # This could be enhanced with regex or more sophisticated pattern matching
        words = error.split()
        if len(words) > 5:
            return " ".join(words[:5]) + "..."
        return error

@dataclass
class PerformanceMetrics:
    """Performance-related metrics"""
    peak_memory_usage: float = 0.0
    compression_failures: int = 0
    hardware_accel_failures: int = 0
    peak_queue_size: int = 0
    peak_processing_time: float = 0.0
    avg_queue_wait_time: float = 0.0
    _total_wait_time: float = 0.0
    _wait_count: int = 0

    def update_memory(self, memory_usage: float) -> None:
        """Update memory usage metrics"""
        self.peak_memory_usage = max(self.peak_memory_usage, memory_usage)

    def record_wait_time(self, wait_time: float) -> None:
        """Record queue wait time"""
        self._total_wait_time += wait_time
        self._wait_count += 1
        self.avg_queue_wait_time = (
            self._total_wait_time / self._wait_count
            if self._wait_count > 0
            else 0.0
        )

class MetricAggregator:
    """Aggregates metrics over time periods"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.hourly_metrics: List[Dict[str, Any]] = []
        self.daily_metrics: List[Dict[str, Any]] = []
        self.last_aggregation = datetime.utcnow()

    def aggregate_metrics(self, current_metrics: Dict[str, Any]) -> None:
        """Aggregate current metrics"""
        now = datetime.utcnow()
        
        # Hourly aggregation
        if now - self.last_aggregation >= timedelta(hours=1):
            self.hourly_metrics.append({
                "timestamp": now.isoformat(),
                "metrics": current_metrics
            })
            if len(self.hourly_metrics) > self.max_history:
                self.hourly_metrics.pop(0)
        
        # Daily aggregation
        if now.date() > self.last_aggregation.date():
            daily_avg = self._calculate_daily_average(
                self.hourly_metrics,
                self.last_aggregation.date()
            )
            self.daily_metrics.append(daily_avg)
            if len(self.daily_metrics) > 30:  # Keep last 30 days
                self.daily_metrics.pop(0)
        
        self.last_aggregation = now

    def _calculate_daily_average(
        self,
        metrics: List[Dict[str, Any]],
        date: datetime.date
    ) -> Dict[str, Any]:
        """Calculate average metrics for a day"""
        day_metrics = [
            m for m in metrics
            if datetime.fromisoformat(m["timestamp"]).date() == date
        ]
        
        if not day_metrics:
            return {
                "date": date.isoformat(),
                "metrics": {}
            }
        
        # Calculate averages for numeric values
        avg_metrics = {}
        for key in day_metrics[0]["metrics"].keys():
            if isinstance(day_metrics[0]["metrics"][key], (int, float)):
                avg_metrics[key] = sum(
                    m["metrics"][key] for m in day_metrics
                ) / len(day_metrics)
            else:
                avg_metrics[key] = day_metrics[-1]["metrics"][key]
        
        return {
            "date": date.isoformat(),
            "metrics": avg_metrics
        }

class QueueMetricsManager:
    """Manages metrics collection and reporting for the queue system"""

    def __init__(self):
        self.processing = ProcessingMetrics()
        self.errors = ErrorMetrics()
        self.performance = PerformanceMetrics()
        self.aggregator = MetricAggregator()
        self.last_activity = time.time()
        self.last_cleanup = datetime.utcnow()

    def update(
        self,
        processing_time: float,
        success: bool,
        error: Optional[str] = None
    ) -> None:
        """Update metrics with new processing information"""
        try:
            # Update processing metrics
            self.processing.update(processing_time, success)

            # Update error tracking
            if error:
                self.errors.record_error(error)
                
                # Track specific failures
                if "hardware acceleration" in error.lower():
                    self.performance.hardware_accel_failures += 1
                elif "compression" in error.lower():
                    self.performance.compression_failures += 1

            # Update activity timestamp
            self.last_activity = time.time()

            # Aggregate metrics
            self.aggregator.aggregate_metrics(self.get_metrics())

        except Exception as e:
            logger.error(f"Error updating metrics: {e}")

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        return {
            MetricCategory.PROCESSING.value: {
                "total_processed": self.processing.total_processed,
                "total_failed": self.processing.total_failed,
                "success_rate": self.processing.success_rate,
                "avg_processing_time": self.processing.avg_processing_time
            },
            MetricCategory.ERRORS.value: {
                "errors_by_type": self.errors.errors_by_type,
                "errors_by_category": {
                    cat.value: count
                    for cat, count in self.errors.errors_by_category.items()
                },
                "error_patterns": self.errors.error_patterns,
                "recent_errors": self.errors.recent_errors
            },
            MetricCategory.PERFORMANCE.value: {
                "peak_memory_usage": self.performance.peak_memory_usage,
                "compression_failures": self.performance.compression_failures,
                "hardware_accel_failures": self.performance.hardware_accel_failures,
                "peak_queue_size": self.performance.peak_queue_size,
                "avg_queue_wait_time": self.performance.avg_queue_wait_time
            },
            MetricCategory.ACTIVITY.value: {
                "last_activity": time.time() - self.last_activity,
                "last_cleanup": self.last_cleanup.isoformat()
            },
            "history": {
                "hourly": self.aggregator.hourly_metrics,
                "daily": self.aggregator.daily_metrics
            }
        }

    def update_memory_usage(self, memory_usage: float) -> None:
        """Update peak memory usage"""
        self.performance.update_memory(memory_usage)

    def update_cleanup_time(self) -> None:
        """Update last cleanup timestamp"""
        self.last_cleanup = datetime.utcnow()

    def reset_metrics(self) -> None:
        """Reset all metrics to initial state"""
        self.processing = ProcessingMetrics()
        self.errors = ErrorMetrics()
        self.performance = PerformanceMetrics()
        self.last_activity = time.time()
        self.last_cleanup = datetime.utcnow()

    def save_metrics(self, file_path: str) -> None:
        """Save metrics to file"""
        try:
            metrics = self.get_metrics()
            with open(file_path, 'w') as f:
                json.dump(metrics, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")

    def load_metrics(self, file_path: str) -> None:
        """Load metrics from file"""
        try:
            with open(file_path, 'r') as f:
                metrics = json.load(f)
            self.restore_metrics(metrics)
        except Exception as e:
            logger.error(f"Error loading metrics: {e}")

    def restore_metrics(self, metrics_data: Dict[str, Any]) -> None:
        """Restore metrics from saved data"""
        try:
            # Restore processing metrics
            proc_data = metrics_data.get(MetricCategory.PROCESSING.value, {})
            self.processing = ProcessingMetrics(
                total_processed=proc_data.get("total_processed", 0),
                total_failed=proc_data.get("total_failed", 0),
                success_rate=proc_data.get("success_rate", 0.0),
                avg_processing_time=proc_data.get("avg_processing_time", 0.0)
            )

            # Restore error metrics
            error_data = metrics_data.get(MetricCategory.ERRORS.value, {})
            self.errors = ErrorMetrics(
                errors_by_type=error_data.get("errors_by_type", {}),
                errors_by_category={
                    ErrorCategory[k.upper()]: v
                    for k, v in error_data.get("errors_by_category", {}).items()
                },
                error_patterns=error_data.get("error_patterns", {}),
                recent_errors=error_data.get("recent_errors", [])
            )

            # Restore performance metrics
            perf_data = metrics_data.get(MetricCategory.PERFORMANCE.value, {})
            self.performance = PerformanceMetrics(
                peak_memory_usage=perf_data.get("peak_memory_usage", 0.0),
                compression_failures=perf_data.get("compression_failures", 0),
                hardware_accel_failures=perf_data.get("hardware_accel_failures", 0),
                peak_queue_size=perf_data.get("peak_queue_size", 0),
                avg_queue_wait_time=perf_data.get("avg_queue_wait_time", 0.0)
            )

            # Restore history
            history = metrics_data.get("history", {})
            self.aggregator.hourly_metrics = history.get("hourly", [])
            self.aggregator.daily_metrics = history.get("daily", [])

        except Exception as e:
            logger.error(f"Error restoring metrics: {e}")
