"""FastAPI serverless function for Spectra API brain with async job queue."""

import sys
import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any

# Safe logging initialization - use print as fallback
_logger_initialized = False
try:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    _logger_initialized = True
except Exception as e:
    # If logging fails completely, create a minimal logger that uses print
    class PrintLogger:
        def info(self, msg): print(f"INFO: {msg}", file=sys.stderr)
        def warning(self, msg): print(f"WARNING: {msg}", file=sys.stderr)
        def error(self, msg): print(f"ERROR: {msg}", file=sys.stderr)
        def setLevel(self, level): pass
    logger = PrintLogger()
    logger.error(f"Logging initialization failed: {e}")

# Ensure api directory is in Python path for direct imports (Vercel compatibility)
try:
    api_dir = os.path.dirname(os.path.abspath(__file__))
    if api_dir and api_dir not in sys.path:
        sys.path.insert(0, api_dir)
except (NameError, AttributeError):
    try:
        if 'api' not in str(sys.path):
            for path in [os.getcwd(), '/var/task/api', '/var/task']:
                if os.path.exists(path) and path not in sys.path:
                    sys.path.insert(0, path)
    except Exception:
        pass

# Import BaseModel separately - needed even in fallback mode
try:
    from pydantic import BaseModel
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

# Try to import FastAPI and dependencies
FALLBACK_MODE = False
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
except Exception as e:
    FALLBACK_MODE = True
    logger.error(f"FastAPI import failed: {e}")

# Direct imports - all files are in the same directory in Vercel serverless
IMPORTS_OK = False
ProjectContext = None
DevOpsFiles = None
JobResponse = None
JobStatus = None
get_template = None
create_job = None
get_job = None
update_job_status = None

try:
    from models import ProjectContext, DevOpsFiles, JobResponse, JobStatus
    from templates import get_template
    from job_queue import create_job, get_job, update_job_status
    IMPORTS_OK = True
    logger.info("Successfully imported all required modules")
except ImportError as e:
    IMPORTS_OK = False
    logger.error(f"Failed to import modules: {e}")
    # Define minimal fallbacks
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
        raise ImportError(f"get_template unavailable: required modules not imported")
    def create_job(context):
        raise ImportError(f"create_job unavailable: required modules not imported")
    def get_job(job_id):
        raise ImportError(f"get_job unavailable: required modules not imported")
    def update_job_status(job_id, status, result=None, error=None):
        raise ImportError(f"update_job_status unavailable: required modules not imported")
except Exception as e:
    IMPORTS_OK = False
    logger.error(f"Unexpected error importing modules: {e}")
    # Same fallbacks as above
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
        raise ImportError(f"get_template unavailable")
    def create_job(context):
        raise ImportError(f"create_job unavailable")
    def get_job(job_id):
        raise ImportError(f"get_job unavailable")
    def update_job_status(job_id, status, result=None, error=None):
        raise ImportError(f"update_job_status unavailable")

# Initialize app variable - CRITICAL: must never be None
app = None
_mangum_available = False
mangum_handler = None

# Initialize FastAPI app - wrap everything in try-except to prevent crashes
try:
    if not FALLBACK_MODE:
        # Initialize Gemini client (defer heavy import until needed)
        def get_gemini_client():
            """Get or configure Gemini client with API key validation."""
            import google.genai as genai
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable is not set")
            genai.configure(api_key=api_key)
            return genai.GenerativeModel('gemini-2.5-flash')

        def parse_and_validate_cors_origins():
            """Parse and validate CORS allowed origins from environment variable."""
            origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
            if not origins_str:
                return [], []
            regular_origins = []
            regex_origins = []
            for origin in origins_str.split(","):
                origin = origin.strip()
                if not origin:
                    continue
                if origin == "*":
                    logger.warning("CORS origin '*' detected. This will be ignored if allow_credentials=True.")
                    regular_origins.append(origin)
                elif origin.startswith(("http://", "https://")):
                    regular_origins.append(origin.rstrip("/"))
                elif origin.startswith("regex:"):
                    regex_pattern = origin[6:].strip()
                    if regex_pattern:
                        regex_origins.append(regex_pattern)
            return regular_origins, regex_origins

        app = FastAPI(
            title="Spectra API",
            description="AI-powered DevOps file generator with template caching and async processing",
            version="0.2.0"
        )

        # Parse and validate CORS origins
        regular_origins, regex_origins = parse_and_validate_cors_origins()
        cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
        has_wildcard = "*" in regular_origins
        has_any_origins = len(regular_origins) > 0 or len(regex_origins) > 0
        
        if cors_allow_credentials:
            if not has_any_origins or has_wildcard:
                logger.warning("CORS_ALLOWED_ORIGINS not configured or contains '*', but CORS_ALLOW_CREDENTIALS=True. Setting allow_credentials=False.")
                cors_allow_credentials = False
        
        if not has_any_origins and not cors_allow_credentials:
            regular_origins = ["*"]
            logger.info("No CORS origins configured. Using allow_origins=['*'] with allow_credentials=False.")
        elif not has_any_origins:
            logger.warning("CORS_ALLOWED_ORIGINS not configured but credentials enabled. No origins will be allowed.")
            regular_origins = []
        
        cors_config = {
            "allow_credentials": cors_allow_credentials,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
        if regular_origins:
            cors_config["allow_origins"] = regular_origins
        if regex_origins:
            cors_config["allow_origin_regex"] = "|".join(f"({pattern})" for pattern in regex_origins)
        
        app.add_middleware(CORSMiddleware, **cors_config)

        # Define get_llm_response function
        async def get_llm_response(context: ProjectContext, timeout: float = 120.0) -> DevOpsFiles:
            """Calls the Gemini API to generate the DevOps files asynchronously with timeout handling."""
            try:
                model = get_gemini_client()
            except ValueError:
                logger.error("OPENAI_API_KEY is not set!")
                raise HTTPException(status_code=500, detail="API key is not configured on the server.")

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
            
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            
            def _call_gemini_sync():
                """Synchronous wrapper for Gemini API call to run in thread pool."""
                try:
                    logger.info(f"Calling Gemini API for stack: {context.stack}")
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
                logger.info(f"Starting async LLM call for stack: {context.stack} with timeout: {timeout}s")
                if hasattr(asyncio, 'to_thread'):
                    response_json_str = await asyncio.wait_for(
                        asyncio.to_thread(_call_gemini_sync),
                        timeout=timeout
                    )
                else:
                    loop = asyncio.get_event_loop()
                    response_json_str = await asyncio.wait_for(
                        loop.run_in_executor(None, _call_gemini_sync),
                        timeout=timeout
                    )
                logger.info("AI Response received successfully")
                
                if response_json_str.startswith("```json"):
                    response_json_str = response_json_str.replace("```json", "").replace("```", "").strip()
                elif response_json_str.startswith("```"):
                    response_json_str = response_json_str.replace("```", "").strip()
                
                data = json.loads(response_json_str)
                return DevOpsFiles(
                    dockerfile=data.get('dockerfile'),
                    compose=data.get('compose'),
                    github_action=data.get('github_action')
                )
            except asyncio.TimeoutError:
                logger.error(f"LLM call timed out after {timeout} seconds")
                raise HTTPException(status_code=504, detail=f"LLM request timed out after {timeout} seconds.")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response from Gemini: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {e}")
            except Exception as e:
                logger.error(f"Error calling Gemini or parsing response: {e}")
                raise HTTPException(status_code=500, detail=f"AI model error: {str(e)}")

        # Route definitions
        @app.post("/")
        async def generate_devops(context: ProjectContext):
            """Main API endpoint. Receives project context and returns DevOps files."""
            logger.info("API request received")
            try:
                logger.info(f"Processing project with stack: {context.stack}")
                try:
                    template = get_template(context.stack)
                    if template:
                        logger.info(f"Returning cached template for stack: {context.stack}")
                        return template.dict()
                except Exception as template_error:
                    logger.warning(f"Error checking template cache: {template_error}. Continuing with job creation.")
                
                logger.info(f"No template found for stack: {context.stack}, creating async job")
                try:
                    context_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(context_dict)
                    return {"job_id": job_id, "status": "pending"}
                except Exception as job_error:
                    logger.error(f"Failed to create job: {job_error}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Failed to create processing job: {str(job_error)}")
            except HTTPException:
                raise
            except ValueError as e:
                logger.error(f"Validation error: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid request data: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in API: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

        @app.post("/jobs")
        async def create_job_endpoint(context: ProjectContext):
            """Explicitly create a job (alternative endpoint for job-based flow)."""
            template = get_template(context.stack)
            if template:
                return {"status": "completed", "result": template.dict()}
            try:
                context_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                job_id = create_job(context_dict)
                return JobResponse(job_id=job_id, status="pending")
            except Exception as e:
                logger.error(f"Failed to create job: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")

        @app.get("/job/{job_id}")
        async def get_job_status(job_id: str):
            """Get the status of a job."""
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
            """Background job processor endpoint."""
            job_data = get_job(job_id)
            if not job_data:
                raise HTTPException(status_code=404, detail="Job not found")
            if job_data["status"] != "pending":
                return {"message": f"Job already processed. Status: {job_data['status']}"}
            update_job_status(job_id, "processing")
            try:
                context_dict = job_data["context"]
                context = ProjectContext(**context_dict)
                llm_timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120.0"))
                result = await get_llm_response(context, timeout=llm_timeout)
                update_job_status(job_id, "completed", result=result.dict())
                logger.info(f"Successfully processed job {job_id}")
                return {"message": "Job processed successfully", "job_id": job_id}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
                error_message = str(e)
                update_job_status(job_id, "failed", error=error_message)
                raise HTTPException(status_code=500, detail=f"Job processing failed: {error_message}")

        @app.get("/health")
        def health_check():
            """Simple health check endpoint."""
            return {"status": "ok", "service": "spectra-api", "version": "0.2.0"}

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

        # Try to initialize Mangum handler
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
    logger.error(f"Error initializing FastAPI app: {e}", exc_info=True)
    app = None
    _mangum_available = False
    mangum_handler = None

if FALLBACK_MODE:
    _mangum_available = False
    mangum_handler = None

# CRITICAL: Ensure app is ALWAYS a valid FastAPI/ASGI instance for Vercel
# Vercel Python runtime requires the 'app' variable to be a valid ASGI application
if app is None:
    try:
        if not FALLBACK_MODE:
            from fastapi import FastAPI
            app = FastAPI(title="Spectra API", version="0.2.0")
            logger.warning("Created minimal FastAPI app as fallback")
            @app.get("/health")
            def health_check():
                return {"status": "ok", "service": "spectra-api", "version": "0.2.0", "mode": "minimal"}
            @app.get("/")
            def root():
                return {"service": "Spectra API", "version": "0.2.0", "status": "minimal_mode", "error": "Full API initialization failed"}
        else:
            try:
                from fastapi import FastAPI
                app = FastAPI(title="Spectra API", version="0.2.0")
                logger.warning("Created minimal FastAPI app in fallback mode")
                @app.get("/health")
                def health_check():
                    return {"status": "ok", "service": "spectra-api", "version": "0.2.0", "mode": "fallback"}
                @app.get("/")
                def root():
                    return {"service": "Spectra API", "version": "0.2.0", "status": "fallback_mode"}
            except Exception:
                # Last resort: create minimal ASGI app
                class MinimalASGIApp:
                    def __init__(self):
                        self.title = "Spectra API"
                        self.version = "0.2.0"
                    async def __call__(self, scope, receive, send):
                        if scope["type"] == "http":
                            response_body = json.dumps({"error": "Service unavailable", "message": "FastAPI initialization failed"}).encode()
                            await send({"type": "http.response.start", "status": 503, "headers": [[b"content-type", b"application/json"]]})
                            await send({"type": "http.response.body", "body": response_body})
                app = MinimalASGIApp()
                logger.error("Created minimal ASGI app wrapper as absolute last resort")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to create any FastAPI app: {e}", exc_info=True)
        # Absolute last resort: minimal ASGI app
        class MinimalASGIApp:
            def __init__(self):
                self.title = "Spectra API"
                self.version = "0.2.0"
            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    response_body = json.dumps({"error": "Service unavailable", "message": "Critical initialization failure"}).encode()
                    await send({"type": "http.response.start", "status": 503, "headers": [[b"content-type", b"application/json"]]})
                    await send({"type": "http.response.body", "body": response_body})
        app = MinimalASGIApp()
        logger.error("Created minimal ASGI app wrapper as absolute last resort")

# Handler function for Vercel (compatibility layer)
def handler(event=None, context=None):
    """Vercel serverless function handler."""
    try:
        if not FALLBACK_MODE and _mangum_available and mangum_handler:
            try:
                result = mangum_handler(event, context)
                if isinstance(result, dict) and "statusCode" in result:
                    return result
                return {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(result) if not isinstance(result, str) else result}
            except Exception as e:
                logger.error(f"Mangum handler error: {e}", exc_info=True)
        
        if FALLBACK_MODE:
            path = (event or {}).get('rawPath') or (event or {}).get('path') or (event or {}).get('url', {}).get('path', '/')
            if path in ('/', '/health'):
                body = json.dumps({"status": "ok", "service": "spectra-api", "version": "0.2.0"}) if path == '/health' else json.dumps({"service": "Spectra API", "version": "0.2.0"})
                return {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": body}
            return {"statusCode": 503, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Service initializing - FastAPI not available"})}
        
        return {"statusCode": 503, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Service initializing - Mangum handler unavailable"})}
    except Exception as ex:
        logger.error(f"Fatal error in handler: {ex}", exc_info=True)
        return {"statusCode": 500, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Internal server error", "message": str(ex) if os.getenv("DEBUG", "false").lower() == "true" else "An error occurred"})}
