"""Shared Celery application instance with beat schedule.

All tasks in ``app/tasks/`` import their Celery app from here so there is a
single broker/backend configuration and a single beat scheduler entry point.

Beat schedule
-------------
``run_retention_sweep`` runs daily at 02:00 UTC.  It deletes ``audit_logs``
rows older than each org's ``retention_days`` threshold, fulfilling the SOC-2
CC6.5 and GDPR Article 5(1)(e) data-minimisation requirements.
"""

import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "aegis",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.ingestion",
        "app.tasks.retention",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "retention-sweep-daily": {
            "task": "app.tasks.retention.run_retention_sweep",
            "schedule": crontab(hour=2, minute=0),  # 02:00 UTC every day
            "options": {"queue": "celery"},
        },
    },
)
