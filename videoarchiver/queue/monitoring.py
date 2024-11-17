"""Queue monitoring and health checks"""

import asyncio
import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Set
from datetime import datetime, timedelta

from videoarchiver.queue.health_checker import HealthChecker, HealthStatus, HealthCategory
from videoarchiver.queue.recovery_manager import RecoveryManager, RecoveryStrategy

logger = logging.getLogger("QueueMonitoring")

class MonitoringLevel(Enum):
    """Monitoring intensity levels"""
    LIGHT = "light"      # Basic monitoring
    NORMAL = "normal"    # Standard monitoring
    INTENSIVE = "intensive"  # Detailed monitoring
    DEBUG = "debug"      # Debug-level monitoring

class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class MonitoringEvent:
    """Represents a monitoring event"""
    timestamp: datetime
    category: HealthCategory
    severity: AlertSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolution_time: Optional[datetime] = None

@dataclass
class MonitoringThresholds:
    """Monitoring thresholds configuration"""
    check_interval: int = 15        # 15 seconds
    deadlock_threshold: int = 60    # 1 minute
    memory_threshold: int = 512     # 512MB
    max_retries: int = 3
    alert_threshold: int = 5        # Max alerts before escalation
    recovery_timeout: int = 300     # 5 minutes
    intensive_threshold: int = 0.8  # 80% resource usage triggers intensive

class AlertManager:
    """Manages monitoring alerts"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.active_alerts: Dict[str, MonitoringEvent] = {}
        self.alert_history: List[MonitoringEvent] = []
        self.alert_counts: Dict[AlertSeverity, int] = {
            severity: 0 for severity in AlertSeverity
        }

    def create_alert(
        self,
        category: HealthCategory,
        severity: AlertSeverity,
        message: str,
        details: Dict[str, Any] = None
    ) -> MonitoringEvent:
        """Create a new alert"""
        event = MonitoringEvent(
            timestamp=datetime.utcnow(),
            category=category,
            severity=severity,
            message=message,
            details=details or {}
        )
        
        alert_id = f"{category.value}_{event.timestamp.timestamp()}"
        self.active_alerts[alert_id] = event
        self.alert_counts[severity] += 1
        
        self.alert_history.append(event)
        if len(self.alert_history) > self.max_history:
            self.alert_history.pop(0)
        
        return event

    def resolve_alert(self, alert_id: str) -> None:
        """Mark an alert as resolved"""
        if alert_id in self.active_alerts:
            event = self.active_alerts[alert_id]
            event.resolved = True
            event.resolution_time = datetime.utcnow()
            self.active_alerts.pop(alert_id)

    def get_active_alerts(self) -> List[MonitoringEvent]:
        """Get currently active alerts"""
        return list(self.active_alerts.values())

    def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert statistics"""
        return {
            "active_alerts": len(self.active_alerts),
            "total_alerts": len(self.alert_history),
            "alert_counts": {
                severity.value: count
                for severity, count in self.alert_counts.items()
            },
            "recent_alerts": [
                {
                    "timestamp": event.timestamp.isoformat(),
                    "category": event.category.value,
                    "severity": event.severity.value,
                    "message": event.message,
                    "resolved": event.resolved
                }
                for event in self.alert_history[-10:]  # Last 10 alerts
            ]
        }

class MonitoringStrategy:
    """Determines monitoring behavior"""

    def __init__(
        self,
        level: MonitoringLevel = MonitoringLevel.NORMAL,
        thresholds: Optional[MonitoringThresholds] = None
    ):
        self.level = level
        self.thresholds = thresholds or MonitoringThresholds()
        self._last_intensive_check = datetime.utcnow()

    def should_check_health(self, metrics: Dict[str, Any]) -> bool:
        """Determine if health check should be performed"""
        if self.level == MonitoringLevel.INTENSIVE:
            return True
        elif self.level == MonitoringLevel.LIGHT:
            return metrics.get("queue_size", 0) > 0
        else:  # NORMAL or DEBUG
            return True

    def get_check_interval(self) -> float:
        """Get the current check interval"""
        if self.level == MonitoringLevel.INTENSIVE:
            return self.thresholds.check_interval / 2
        elif self.level == MonitoringLevel.LIGHT:
            return self.thresholds.check_interval * 2
        else:  # NORMAL or DEBUG
            return self.thresholds.check_interval

    def should_escalate(self, alert_count: int) -> bool:
        """Determine if monitoring should be escalated"""
        return (
            self.level != MonitoringLevel.INTENSIVE and
            alert_count >= self.thresholds.alert_threshold
        )

    def should_deescalate(self, alert_count: int) -> bool:
        """Determine if monitoring can be deescalated"""
        return (
            self.level == MonitoringLevel.INTENSIVE and
            alert_count == 0 and
            (datetime.utcnow() - self._last_intensive_check).total_seconds() > 300
        )

class QueueMonitor:
    """Monitors queue health and performance"""

    def __init__(
        self,
        strategy: Optional[MonitoringStrategy] = None,
        thresholds: Optional[MonitoringThresholds] = None
    ):
        self.strategy = strategy or MonitoringStrategy()
        self.thresholds = thresholds or MonitoringThresholds()
        
        # Initialize components
        self.health_checker = HealthChecker(
            memory_threshold=self.thresholds.memory_threshold,
            deadlock_threshold=self.thresholds.deadlock_threshold
        )
        self.recovery_manager = RecoveryManager(max_retries=self.thresholds.max_retries)
        self.alert_manager = AlertManager()
        
        self._shutdown = False
        self._last_active_time = time.time()
        self._monitoring_task: Optional[asyncio.Task] = None

    async def start(self, state_manager, metrics_manager) -> None:
        """Start monitoring queue health"""
        if self._monitoring_task is not None:
            logger.warning("Monitoring task already running")
            return

        logger.info(f"Starting queue monitoring with level: {self.strategy.level.value}")
        self._monitoring_task = asyncio.create_task(
            self._monitor_loop(state_manager, metrics_manager)
        )

    async def _monitor_loop(self, state_manager, metrics_manager) -> None:
        """Main monitoring loop"""
        while not self._shutdown:
            try:
                # Get current metrics
                metrics = metrics_manager.get_metrics()
                
                # Check if health check should be performed
                if self.strategy.should_check_health(metrics):
                    await self._perform_health_check(
                        state_manager,
                        metrics_manager,
                        metrics
                    )

                # Check for strategy adjustment
                self._adjust_monitoring_strategy(metrics)
                
                # Wait for next check
                await asyncio.sleep(self.strategy.get_check_interval())
                
            except asyncio.CancelledError:
                logger.info("Queue monitoring cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the monitoring process"""
        logger.info("Stopping queue monitoring...")
        self._shutdown = True
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        self._monitoring_task = None

    def update_activity(self) -> None:
        """Update the last active time"""
        self._last_active_time = time.time()

    async def _perform_health_check(
        self,
        state_manager,
        metrics_manager,
        current_metrics: Dict[str, Any]
    ) -> None:
        """Perform health check and recovery if needed"""
        try:
            # Check memory usage
            memory_usage, is_critical = await self.health_checker.check_memory_usage()
            metrics_manager.update_memory_usage(memory_usage)

            if is_critical:
                self.alert_manager.create_alert(
                    category=HealthCategory.MEMORY,
                    severity=AlertSeverity.CRITICAL,
                    message=f"Critical memory usage: {memory_usage:.1f}MB",
                    details={"memory_usage": memory_usage}
                )

            # Get current queue state
            queue_stats = await state_manager.get_queue_stats()
            processing_items = await state_manager.get_all_processing_items()

            # Check for stuck items
            stuck_items = []
            for item in processing_items:
                if self.recovery_manager.should_recover_item(item):
                    stuck_items.append((item.url, item))

            # Handle stuck items if found
            if stuck_items:
                self.alert_manager.create_alert(
                    category=HealthCategory.DEADLOCKS,
                    severity=AlertSeverity.WARNING,
                    message=f"Potential deadlock: {len(stuck_items)} items stuck",
                    details={"stuck_items": [item[0] for item in stuck_items]}
                )
                
                await self.recovery_manager.recover_stuck_items(
                    stuck_items,
                    state_manager,
                    metrics_manager
                )

            # Check overall queue activity
            if processing_items and self.health_checker.check_queue_activity(
                self._last_active_time,
                bool(processing_items)
            ):
                self.alert_manager.create_alert(
                    category=HealthCategory.ACTIVITY,
                    severity=AlertSeverity.ERROR,
                    message="Queue appears to be hung",
                    details={"last_active": self._last_active_time}
                )
                
                await self.recovery_manager.perform_emergency_recovery(
                    state_manager,
                    metrics_manager
                )
                self.update_activity()

            # Check error rates
            error_rate = current_metrics.get("error_rate", 0)
            if error_rate > 0.2:  # 20% error rate
                self.alert_manager.create_alert(
                    category=HealthCategory.ERRORS,
                    severity=AlertSeverity.ERROR,
                    message=f"High error rate: {error_rate:.1%}",
                    details={"error_rate": error_rate}
                )

            # Log health report
            if self.strategy.level in (MonitoringLevel.INTENSIVE, MonitoringLevel.DEBUG):
                health_report = self.health_checker.format_health_report(
                    memory_usage=memory_usage,
                    queue_size=queue_stats["queue_size"],
                    processing_count=queue_stats["processing_count"],
                    success_rate=metrics_manager.success_rate,
                    avg_processing_time=metrics_manager.avg_processing_time,
                    peak_memory=metrics_manager.peak_memory_usage,
                    error_distribution=metrics_manager.errors_by_type,
                    last_activity_delta=time.time() - self._last_active_time
                )
                logger.info(health_report)

        except Exception as e:
            logger.error(f"Error performing health check: {str(e)}")
            self.alert_manager.create_alert(
                category=HealthCategory.SYSTEM,
                severity=AlertSeverity.ERROR,
                message=f"Health check error: {str(e)}"
            )

    def _adjust_monitoring_strategy(self, metrics: Dict[str, Any]) -> None:
        """Adjust monitoring strategy based on current state"""
        active_alerts = self.alert_manager.get_active_alerts()
        
        # Check for escalation
        if self.strategy.should_escalate(len(active_alerts)):
            logger.warning("Escalating to intensive monitoring")
            self.strategy.level = MonitoringLevel.INTENSIVE
            self.strategy._last_intensive_check = datetime.utcnow()
        
        # Check for de-escalation
        elif self.strategy.should_deescalate(len(active_alerts)):
            logger.info("De-escalating to normal monitoring")
            self.strategy.level = MonitoringLevel.NORMAL

    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Get comprehensive monitoring statistics"""
        return {
            "monitoring_level": self.strategy.level.value,
            "last_active": self._last_active_time,
            "alerts": self.alert_manager.get_alert_stats(),
            "recovery": self.recovery_manager.get_recovery_stats(),
            "health": self.health_checker.get_health_stats()
        }

class MonitoringError(Exception):
    """Base exception for monitoring-related errors"""
    pass
