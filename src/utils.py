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
