"""Module for queue health checks"""

import logging
import psutil
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List, Any, Set
from datetime import datetime, timedelta

logger = logging.getLogger("QueueHealthChecker")

class HealthStatus(Enum):
    """Possible health status values"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

class HealthCategory(Enum):
    """Health check categories"""
    MEMORY = "memory"
    PERFORMANCE = "performance"
    ACTIVITY = "activity"
    ERRORS = "errors"
    DEADLOCKS = "deadlocks"
    SYSTEM = "system"

@dataclass
class HealthThresholds:
    """Defines thresholds for health checks"""
    memory_warning_mb: int = 384    # 384MB
    memory_critical_mb: int = 512   # 512MB
    deadlock_warning_sec: int = 30  # 30 seconds
    deadlock_critical_sec: int = 60 # 1 minute
    error_rate_warning: float = 0.1 # 10% errors
    error_rate_critical: float = 0.2 # 20% errors
    inactivity_warning_sec: int = 30
    inactivity_critical_sec: int = 60
    cpu_warning_percent: float = 80.0
    cpu_critical_percent: float = 90.0

@dataclass
class HealthCheckResult:
    """Result of a health check"""
    category: HealthCategory
    status: HealthStatus
    message: str
    value: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)

class HealthHistory:
    """Tracks health check history"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: List[HealthCheckResult] = []
        self.status_changes: List[Dict[str, Any]] = []
        self.critical_events: List[Dict[str, Any]] = []

    def add_result(self, result: HealthCheckResult) -> None:
        """Add a health check result"""
        self.history.append(result)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        # Track status changes
        if self.history[-2:-1] and self.history[-1].status != self.history[-2].status:
            self.status_changes.append({
                "timestamp": result.timestamp,
                "category": result.category.value,
                "from_status": self.history[-2].status.value,
                "to_status": result.status.value,
                "message": result.message
            })

        # Track critical events
        if result.status == HealthStatus.CRITICAL:
            self.critical_events.append({
                "timestamp": result.timestamp,
                "category": result.category.value,
                "message": result.message,
                "details": result.details
            })

    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of health status history"""
        return {
            "total_checks": len(self.history),
            "status_changes": len(self.status_changes),
            "critical_events": len(self.critical_events),
            "recent_status_changes": self.status_changes[-5:],
            "recent_critical_events": self.critical_events[-5:]
        }

class SystemHealthMonitor:
    """Monitors system health metrics"""

    def __init__(self):
        self.process = psutil.Process()

    async def check_system_health(self) -> Dict[str, Any]:
        """Check system health metrics"""
        try:
            cpu_percent = self.process.cpu_percent()
            memory_info = self.process.memory_info()
            io_counters = self.process.io_counters()
            
            return {
                "cpu_percent": cpu_percent,
                "memory_rss": memory_info.rss / 1024 / 1024,  # MB
                "memory_vms": memory_info.vms / 1024 / 1024,  # MB
                "io_read_mb": io_counters.read_bytes / 1024 / 1024,
                "io_write_mb": io_counters.write_bytes / 1024 / 1024,
                "thread_count": self.process.num_threads(),
                "open_files": len(self.process.open_files()),
                "connections": len(self.process.connections())
            }
        except Exception as e:
            logger.error(f"Error checking system health: {e}")
            return {}

class HealthChecker:
    """Handles health checks for the queue system"""

    def __init__(
        self,
        thresholds: Optional[HealthThresholds] = None,
        history_size: int = 1000
    ):
        self.thresholds = thresholds or HealthThresholds()
        self.history = HealthHistory(history_size)
        self.system_monitor = SystemHealthMonitor()
        self._last_gc_time: Optional[datetime] = None

    async def check_health(
        self,
        metrics: Dict[str, Any],
        queue_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        results = []

        # Check memory health
        memory_result = await self._check_memory_health()
        results.append(memory_result)

        # Check performance health
        perf_result = self._check_performance_health(metrics)
        results.append(perf_result)

        # Check activity health
        activity_result = self._check_activity_health(
            queue_info["last_activity"],
            queue_info["processing_count"] > 0
        )
        results.append(activity_result)

        # Check error health
        error_result = self._check_error_health(metrics)
        results.append(error_result)

        # Check for deadlocks
        deadlock_result = self._check_deadlocks(queue_info)
        results.append(deadlock_result)

        # Check system health
        system_result = await self._check_system_health()
        results.append(system_result)

        # Record results
        for result in results:
            self.history.add_result(result)

        # Determine overall health
        overall_status = self._determine_overall_status(results)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": overall_status.value,
            "checks": [
                {
                    "category": r.category.value,
                    "status": r.status.value,
                    "message": r.message,
                    "value": r.value,
                    "details": r.details
                }
                for r in results
            ],
            "history": self.history.get_status_summary()
        }

    async def _check_memory_health(self) -> HealthCheckResult:
        """Check memory health"""
        try:
            memory_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            
            if memory_usage > self.thresholds.memory_critical_mb:
                if (
                    not self._last_gc_time or
                    datetime.utcnow() - self._last_gc_time > timedelta(minutes=5)
                ):
                    import gc
                    gc.collect()
                    self._last_gc_time = datetime.utcnow()
                    memory_usage = psutil.Process().memory_info().rss / 1024 / 1024
                
                status = HealthStatus.CRITICAL
                message = f"Critical memory usage: {memory_usage:.1f}MB"
            elif memory_usage > self.thresholds.memory_warning_mb:
                status = HealthStatus.WARNING
                message = f"High memory usage: {memory_usage:.1f}MB"
            else:
                status = HealthStatus.HEALTHY
                message = f"Normal memory usage: {memory_usage:.1f}MB"

            return HealthCheckResult(
                category=HealthCategory.MEMORY,
                status=status,
                message=message,
                value=memory_usage
            )

        except Exception as e:
            logger.error(f"Error checking memory health: {e}")
            return HealthCheckResult(
                category=HealthCategory.MEMORY,
                status=HealthStatus.UNKNOWN,
                message=f"Error checking memory: {str(e)}"
            )

    def _check_performance_health(self, metrics: Dict[str, Any]) -> HealthCheckResult:
        """Check performance health"""
        try:
            avg_time = metrics.get("avg_processing_time", 0)
            success_rate = metrics.get("success_rate", 1.0)

            if success_rate < 0.5:  # Less than 50% success
                status = HealthStatus.CRITICAL
                message = f"Critical performance: {success_rate:.1%} success rate"
            elif success_rate < 0.8:  # Less than 80% success
                status = HealthStatus.WARNING
                message = f"Degraded performance: {success_rate:.1%} success rate"
            else:
                status = HealthStatus.HEALTHY
                message = f"Normal performance: {success_rate:.1%} success rate"

            return HealthCheckResult(
                category=HealthCategory.PERFORMANCE,
                status=status,
                message=message,
                value=success_rate,
                details={"avg_processing_time": avg_time}
            )

        except Exception as e:
            logger.error(f"Error checking performance health: {e}")
            return HealthCheckResult(
                category=HealthCategory.PERFORMANCE,
                status=HealthStatus.UNKNOWN,
                message=f"Error checking performance: {str(e)}"
            )

    def _check_activity_health(
        self,
        last_activity_time: float,
        has_processing_items: bool
    ) -> HealthCheckResult:
        """Check activity health"""
        if not has_processing_items:
            return HealthCheckResult(
                category=HealthCategory.ACTIVITY,
                status=HealthStatus.HEALTHY,
                message="No items being processed"
            )

        inactive_time = time.time() - last_activity_time

        if inactive_time > self.thresholds.inactivity_critical_sec:
            status = HealthStatus.CRITICAL
            message = f"No activity for {inactive_time:.1f}s"
        elif inactive_time > self.thresholds.inactivity_warning_sec:
            status = HealthStatus.WARNING
            message = f"Limited activity for {inactive_time:.1f}s"
        else:
            status = HealthStatus.HEALTHY
            message = "Normal activity levels"

        return HealthCheckResult(
            category=HealthCategory.ACTIVITY,
            status=status,
            message=message,
            value=inactive_time
        )

    def _check_error_health(self, metrics: Dict[str, Any]) -> HealthCheckResult:
        """Check error health"""
        try:
            error_rate = metrics.get("error_rate", 0.0)
            error_count = metrics.get("total_errors", 0)

            if error_rate > self.thresholds.error_rate_critical:
                status = HealthStatus.CRITICAL
                message = f"Critical error rate: {error_rate:.1%}"
            elif error_rate > self.thresholds.error_rate_warning:
                status = HealthStatus.WARNING
                message = f"High error rate: {error_rate:.1%}"
            else:
                status = HealthStatus.HEALTHY
                message = f"Normal error rate: {error_rate:.1%}"

            return HealthCheckResult(
                category=HealthCategory.ERRORS,
                status=status,
                message=message,
                value=error_rate,
                details={"error_count": error_count}
            )

        except Exception as e:
            logger.error(f"Error checking error health: {e}")
            return HealthCheckResult(
                category=HealthCategory.ERRORS,
                status=HealthStatus.UNKNOWN,
                message=f"Error checking errors: {str(e)}"
            )

    def _check_deadlocks(self, queue_info: Dict[str, Any]) -> HealthCheckResult:
        """Check for potential deadlocks"""
        try:
            stuck_items = queue_info.get("stuck_items", [])
            if not stuck_items:
                return HealthCheckResult(
                    category=HealthCategory.DEADLOCKS,
                    status=HealthStatus.HEALTHY,
                    message="No stuck items detected"
                )

            longest_stuck = max(
                time.time() - item["start_time"]
                for item in stuck_items
            )

            if longest_stuck > self.thresholds.deadlock_critical_sec:
                status = HealthStatus.CRITICAL
                message = f"Potential deadlock: {len(stuck_items)} items stuck"
            elif longest_stuck > self.thresholds.deadlock_warning_sec:
                status = HealthStatus.WARNING
                message = f"Slow processing: {len(stuck_items)} items delayed"
            else:
                status = HealthStatus.HEALTHY
                message = "Normal processing time"

            return HealthCheckResult(
                category=HealthCategory.DEADLOCKS,
                status=status,
                message=message,
                value=longest_stuck,
                details={"stuck_items": len(stuck_items)}
            )

        except Exception as e:
            logger.error(f"Error checking deadlocks: {e}")
            return HealthCheckResult(
                category=HealthCategory.DEADLOCKS,
                status=HealthStatus.UNKNOWN,
                message=f"Error checking deadlocks: {str(e)}"
            )

    async def _check_system_health(self) -> HealthCheckResult:
        """Check system health"""
        try:
            metrics = await self.system_monitor.check_system_health()
            
            if not metrics:
                return HealthCheckResult(
                    category=HealthCategory.SYSTEM,
                    status=HealthStatus.UNKNOWN,
                    message="Unable to get system metrics"
                )

            cpu_percent = metrics["cpu_percent"]
            if cpu_percent > self.thresholds.cpu_critical_percent:
                status = HealthStatus.CRITICAL
                message = f"Critical CPU usage: {cpu_percent:.1f}%"
            elif cpu_percent > self.thresholds.cpu_warning_percent:
                status = HealthStatus.WARNING
                message = f"High CPU usage: {cpu_percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY
                message = f"Normal CPU usage: {cpu_percent:.1f}%"

            return HealthCheckResult(
                category=HealthCategory.SYSTEM,
                status=status,
                message=message,
                value=cpu_percent,
                details=metrics
            )

        except Exception as e:
            logger.error(f"Error checking system health: {e}")
            return HealthCheckResult(
                category=HealthCategory.SYSTEM,
                status=HealthStatus.UNKNOWN,
                message=f"Error checking system: {str(e)}"
            )

    def _determine_overall_status(
        self,
        results: List[HealthCheckResult]
    ) -> HealthStatus:
        """Determine overall health status"""
        if any(r.status == HealthStatus.CRITICAL for r in results):
            return HealthStatus.CRITICAL
        if any(r.status == HealthStatus.WARNING for r in results):
            return HealthStatus.WARNING
        if any(r.status == HealthStatus.UNKNOWN for r in results):
            return HealthStatus.UNKNOWN
        return HealthStatus.HEALTHY

    def format_health_report(
        self,
        results: List[HealthCheckResult]
    ) -> str:
        """Format a detailed health report"""
        lines = ["Queue Health Report:"]
        
        for result in results:
            lines.append(
                f"\n{result.category.value.title()}:"
                f"\n- Status: {result.status.value}"
                f"\n- {result.message}"
            )
            if result.details:
                for key, value in result.details.items():
                    lines.append(f"  - {key}: {value}")

        return "\n".join(lines)
