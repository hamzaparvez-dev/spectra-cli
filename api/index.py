"""FastAPI serverless function for Spectra API brain."""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import Optional
import os
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client (will be created lazily if API key is available)
def get_openai_client() -> OpenAI:
    """Get or create OpenAI client with API key validation."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key)

app = FastAPI(
    title="Spectra API",
    description="AI-powered DevOps file generator",
    version="0.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProjectContext(BaseModel):
    """Project context model."""
    stack: str
    files: dict


class DevOpsFiles(BaseModel):
    """DevOps files response model."""
    dockerfile: Optional[str] = None
    compose: Optional[str] = None
    github_action: Optional[str] = None


def get_llm_response(context: ProjectContext) -> DevOpsFiles:
    """
    Calls the OpenAI API to generate the DevOps files.
    
    Args:
        context: Project context containing stack and files
        
    Returns:
        DevOpsFiles object with generated content
        
    Raises:
        HTTPException: If API key is missing or OpenAI call fails
    """
    try:
        openai_client = get_openai_client()
    except ValueError:
        logger.error("OPENAI_API_KEY is not set!")
        raise HTTPException(
            status_code=500,
            detail="OpenAI API key is not configured on the server."
        )

    # Convert file context to a more readable string for the prompt
    file_context_str = "\n".join([
        f"--- File: {filename} ---\n{content}\n"
        for filename, content in context.files.items()
    ])
    
    system_prompt = (
        "You are 'Spectra', an expert DevOps engineer. Your sole purpose is to generate "
        "production-ready DevOps files based on a project's context. You MUST return ONLY "
        "a valid JSON object with three keys: 'dockerfile', 'compose', and 'github_action'. "
        "All files should be production-ready, secure, and follow best practices."
    )
    
    user_prompt = f"""A developer needs DevOps files for their project.

Project Context:
- Detected Stack: {context.stack}
- Relevant Files:
{file_context_str}

Instructions:
1. **dockerfile**: Create a multi-stage, production-optimized Dockerfile. It must be efficient, secure, and use best practices (non-root user, minimal layers, proper caching).
2. **compose**: Create a `docker-compose.yml` file for local development. It should build from the Dockerfile and map the necessary ports. Include proper service definitions.
3. **github_action**: Create a GitHub Actions workflow file (`.github/workflows/ci-cd.yml`). It should trigger on push to 'main' and pull requests, build the Docker image, run tests if applicable, and push it to GitHub Container Registry (GHCR) with proper tagging.

Return ONLY the valid JSON object with these exact keys: dockerfile, compose, github_action.
Example format: {{"dockerfile": "FROM...", "compose": "version: '3.8'...", "github_action": "name: CI/CD..."}}"""
    
    try:
        logger.info(f"Calling OpenAI API for stack: {context.stack}")
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",  # Using the latest available model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4000
        )
        
        response_json_str = response.choices[0].message.content
        logger.info("AI Response received successfully")
        
        # Parse the JSON string from the LLM
        data = json.loads(response_json_str)
        
        return DevOpsFiles(
            dockerfile=data.get('dockerfile'),
            compose=data.get('compose'),
            github_action=data.get('github_action')
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response from OpenAI: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse AI response: {e}"
        )
    except Exception as e:
        logger.error(f"Error calling OpenAI or parsing response: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"AI model error: {str(e)}"
        )


@app.post("/", response_model=DevOpsFiles)
async def generate_devops(request: Request):
    """
    Main API endpoint. Receives project context and returns DevOps files.
    
    Args:
        request: FastAPI request object
        
    Returns:
        DevOpsFiles object containing generated files
        
    Raises:
        HTTPException: If request is invalid or processing fails
    """
    logger.info("API request received")
    try:
        raw_body = await request.body()
        data = json.loads(raw_body)
        context = ProjectContext(**data)
        
        logger.info(f"Processing project with stack: {context.stack}")
        
        files = get_llm_response(context)
        
        logger.info("Successfully generated DevOps files")
        return files
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload received")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request data: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in API: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {
        "status": "ok",
        "service": "spectra-api",
        "version": "0.1.0"
    }


@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "service": "Spectra API",
        "version": "0.1.0",
        "endpoints": {
            "POST /": "Generate DevOps files",
            "GET /health": "Health check"
        }
    }

