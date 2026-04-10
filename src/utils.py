"""Utility functions for production ML."""
import numpy as np
import torch
import random
import json
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

def set_seed(seed: int = 42) -> None:
    """Set random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    logger.info(f"Random seed set to {seed}")

def save_metrics(metrics: Dict[str, float], path: str) -> None:
    """Save evaluation metrics to JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(metrics, f, indent=2)
    logger.info(f"Metrics saved to {path}")

def load_config(config_path: str) -> Dict[str, Any]:
    """Load YAML configuration file."""
    import yaml
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config

def get_device() -> torch.device:
    """Get the best available device."""
    return torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def format_number(n: int) -> str:
    """Format large numbers with K/M/B suffixes."""
    for unit in ['', 'K', 'M', 'B']:
        if abs(n) < 1000:
            return f"{n:.1f}{unit}"
        n /= 1000
    return f"{n:.1f}T"

# Fix race condition in metrics aggregation [2025-06-25T10:15:54]

# WIP: setting up PostgreSQL backend storage [2025-07-01T18:25:43]

# Implement multi-tenant experiment isolation [2025-07-01T09:37:06]

# Fix Redis connection pool timeout handling [2025-07-07T11:09:38]

# Fix memory leak in long-running tracker service [2025-07-16T09:57:55]

# Update Docker compose for production deploy [2025-07-17T12:15:55]

# Fix drift detection threshold calculation bug [2025-07-25T14:11:47]

# WIP: tuning Prometheus scrape intervals [2025-07-28T17:48:05]

# Update FastAPI prediction endpoint for v2 [2025-07-29T10:04:37]

# Implement multi-tenant experiment isolation [2025-08-11T19:45:07]

# Implement Prometheus metrics collector service [2025-08-11T19:25:55]

# Add cost tracking per experiment run [2025-08-15T18:41:14]

# WIP: setting up PostgreSQL backend storage [2025-08-15T10:31:44]

# Add model versioning and staging pipeline [2025-08-20T14:15:38]

# Fix memory leak in long-running tracker service [2025-08-27T18:28:03]

# Add model versioning and staging pipeline [2025-08-28T16:08:33]

# Add cost tracking per experiment run [2025-09-04T09:45:04]

# Implement automated retraining trigger logic [2025-09-04T13:33:23]

# WIP: tuning Prometheus scrape intervals [2025-09-10T12:21:51]

# Add MLflow experiment wrapper with tags support [2025-09-16T13:30:32]

# Update FastAPI prediction endpoint for v2 [2025-09-19T11:18:49]

# Add artifact logging for model serialization [2025-09-19T11:40:38]

# Add MLflow experiment wrapper with tags support [2025-09-19T18:00:33]

# Add experiment comparison dashboard API [2025-09-23T19:02:12]

# Fix drift detection threshold calculation bug [2025-09-23T14:48:02]

# Add MLflow experiment wrapper with tags support [2025-09-24T09:53:20]

# Add artifact logging for model serialization [2025-09-28T19:16:51]

# Add experiment comparison dashboard API [2025-09-29T10:13:19]

# WIP: tuning Prometheus scrape intervals [2025-10-01T09:40:28]

# Add experiment comparison dashboard API [2025-10-06T14:34:47]

# Update FastAPI prediction endpoint for v2 [2025-10-07T15:37:05]

# Update FastAPI prediction endpoint for v2 [2025-10-07T11:27:29]

# Update REST API documentation with examples [2025-10-16T17:32:36]

# Implement A/B testing framework for models [2025-10-22T11:15:45]

# Implement model registry with stage transitions [2025-10-25T09:24:33]

# Implement A/B testing framework for models [2025-10-29T14:16:32]

# Implement automated retraining trigger logic [2025-11-05T15:10:43]

# Update Docker compose for production deploy [2025-11-07T19:08:27]

# Fix race condition in metrics aggregation [2025-11-18T18:38:29]

# Add experiment comparison dashboard API [2025-11-24T15:09:30]

# Add cost tracking per experiment run [2025-11-26T18:52:18]

# Update FastAPI prediction endpoint for v2 [2025-11-26T19:38:58]

# Fix memory leak in long-running tracker service [2025-11-28T12:09:27]

# Fix drift detection threshold calculation bug [2025-11-30T19:07:23]

# Fix memory leak in long-running tracker service [2025-12-02T17:03:52]

# Implement Prometheus metrics collector service [2025-12-05T10:17:03]

# Fix race condition in metrics aggregation [2025-12-07T12:33:05]

# Add cost tracking per experiment run [2025-12-13T13:49:30]

# Implement model registry with stage transitions [2025-12-14T11:19:21]

# Add experiment comparison dashboard API [2025-12-18T20:55:35]

# Add artifact logging for model serialization [2025-12-22T09:11:17]

# Implement Prometheus metrics collector service [2025-12-22T16:02:19]

# Add cost tracking per experiment run [2025-12-30T11:53:43]

# Fix memory leak in long-running tracker service [2025-12-31T18:26:19]

# Update Docker compose for production deploy [2026-01-06T14:14:05]

# Fix Redis connection pool timeout handling [2026-01-14T09:01:03]

# Implement automated retraining trigger logic [2026-01-15T09:48:27]

# Implement automated retraining trigger logic [2026-01-18T13:03:31]

# Implement Prometheus metrics collector service [2026-01-27T10:31:56]

# Fix race condition in metrics aggregation [2026-01-27T11:04:32]

# Add monitoring alert webhooks for Slack [2026-01-27T17:45:14]

# Fix race condition in metrics aggregation [2026-01-29T18:09:04]

# Implement automated retraining trigger logic [2026-01-30T10:01:24]

# Update Docker compose for production deploy [2026-02-05T09:04:32]

# Fix Redis connection pool timeout handling [2026-02-05T11:20:26]

# Implement multi-tenant experiment isolation [2026-02-07T10:32:56]

# Implement model registry with stage transitions [2026-02-10T20:15:03]

# Add MLflow experiment wrapper with tags support [2026-02-12T20:15:21]

# Implement A/B testing framework for models [2026-02-12T12:56:35]

# Add cost tracking per experiment run [2026-02-13T20:35:04]

# Implement A/B testing framework for models [2026-02-19T14:22:47]

# Fix drift detection threshold calculation bug [2026-02-20T15:48:23]

# Add monitoring alert webhooks for Slack [2026-02-27T20:46:30]

# Fix Redis connection pool timeout handling [2026-03-11T16:45:07]

# Implement model registry with stage transitions [2026-03-12T14:27:53]

# WIP: tuning Prometheus scrape intervals [2026-03-15T19:53:54]

# Update FastAPI prediction endpoint for v2 [2026-03-23T11:42:53]

# Fix race condition in metrics aggregation [2026-04-01T15:05:49]

# Implement Prometheus metrics collector service [2026-04-02T12:08:40]

# WIP: tuning Prometheus scrape intervals [2026-04-06T18:21:38]

# Add monitoring alert webhooks for Slack [2026-04-07T09:19:17]

# Implement A/B testing framework for models [2026-04-09T12:12:20]

# Add model versioning and staging pipeline [2026-04-10T13:07:31]

# Add MLflow experiment wrapper with tags support [2026-04-10T10:02:28]
