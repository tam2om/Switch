from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

s = get_settings()
celery = Celery("anm", broker=s.redis_url, backend=s.redis_url, include=["app.workers.tasks"])
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.execute_job": {"queue": "changes"},
        "app.workers.tasks.poll_category": {"queue": "polling"},
    },
    task_time_limit=3600,
    task_soft_time_limit=3300,
    result_expires=86400,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "scheduler-tick": {"task": "app.workers.tasks.scheduler_tick", "schedule": 15.0},
        "notifications": {"task": "app.workers.tasks.send_notifications", "schedule": 60.0},
        "maintenance": {"task": "app.workers.tasks.maintenance", "schedule": 3600.0},
    },
    task_always_eager=s.environment == "test",
    task_eager_propagates=True,
)
