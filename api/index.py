"""FastAPI serverless function for Spectra API brain with async job queue."""

import sys
import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any

# Configure logging FIRST - before any logger usage
# Use try-except to ensure logging setup never fails
try:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
except Exception:
    # Fallback if logging setup fails
    logging.basicConfig()
    logger = logging.getLogger(__name__)

# Ensure api directory is in Python path for direct imports (Vercel compatibility)
try:
    api_dir = os.path.dirname(os.path.abspath(__file__))
    if api_dir and api_dir not in sys.path:
        sys.path.insert(0, api_dir)
except (NameError, AttributeError):
    # __file__ might not be available in some environments
    # Try to add current working directory or api directory
    try:
        if 'api' not in str(sys.path):
            # Try adding common paths
            for path in [os.getcwd(), '/var/task/api', '/var/task']:
                if os.path.exists(path) and path not in sys.path:
                    sys.path.insert(0, path)
    except Exception:

        pass

# Import BaseModel separately - needed even in fallback mode
try:
    from pydantic import BaseModel
except ImportError:
    # If pydantic is not available, create a minimal BaseModel fallback
    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

# Try to import FastAPI and dependencies. If it fails, provide a minimal handler.
FALLBACK_MODE = False
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
except Exception as e:
    FALLBACK_MODE = True
    logger.error(f"FastAPI import failed: {e}")

# Direct imports - all files are in the same directory in Vercel serverless
# Wrap in try-except to handle import errors gracefully
IMPORTS_OK = False
try:
    from models import ProjectContext, DevOpsFiles, JobResponse, JobStatus
    from templates import get_template
    from job_queue import create_job, get_job, update_job_status
    IMPORTS_OK = True
except ImportError as e:
    IMPORTS_OK = False
    logger.error(f"Failed to import modules: {e}")
except Exception as e:
    # Catch any other exceptions during import to prevent module load failure
    IMPORTS_OK = False
    logger.error(f"Unexpected error importing modules: {e}", exc_info=True)
    # Define minimal fallbacks to prevent complete failure
    # These inherit from BaseModel to work with FastAPI response_model
    class ProjectContext(BaseModel):
        stack: str = "unknown"
        files: Dict[str, str] = {}
    
    class DevOpsFiles(BaseModel):
        dockerfile: Optional[str] = None
        compose: Optional[str] = None
        github_action: Optional[str] = None
    
    class JobResponse(BaseModel):
        job_id: str = ""
        status: str = "pending"
    
    class JobStatus(BaseModel):
        job_id: str = ""
        status: str = "pending"
        result: Optional[DevOpsFiles] = None
        error: Optional[str] = None
    
    def get_template(stack):
        logger.error(f"get_template called in fallback mode (stack: {stack}) - imports failed")
        raise ImportError(f"get_template unavailable: required modules not imported (stack: {stack})")
    
    def create_job(context):
        stack = context.get('stack', 'unknown') if isinstance(context, dict) else getattr(context, 'stack', 'unknown')
        logger.error(f"create_job called in fallback mode (stack: {stack}) - imports failed")
        raise ImportError(f"create_job unavailable: required modules not imported (stack: {stack})")
    
    def get_job(job_id):
        logger.error(f"get_job called in fallback mode (job_id: {job_id}) - imports failed")
        raise ImportError(f"get_job unavailable: required modules not imported (job_id: {job_id})")
    
    def update_job_status(job_id, status, result=None, error=None):
        logger.error(f"update_job_status called in fallback mode (job_id: {job_id}, status: {status}) - imports failed")
        raise ImportError(f"update_job_status unavailable: required modules not imported (job_id: {job_id}, status: {status})")

# Initialize app variable and handler variables to None first to ensure they're always defined
app = None
_mangum_available = False
mangum_handler = None

# Only initialize FastAPI app if not in fallback mode
# Wrap in try-except to prevent module load failures
try:
    if not FALLBACK_MODE:
        # Initialize Gemini client (defer heavy import until needed)
        def get_gemini_client():
            """Get or configure Gemini client with API key validation."""
            # Import inside function to avoid module-level import failure
            import google.genai as genai
            api_key = os.getenv("OPENAI_API_KEY")  # Keep variable name as requested
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable is not set")
            genai.configure(api_key=api_key)
            # Use gemini-2.5-flash for faster, cheaper responses
            return genai.GenerativeModel('gemini-2.5-flash')

        def parse_and_validate_cors_origins():
            """
            Parse and validate CORS allowed origins from environment variable.
            
            Reads CORS_ALLOWED_ORIGINS environment variable (comma-separated list).
            Validates that origins are properly formatted URLs.
            
            Returns:
                Tuple of (regular_origins, regex_origins) where:
                - regular_origins: List of validated origin URLs
                - regex_origins: List of regex patterns for allow_origin_regex
            """
            origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
            if not origins_str:
                return [], []
            
            regular_origins = []
            regex_origins = []
            
            for origin in origins_str.split(","):
                origin = origin.strip()
                if not origin:
                    continue
                
                # Basic validation: must be a valid URL format
                # Allow http://, https://, or specific patterns
                if origin == "*":
                    logger.warning("CORS origin '*' detected in CORS_ALLOWED_ORIGINS. This will be ignored if allow_credentials=True.")
                    regular_origins.append(origin)
                elif origin.startswith(("http://", "https://")):
                    # Normalize: remove trailing slashes
                    origin = origin.rstrip("/")
                    regular_origins.append(origin)
                elif origin.startswith("regex:"):
                    # Support regex patterns (will use allow_origin_regex)
                    regex_pattern = origin[6:].strip()  # Remove "regex:" prefix
                    if regex_pattern:
                        regex_origins.append(regex_pattern)
                    else:
                        logger.warning(f"Empty regex pattern after 'regex:' prefix. Skipping.")
                else:
                    logger.warning(f"Invalid CORS origin format: {origin}. Skipping.")
            
            return regular_origins, regex_origins

        app = FastAPI(
            title="Spectra API",
            description="AI-powered DevOps file generator with template caching and async processing",
            version="0.2.0"
        )

        # Parse and validate CORS origins from environment
        regular_origins, regex_origins = parse_and_validate_cors_origins()
        cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
        
        # Security check: cannot use allow_origins=["*"] with allow_credentials=True
        has_wildcard = "*" in regular_origins
        has_any_origins = len(regular_origins) > 0 or len(regex_origins) > 0
        
        if cors_allow_credentials:
            if not has_any_origins or has_wildcard:
                logger.warning(
                    "CORS_ALLOWED_ORIGINS not configured or contains '*', but CORS_ALLOW_CREDENTIALS=True. "
                    "This is rejected by browsers. Setting allow_credentials=False for security."
                )
                cors_allow_credentials = False
        
        # If no origins configured and credentials disabled, allow all (public API)
        if not has_any_origins and not cors_allow_credentials:
            regular_origins = ["*"]
            logger.info("No CORS origins configured. Using allow_origins=['*'] with allow_credentials=False (public API).")
        elif not has_any_origins:
            # If credentials are needed but no origins, default to empty (most restrictive)
            logger.warning("CORS_ALLOWED_ORIGINS not configured but credentials enabled. No origins will be allowed.")
            regular_origins = []
        
        # Build CORS middleware configuration
        cors_config = {
            "allow_credentials": cors_allow_credentials,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
        
        if regular_origins:
            cors_config["allow_origins"] = regular_origins
        if regex_origins:
            cors_config["allow_origin_regex"] = "|".join(f"({pattern})" for pattern in regex_origins)
        
        logger.info(f"CORS configuration: allow_origins={regular_origins}, allow_credentials={cors_allow_credentials}, "
                    f"allow_origin_regex={'configured' if regex_origins else 'none'}")
        
        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            **cors_config
        )

        # Normal mode - define get_llm_response and all routes
        async def get_llm_response(context: ProjectContext, timeout: float = 120.0) -> DevOpsFiles:
            """
            Calls the Gemini API to generate the DevOps files asynchronously with timeout handling.
            
            Args:
                context: Project context containing stack and files
                timeout: Maximum time to wait for LLM response in seconds (default: 120)
                
            Returns:
                DevOpsFiles object with generated content
                
            Raises:
                HTTPException: If API key is missing or Gemini call fails
                asyncio.TimeoutError: If the LLM call exceeds the timeout
            """
            try:
                model = get_gemini_client()
            except ValueError:
                logger.error("OPENAI_API_KEY is not set!")
                raise HTTPException(
                    status_code=500,
                    detail="API key is not configured on the server."
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
            
            # Combine system and user prompts for Gemini
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            
            def _call_gemini_sync():
                """Synchronous wrapper for Gemini API call to run in thread pool."""
                try:
                    logger.info(f"Calling Gemini API for stack: {context.stack}")
                    # Use gemini-2.5-flash optimized config for faster responses
                    response = model.generate_content(
                        full_prompt,
                        generation_config={
                            "temperature": 0.1,
                            "max_output_tokens": 3000,
                            "top_p": 0.95,
                            "top_k": 40,
                        }
                    )
                    if not response or not hasattr(response, 'text'):
                        raise ValueError("Invalid response from Gemini API: missing text attribute")
                    return response.text.strip()
                except Exception as e:
                    logger.error(f"Gemini API call failed: {e}", exc_info=True)
                    raise
            
            try:
                # Run the blocking Gemini API call in a thread pool with timeout
                # Use asyncio.to_thread for Python 3.9+, fallback to run_in_executor for Python 3.8
                logger.info(f"Starting async LLM call for stack: {context.stack} with timeout: {timeout}s")
                if hasattr(asyncio, 'to_thread'):
                    # Python 3.9+
                    response_json_str = await asyncio.wait_for(
                        asyncio.to_thread(_call_gemini_sync),
                        timeout=timeout
                    )
                else:
                    # Python 3.8 compatibility
                    loop = asyncio.get_event_loop()
                    response_json_str = await asyncio.wait_for(
                        loop.run_in_executor(None, _call_gemini_sync),
                        timeout=timeout
                    )
                logger.info("AI Response received successfully")
                
                # Clean up response if it has markdown code blocks
                if response_json_str.startswith("```json"):
                    response_json_str = response_json_str.replace("```json", "").replace("```", "").strip()
                elif response_json_str.startswith("```"):
                    response_json_str = response_json_str.replace("```", "").strip()
                
                # Parse the JSON string from the LLM
                data = json.loads(response_json_str)
                
                return DevOpsFiles(
                    dockerfile=data.get('dockerfile'),
                    compose=data.get('compose'),
                    github_action=data.get('github_action')
                )
                
            except asyncio.TimeoutError:
                logger.error(f"LLM call timed out after {timeout} seconds for stack: {context.stack}")
                raise HTTPException(
                    status_code=504,
                    detail=f"LLM request timed out after {timeout} seconds. Please try again or contact support."
                )
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response from Gemini: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to parse AI response: {e}"
                )
            except Exception as e:
                logger.error(f"Error calling Gemini or parsing response: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"AI model error: {str(e)}"
                )

        # All route definitions
        @app.post("/")
        async def generate_devops(context: ProjectContext):
            """
            Main API endpoint. Receives project context and returns DevOps files.
            
            Flow:
            1. Check if template exists for the stack -> return files immediately
            2. If no template, create a job and return job_id (for async processing)
            
            Args:
                context: Project context containing stack and files
                
            Returns:
                Dict with either:
                - {"dockerfile": "...", "compose": "...", "github_action": "..."} if template exists
                - {"job_id": "...", "status": "pending"} if job created
            """
            logger.info("API request received")
            try:
                logger.info(f"Processing project with stack: {context.stack}")
                
                # Priority 1: Check template cache first (instant response for 80% of users)
                try:
                    template = get_template(context.stack)
                    if template:
                        logger.info(f"Returning cached template for stack: {context.stack}")
                        return template.dict()
                except Exception as template_error:
                    logger.warning(f"Error checking template cache: {template_error}. Continuing with job creation.")
                
                # Priority 2: Create async job for custom stacks
                logger.info(f"No template found for stack: {context.stack}, creating async job")
                try:
                    context_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(context_dict)
                    
                    # Return job_id for polling
                    return {
                        "job_id": job_id,
                        "status": "pending"
                    }
                except Exception as job_error:
                    logger.error(f"Failed to create job: {job_error}", exc_info=True)
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create processing job: {str(job_error)}"
                    )
                
            except HTTPException:
                # Re-raise HTTPExceptions as-is
                raise
            except ValueError as e:
                logger.error(f"Validation error: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid request data: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in API: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

        @app.post("/jobs")
        async def create_job_endpoint(context: ProjectContext):
            """
            Explicitly create a job (alternative endpoint for job-based flow).
            
            Args:
                context: Project context containing stack and files
                
            Returns:
                JobResponse with job_id
            """
            # Check template first
            template = get_template(context.stack)
            if template:
                # Return files directly, not a job
                return template
            
            # Create job
            try:
                context_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                job_id = create_job(context_dict)
                return JobResponse(job_id=job_id, status="pending")
            except Exception as e:
                logger.error(f"Failed to create job: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create job: {str(e)}"
                )

        @app.get("/job/{job_id}")
        async def get_job_status(job_id: str):
            """
            Get the status of a job.
            
            Args:
                job_id: Job ID
                
            Returns:
                JobStatus with current status and result if completed
            """
            job_data = get_job(job_id)
            if not job_data:
                raise HTTPException(status_code=404, detail="Job not found")
            
            result = None
            if job_data.get("result"):
                result = DevOpsFiles(**job_data["result"])
            
            return JobStatus(
                job_id=job_id,
                status=job_data["status"],
                result=result,
                error=job_data.get("error")
            )

        @app.post("/process/{job_id}")
        async def process_job(job_id: str):
            """
            Background job processor endpoint. 
            This can be called by Vercel cron jobs or manually.
            
            Args:
                job_id: Job ID to process
                
            Returns:
                Success message
            """
            job_data = get_job(job_id)
            if not job_data:
                raise HTTPException(status_code=404, detail="Job not found")
            
            if job_data["status"] != "pending":
                return {"message": f"Job already processed. Status: {job_data['status']}"}
            
            # Update status to processing
            update_job_status(job_id, "processing")
            
            try:
                # Get context from job
                context_dict = job_data["context"]
                context = ProjectContext(**context_dict)
                
                # Call LLM asynchronously with timeout (120 seconds default, but can be adjusted)
                # This prevents blocking the request and exceeding platform timeouts
                llm_timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120.0"))
                result = await get_llm_response(context, timeout=llm_timeout)
                
                # Store result
                update_job_status(
                    job_id,
                    "completed",
                    result=result.dict()
                )
                
                logger.info(f"Successfully processed job {job_id}")
                return {"message": "Job processed successfully", "job_id": job_id}
                
            except HTTPException:
                # Re-raise HTTPExceptions (including timeout errors) to preserve status codes
                raise
            except Exception as e:
                logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
                error_message = str(e)
                update_job_status(
                    job_id,
                    "failed",
                    error=error_message
                )
                raise HTTPException(status_code=500, detail=f"Job processing failed: {error_message}")

        @app.get("/health")
        def health_check():
            """Simple health check endpoint."""
            return {
                "status": "ok",
                "service": "spectra-api",
                "version": "0.2.0"
            }

        @app.get("/")
        def root():
            """Root endpoint with API information."""
            return {
                "service": "Spectra API",
                "version": "0.2.0",
                "endpoints": {
                    "POST /": "Generate DevOps files (checks templates, creates job if needed)",
                    "POST /jobs": "Create a job explicitly",
                    "GET /job/{job_id}": "Get job status",
                    "POST /process/{job_id}": "Process a job (background worker)",
                    "GET /health": "Health check"
                }
            }

        # Export handler for Vercel
        # Vercel Python runtime supports ASGI apps directly, but we also support Mangum for AWS Lambda compatibility
        try:
            from mangum import Mangum
            mangum_handler = Mangum(app, lifespan="off")
            _mangum_available = True
            logger.info("Mangum handler initialized successfully")
        except Exception as e:
            logger.warning(f"Mangum not available: {e}. Vercel will use ASGI app directly.")
            _mangum_available = False
            mangum_handler = None
except Exception as e:
    # If anything fails during FastAPI initialization, log it but don't crash
    logger.error(f"Error initializing FastAPI app: {e}", exc_info=True)
    app = None
    _mangum_available = False
    mangum_handler = None

if FALLBACK_MODE:
    # In fallback mode, Mangum is not available
    _mangum_available = False
    mangum_handler = None

# For Vercel Python runtime, we can export the app directly as ASGI
# But we also provide a handler function for compatibility
# Vercel will use the app directly if available, otherwise fall back to handler

# Handler function for Vercel (used when ASGI app is not directly supported)
def handler(event=None, context=None):
    """
    Vercel serverless function handler.
    
    Handles both AWS Lambda format (event, context) and Vercel format.
    Vercel passes event as a dict with request information.
    """
    try:
        # Normal mode - use Mangum if available (preferred for FastAPI)
        if not FALLBACK_MODE and _mangum_available and mangum_handler:
            try:
                # Mangum expects AWS Lambda format, but Vercel uses a different format
                # Convert Vercel event to Lambda format if needed
                result = mangum_handler(event, context)
                # Ensure proper response format for Vercel
                if isinstance(result, dict) and "statusCode" in result:
                    return result
                # If Mangum returns a different format, wrap it
                return {
                    "statusCode": 200,
                    "headers": {"content-type": "application/json"},
                    "body": json.dumps(result) if not isinstance(result, str) else result
                }
            except Exception as e:
                logger.error(f"Mangum handler error: {e}", exc_info=True)
                # Fall through to fallback handler
                pass
        
        # Fallback handler when Mangum is not available or failed
        if FALLBACK_MODE:
            # Minimal fallback handler when FastAPI is not available
            path = (event or {}).get('rawPath') or (event or {}).get('path') or (event or {}).get('url', {}).get('path', '/')
            if path in ('/', '/health'):
                body = json.dumps({
                    "status": "ok",
                    "service": "spectra-api",
                    "version": "0.2.0"
                }) if path == '/health' else json.dumps({"service": "Spectra API", "version": "0.2.0"})
                return {
                    "statusCode": 200,
                    "headers": {"content-type": "application/json"},
                    "body": body
                }
            return {
                "statusCode": 503,
                "headers": {"content-type": "application/json"},
                "body": json.dumps({"error": "Service initializing - FastAPI not available"})
            }
        
        # Fallback when FastAPI is available but Mangum failed
        # This should not happen in normal operation, but handle gracefully
        path = (event or {}).get('rawPath') or (event or {}).get('path') or (event or {}).get('url', {}).get('path', '/')
        method = (event or {}).get('requestContext', {}).get('http', {}).get('method') or (event or {}).get('httpMethod') or (event or {}).get('method', 'GET')
        
        if method == 'GET' and path in ('/health', '/'):
            body = json.dumps({
                "status": "ok",
                "service": "spectra-api",
                "version": "0.2.0"
            }) if path == '/health' else json.dumps({
                "service": "Spectra API",
                "version": "0.2.0",
                "endpoints": {
                    "POST /": "Generate DevOps files (checks templates, creates job if needed)",
                    "POST /jobs": "Create a job explicitly",
                    "GET /job/{job_id}": "Get job status",
                    "POST /process/{job_id}": "Process a job (background worker)",
                    "GET /health": "Health check"
                }
            })
            return {
                "statusCode": 200,
                "headers": {"content-type": "application/json"},
                "body": body
            }
        
        return {
            "statusCode": 503,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": "Service initializing - Mangum handler unavailable"})
        }
        
    except Exception as ex:
        logger.error(f"Fatal error in handler: {ex}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({
                "error": "Internal server error",
                "message": str(ex) if os.getenv("DEBUG", "false").lower() == "true" else "An error occurred"
            })
        }

# Ensure app is properly exported for Vercel
# Vercel Python runtime will use the 'app' variable if it's an ASGI application
# If app is None, Vercel will use the handler function instead
if app is None and not FALLBACK_MODE:
    # If app wasn't created but we're not in fallback mode, try to create a minimal one
    try:
        from fastapi import FastAPI
        app = FastAPI(title="Spectra API", version="0.2.0")
        logger.warning("Created minimal FastAPI app as fallback")
    except Exception as e:
        logger.error(f"Failed to create minimal app: {e}")
        app = None

# Final safety check: ensure handler function is always defined and callable
# This prevents module import failures
if not callable(handler):
    def handler(event=None, context=None):
        """Emergency fallback handler if main handler failed to initialize."""
        try:
            return {
                "statusCode": 500,
                "headers": {"content-type": "application/json"},
                "body": json.dumps({
                    "error": "Service initialization failed",
                    "message": "The serverless function failed to initialize properly. Please check the logs."
                })
            }
        except Exception:
            # Last resort: return minimal response
            return {
                "statusCode": 500,
                "body": '{"error":"Service unavailable"}'
            }
