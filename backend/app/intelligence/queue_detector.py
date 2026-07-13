import os
from typing import Optional


QUEUE_INDICATORS = {
    "celery": ["celery", "Celery", "CELERY_"],
    "redis_queue": ["redis.*queue", "rq", "dramatiq"],
    "rabbitmq": ["rabbitmq", "amqp", "pika", "aio_pika"],
    "sqs": ["boto3.*sqs", "SQS", "sqs"],
    "kafka": ["kafka", "confluent_kafka", "aiokafka"],
    "bull": ["bull", "Bull", "bullmq"],
    "sidekiq": ["sidekiq", "Sidekiq"],
}


def detect_queues(repo_path: str) -> Optional[str]:
    content = ""
    count = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if f.endswith((".py", ".js", ".ts")):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                        content += fh.read()[:2000] + "\n"
                except (OSError, IOError):
                    pass
                count += 1
                if count > 80:
                    break
        if count > 80:
            break

    for queue_name, keywords in QUEUE_INDICATORS.items():
        for kw in keywords:
            if kw in content:
                return queue_name

    return None


def detect_caching(repo_path: str) -> Optional[str]:
    content = ""
    count = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if f.endswith((".py", ".js", ".ts")):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                        content += fh.read()[:2000] + "\n"
                except (OSError, IOError):
                    pass
                count += 1
                if count > 80:
                    break
        if count > 80:
            break

    if "redis" in content.lower() and ("cache" in content.lower() or "lru" in content.lower()):
        return "redis"
    if "memcached" in content.lower():
        return "memcached"
    if "cache" in content.lower():
        return "in_memory"

    return None
