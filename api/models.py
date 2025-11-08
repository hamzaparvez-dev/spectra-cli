"""Pydantic models for Spectra API."""

from pydantic import BaseModel
from typing import Optional, Dict


class ProjectContext(BaseModel):
    """Project context model."""
    stack: str
    files: Dict[str, str]


class DevOpsFiles(BaseModel):
    """DevOps files response model."""
    dockerfile: Optional[str] = None
    compose: Optional[str] = None
    github_action: Optional[str] = None


class JobResponse(BaseModel):
    """Job creation response."""
    job_id: str
    status: str


class JobStatus(BaseModel):
    """Job status response."""
    job_id: str
    status: str  # "pending", "processing", "completed", "failed"
    result: Optional[DevOpsFiles] = None
    error: Optional[str] = None

