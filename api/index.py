"""Spectra API - Production-ready FastAPI application for DevOps file generation.

This is a clean, minimal version optimized for Vercel deployment.
"""

import os
import sys
import json
import logging
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Import dependencies
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import httpx
except ImportError as e:
    logger.error(f"Failed to import required dependencies: {e}")
    raise

# Import local modules
try:
    from api.models import ProjectContext, DevOpsFiles, JobResponse, JobStatus
    from api.templates import get_template_for_stack
    from api.job_queue import create_job, get_job, update_job_status
    logger.info("Successfully imported all modules")
except ImportError as e:
    logger.error(f"Failed to import local modules: {e}")
    raise

# Initialize FastAPI app
app = FastAPI(
    title="Spectra API",
    description="AI-powered DevOps file generator",
    version="0.2.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.0-flash-exp:free"

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "Spectra API",
        "version": "0.2.0",
        "status": "online",
        "endpoints": {
            "POST /": "Generate DevOps files or create async job",
            "POST /jobs": "Create a new job",
            "GET /job/{job_id}": "Get job status and result",
            "POST /process/{job_id}": "Trigger job processing",
            "GET /health": "Health check"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "spectra-api",
        "version": "0.2.0"
    }

@app.post("/", response_model=DevOpsFiles)
async def generate_devops_files(context: ProjectContext):
    """Generate DevOps files for a project."""
    try:
        # Try template matching first (fast path)
        template = get_template_for_stack(context.stack)
        if template:
            logger.info(f"Template cache hit for stack: {context.stack}")
            return template
        
        # If no template, use LLM (slow path)
        if not OPENROUTER_API_KEY:
            raise HTTPException(
                status_code=500,
                detail="OpenRouter API key not configured"
            )
        
        logger.info(f"Generating custom files for stack: {context.stack}")
        
        # Create prompt for LLM
        prompt = f"""Generate production-ready DevOps files for a {context.stack} project.

Project files:
{json.dumps(context.files, indent=2)}

Generate:
1. Dockerfile - Multi-stage, optimized, with health checks
2. docker-compose.yml - For local development
3. GitHub Actions CI/CD workflow

Return ONLY valid JSON in this exact format:
{{
  "dockerfile": "...",
  "compose": "...",
  "github_action": "..."
}}"""

        # Call OpenRouter API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://spectra-cli.vercel.app",
                    "X-Title": "Spectra CLI"
                },
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"OpenRouter API error: {response.text}"
                )
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Parse JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            files = json.loads(content)
            return DevOpsFiles(**files)
            
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse AI response")
    except Exception as e:
        logger.error(f"Error generating files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs", response_model=JobResponse)
async def create_job_endpoint(context: ProjectContext):
    """Create a new async job."""
    try:
        job_id = create_job(context.dict())
        return JobResponse(job_id=job_id, status="pending")
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/job/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get job status and result."""
    try:
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobStatus(
            job_id=job_id,
            status=job["status"],
            result=DevOpsFiles(**job["result"]) if job.get("result") else None,
            error=job.get("error")
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process/{job_id}")
async def process_job(job_id: str):
    """Trigger async job processing."""
    try:
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job["status"] != "pending":
            return {"message": "Job already processed"}
        
        # Update status to processing
        update_job_status(job_id, "processing")
        
        # Process the job
        context = ProjectContext(**job["context"])
        result = await generate_devops_files(context)
        
        # Update with result
        update_job_status(job_id, "completed", result=result.dict())
        
        return {"message": "Job processed successfully"}
        
    except Exception as e:
        logger.error(f"Failed to process job: {e}")
        update_job_status(job_id, "failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Export for Vercel
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
    logger.info("Mangum handler created successfully")
except Exception as e:
    logger.error(f"Failed to create Mangum handler: {e}")
    handler = app
