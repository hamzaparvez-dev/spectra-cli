"""Job queue utilities using Upstash Redis.

This module handles job creation, status tracking, and result storage
for async LLM processing.
"""

import json
import uuid
from typing import Optional, Dict, Any
import os
import logging
import threading

logger = logging.getLogger(__name__)

# Redis client and flag - initialized lazily on first use
redis_client = None
USE_REDIS = False

# In-memory fallback storage (for local dev only)
_memory_store: Dict[str, Dict[str, Any]] = {}
_memory_lock = threading.Lock()
def _initialize_redis():
    """Initialize Redis connection lazily (only called when needed)."""
    global redis_client, USE_REDIS
    
    # If already initialized, skip
    if redis_client is not None:
        return
    
        return
    
    try:
        import redis
        REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
        REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN")
        
        if REDIS_URL:
            # Check if URL is a full redis:// URL or just host
            if REDIS_URL.startswith("redis://"):
                # Full redis:// URL provided (includes password)
                redis_client = redis.from_url(
                    REDIS_URL,
                    ssl=True,
                    decode_responses=True
                )
            elif REDIS_TOKEN:
                # Separate URL and token provided
                redis_client = redis.from_url(
                    REDIS_URL,
                    password=REDIS_TOKEN,
                    ssl=True,
                    decode_responses=True
                )
            else:
                logger.warning("UPSTASH_REDIS_TOKEN required when UPSTASH_REDIS_URL doesn't include credentials")
                redis_client = None
                USE_REDIS = False
                return
            
            # Test connection
            try:
                redis_client.ping()
                USE_REDIS = True
                logger.info("Using Upstash Redis for job queue")
            except Exception as e:
                logger.error(f"Redis connection test failed: {e}. Using in-memory storage")
                redis_client = None
                USE_REDIS = False
        else:
            # Fallback to in-memory for local development
            redis_client = None
            USE_REDIS = False
            logger.warning("UPSTASH_REDIS_URL not set. Using in-memory storage (not suitable for production)")
    except ImportError:
        redis_client = None
        USE_REDIS = False
        logger.warning("Redis not installed. Using in-memory storage (not suitable for production)")
    except Exception as e:
        redis_client = None
        USE_REDIS = False
        logger.error(f"Failed to connect to Redis: {e}. Using in-memory storage (not suitable for production)")


def create_job(context: Dict[str, Any]) -> str:
    """
    Create a new job and store the context.
    
    Args:
        context: Project context to process
        
    Returns:
        Job ID string
    """
    job_id = str(uuid.uuid4())
    
    # Initialize Redis lazily on first use
    _initialize_redis()
    
    if USE_REDIS and redis_client:
        try:
            # Use pipeline for atomic hash creation with TTL
            pipe = redis_client.pipeline()
            pipe.hset(f"job:{job_id}", mapping={
                "status": "pending",
                "context": json.dumps(context),
                "result": json.dumps(None),
                "error": json.dumps(None)
            })
            pipe.expire(f"job:{job_id}", 3600)  # 1 hour TTL
            pipe.execute()
        except Exception as e:
            logger.error(f"Failed to store job in Redis: {e}, falling back to memory")
            with _memory_lock:
                _memory_store[f"job:{job_id}"] = {
                    "status": "pending",
                    "context": context,
                    "result": None,
                    "error": None
                }
    else:
        with _memory_lock:
            _memory_store[f"job:{job_id}"] = {
                "status": "pending",
                "context": context,
                "result": None,
                "error": None
            }
    
    logger.info(f"Created job {job_id}")
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get job data by ID.
    
    Args:
        job_id: Job ID
        
    Returns:
        Job data dict or None if not found
    """
    # Initialize Redis lazily on first use
    _initialize_redis()
    
    if USE_REDIS and redis_client:
        try:
            data = redis_client.hgetall(f"job:{job_id}")
            if data:
                # Convert hash fields back to proper types
                result = {
                    "status": data.get("status", "pending"),
                    "context": json.loads(data.get("context", "{}")),
                }
                # Parse result field if it exists
                if "result" in data and data["result"]:
                    result["result"] = json.loads(data["result"])
                else:
                    result["result"] = None
                # Parse error field if it exists
                if "error" in data and data["error"]:
                    result["error"] = json.loads(data["error"])
                else:
                    result["error"] = None
                return result
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse job data from Redis for job {job_id}: {e}")
            with _memory_lock:
                return _memory_store.get(f"job:{job_id}")
        except Exception as e:
            logger.error(f"Failed to get job from Redis: {e}, trying memory")
            with _memory_lock:
                return _memory_store.get(f"job:{job_id}")
    else:
        with _memory_lock:
            return _memory_store.get(f"job:{job_id}")


def update_job_status(job_id: str, status: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
    """
    Update job status and optionally store result or error.
    Uses atomic Redis pipeline to update individual fields without race conditions.
    
    Args:
        job_id: Job ID
        status: New status ("pending", "processing", "completed", "failed")
        result: Optional result data
        error: Optional error message
    """
    # Initialize Redis lazily on first use
    _initialize_redis()
    
    if USE_REDIS and redis_client:
        try:
            # Use pipeline for atomic field updates and TTL refresh
            pipe = redis_client.pipeline()
            
            # Update status field atomically
            pipe.hset(f"job:{job_id}", "status", status)
            
            # Update result field if provided
            if result is not None:
                pipe.hset(f"job:{job_id}", "result", json.dumps(result))
            
            # Update error field if provided
            if error is not None:
                pipe.hset(f"job:{job_id}", "error", json.dumps(error))
            
            # Refresh TTL to 1 hour
            pipe.expire(f"job:{job_id}", 3600)
            
            # Execute all operations atomically
            pipe.execute()
            
            logger.info(f"Updated job {job_id} to status: {status}")
        except Exception as e:
            logger.error(f"Failed to update job in Redis: {e}, falling back to memory")
            # Fallback to memory store with atomic read-modify-write
            with _memory_lock:
                job_data = _memory_store.get(f"job:{job_id}")
                if not job_data:
                    logger.error(f"Job {job_id} not found in memory fallback")
                    return
                job_data["status"] = status
                if result is not None:
                    job_data["result"] = result
                if error is not None:
                    job_data["error"] = error
                _memory_store[f"job:{job_id}"] = job_data
            logger.info(f"Updated job {job_id} to status: {status} (memory fallback)")
    else:
        # In-memory fallback - atomic read-modify-write
        with _memory_lock:
            job_data = _memory_store.get(f"job:{job_id}")
            if not job_data:
                logger.error(f"Job {job_id} not found")
                return
            job_data["status"] = status
            if result is not None:
                job_data["result"] = result
            if error is not None:
                job_data["error"] = error
            _memory_store[f"job:{job_id}"] = job_data
        logger.info(f"Updated job {job_id} to status: {status}")

