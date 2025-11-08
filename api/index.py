"""FastAPI serverless function for Spectra API brain with async job queue."""

# CRITICAL: Wrap entire module in try-except to prevent Python crashes
# This ensures Vercel always gets a valid app, even if everything fails

import sys
import os
import json
import traceback

# Global app variable - must be defined before any code that might fail
app = None

# Top-level exception handler to catch ALL errors during module initialization
def _create_minimal_app():
    """Create a minimal ASGI app as absolute fallback."""
    class MinimalASGIApp:
        def __init__(self):
            self.title = "Spectra API"
            self.version = "0.2.0"
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                response_body = json.dumps({
                    "error": "Service unavailable",
                    "message": "Module initialization failed - check logs"
                }).encode()
                await send({
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [[b"content-type", b"application/json"]]
                })
                await send({
                    "type": "http.response.body",
                    "body": response_body
                })
    return MinimalASGIApp()

try:
    import logging
    import asyncio
    from typing import Optional, Dict, Any

    # Safe logging initialization
    try:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
    except Exception:
        class PrintLogger:
            def info(self, msg): print(f"INFO: {msg}", file=sys.stderr, flush=True)
            def warning(self, msg): print(f"WARNING: {msg}", file=sys.stderr, flush=True)
            def error(self, msg): print(f"ERROR: {msg}", file=sys.stderr, flush=True)
            def setLevel(self, level): pass
        logger = PrintLogger()

    # Ensure api directory is in Python path
    try:
        api_dir = os.path.dirname(os.path.abspath(__file__))
        if api_dir and api_dir not in sys.path:
            sys.path.insert(0, api_dir)
    except (NameError, AttributeError):
        try:
            for path in [os.getcwd(), '/var/task/api', '/var/task']:
                if os.path.exists(path) and path not in sys.path:
                    sys.path.insert(0, path)
        except Exception:
            pass

    # Import BaseModel
    try:
        from pydantic import BaseModel
    except ImportError:
        class BaseModel:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)
            def dict(self):
                return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    # Try to import FastAPI
    FALLBACK_MODE = False
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
    except Exception as e:
        FALLBACK_MODE = True
        logger.error(f"FastAPI import failed: {e}")

    # Import local modules with fallbacks
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
    except Exception as e:
        IMPORTS_OK = False
        logger.error(f"Failed to import modules: {e}")
        # Define fallbacks
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
            raise ImportError("get_template unavailable")
        def create_job(context):
            raise ImportError("create_job unavailable")
        def get_job(job_id):
            raise ImportError("get_job unavailable")
        def update_job_status(job_id, status, result=None, error=None):
            raise ImportError("update_job_status unavailable")

    # Initialize app
    _mangum_available = False
    mangum_handler = None

    try:
        if not FALLBACK_MODE:
            def get_gemini_client():
                import google.genai as genai
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY environment variable is not set")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel('gemini-2.5-flash')

            def parse_and_validate_cors_origins():
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
                description="AI-powered DevOps file generator",
                version="0.2.0"
            )

            regular_origins, regex_origins = parse_and_validate_cors_origins()
            cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
            has_wildcard = "*" in regular_origins
            has_any_origins = len(regular_origins) > 0 or len(regex_origins) > 0
            
            if cors_allow_credentials and (not has_any_origins or has_wildcard):
                cors_allow_credentials = False
            
            if not has_any_origins and not cors_allow_credentials:
                regular_origins = ["*"]
            
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

            async def get_llm_response(context: ProjectContext, timeout: float = 120.0) -> DevOpsFiles:
                try:
                    model = get_gemini_client()
                except ValueError:
                    raise HTTPException(status_code=500, detail="API key is not configured")

                file_context_str = "\n".join([
                    f"--- File: {filename} ---\n{content}\n"
                    for filename, content in context.files.items()
                ])
                
                system_prompt = (
                    "You are 'Spectra', an expert DevOps engineer. Generate production-ready DevOps files. "
                    "Return ONLY a valid JSON object with three keys: 'dockerfile', 'compose', and 'github_action'."
                )
                
                user_prompt = f"""A developer needs DevOps files for their project.

Project Context:
- Detected Stack: {context.stack}
- Relevant Files:
{file_context_str}

Instructions:
1. **dockerfile**: Create a multi-stage, production-optimized Dockerfile.
2. **compose**: Create a `docker-compose.yml` file for local development.
3. **github_action**: Create a GitHub Actions workflow file.

Return ONLY the valid JSON object with these exact keys: dockerfile, compose, github_action."""
                
                full_prompt = f"{system_prompt}\n\n{user_prompt}"
                
                def _call_gemini_sync():
                    try:
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
                            raise ValueError("Invalid response from Gemini API")
                        return response.text.strip()
                    except Exception as e:
                        logger.error(f"Gemini API call failed: {e}")
                        raise
                
                try:
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
                    raise HTTPException(status_code=504, detail=f"LLM request timed out after {timeout} seconds.")
                except json.JSONDecodeError as e:
                    raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {e}")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"AI model error: {str(e)}")

            @app.post("/")
            async def generate_devops(context: ProjectContext):
                try:
                    try:
                        template = get_template(context.stack)
                        if template:
                            return template.dict()
                    except Exception:
                        pass
                    context_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(context_dict)
                    return {"job_id": job_id, "status": "pending"}
                except Exception as e:
                    logger.error(f"Error in generate_devops: {e}")
                    raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

            @app.post("/jobs")
            async def create_job_endpoint(context: ProjectContext):
                try:
                    template = get_template(context.stack)
                    if template:
                        return {"status": "completed", "result": template.dict()}
                    context_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(context_dict)
                    return JobResponse(job_id=job_id, status="pending")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")

            @app.get("/job/{job_id}")
            async def get_job_status(job_id: str):
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
                    return {"message": "Job processed successfully", "job_id": job_id}
                except HTTPException:
                    raise
                except Exception as e:
                    update_job_status(job_id, "failed", error=str(e))
                    raise HTTPException(status_code=500, detail=f"Job processing failed: {str(e)}")

            @app.get("/health")
            def health_check():
                return {"status": "ok", "service": "spectra-api", "version": "0.2.0"}

            @app.get("/")
            def root():
                return {
                    "service": "Spectra API",
                    "version": "0.2.0",
                    "endpoints": {
                        "POST /": "Generate DevOps files",
                        "POST /jobs": "Create a job",
                        "GET /job/{job_id}": "Get job status",
                        "POST /process/{job_id}": "Process a job",
                        "GET /health": "Health check"
                    }
                }

            try:
                from mangum import Mangum
                mangum_handler = Mangum(app, lifespan="off")
                _mangum_available = True
            except Exception:
                _mangum_available = False
                mangum_handler = None

    except Exception as e:
        logger.error(f"Error initializing FastAPI app: {e}")
        logger.error(traceback.format_exc())
        app = None

    if FALLBACK_MODE:
        _mangum_available = False
        mangum_handler = None

    # Ensure app is always defined
    if app is None:
        try:
            if not FALLBACK_MODE:
                from fastapi import FastAPI
                app = FastAPI(title="Spectra API", version="0.2.0")
                @app.get("/health")
                def health_check():
                    return {"status": "ok", "service": "spectra-api", "version": "0.2.0", "mode": "minimal"}
                @app.get("/")
                def root():
                    return {"service": "Spectra API", "version": "0.2.0", "status": "minimal_mode"}
            else:
                try:
                    from fastapi import FastAPI
                    app = FastAPI(title="Spectra API", version="0.2.0")
                    @app.get("/health")
                    def health_check():
                        return {"status": "ok", "service": "spectra-api", "version": "0.2.0", "mode": "fallback"}
                    @app.get("/")
                    def root():
                        return {"service": "Spectra API", "version": "0.2.0", "status": "fallback_mode"}
                except Exception:
                    app = _create_minimal_app()
        except Exception as e:
            logger.error(f"CRITICAL: Failed to create app: {e}")
            logger.error(traceback.format_exc())
            app = _create_minimal_app()

    def handler(event=None, context=None):
        try:
            if not FALLBACK_MODE and _mangum_available and mangum_handler:
                try:
                    result = mangum_handler(event, context)
                    if isinstance(result, dict) and "statusCode" in result:
                        return result
                    return {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(result) if not isinstance(result, str) else result}
                except Exception:
                    pass
            return {"statusCode": 503, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Service unavailable"})}
        except Exception:
            return {"statusCode": 500, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Internal server error"})}

except Exception as e:
    # Absolute last resort - if even the try block fails, create minimal app
    print(f"CRITICAL MODULE ERROR: {e}", file=sys.stderr, flush=True)
    print(traceback.format_exc(), file=sys.stderr, flush=True)
    app = _create_minimal_app()
    
    def handler(event=None, context=None):
        return {
            "statusCode": 500,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": "Critical initialization failure"})
        }
