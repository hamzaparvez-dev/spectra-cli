"""FastAPI serverless function for Spectra API brain with async job queue."""

# CRITICAL: This module must NEVER crash during import
# Vercel requires a valid 'app' variable to exist, or Python exits with status 1

import sys
import os
import json
import traceback

# Initialize app to None - will be set below
app = None

# Create minimal ASGI app function - defined early to avoid dependency issues
def _create_minimal_asgi_app():
    """Create minimal ASGI app that always works."""
    class MinimalASGIApp:
        def __init__(self):
            self.title = "Spectra API"
            self.version = "0.2.0"
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                body = json.dumps({"error": "Service unavailable", "message": "Initialization failed"}).encode()
                await send({"type": "http.response.start", "status": 503, "headers": [[b"content-type", b"application/json"]]})
                await send({"type": "http.response.body", "body": body})
    return MinimalASGIApp()

# Wrap EVERYTHING in try-except to prevent any crash
try:
    # Import standard library first
    import logging
    import asyncio
    from typing import Optional, Dict, Any
    
    # Initialize logger with fallback
    logger = None
    try:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s', force=True)
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
    except Exception as log_err:
        # Fallback logger using print
        class SimpleLogger:
            def info(self, msg): print(f"INFO: {msg}", file=sys.stderr, flush=True)
            def warning(self, msg): print(f"WARNING: {msg}", file=sys.stderr, flush=True)
            def error(self, msg): print(f"ERROR: {msg}", file=sys.stderr, flush=True)
            def setLevel(self, level): pass
        logger = SimpleLogger()
        logger.error(f"Logging init failed: {log_err}")

    # Add api directory to path
    try:
        api_dir = os.path.dirname(os.path.abspath(__file__))
        if api_dir and api_dir not in sys.path:
            sys.path.insert(0, api_dir)
    except Exception:
        try:
            for p in ['/var/task/api', '/var/task', os.getcwd()]:
                if os.path.exists(p) and p not in sys.path:
                    sys.path.insert(0, p)
        except Exception:
            pass

    # Import pydantic with fallback
    BaseModel = None
    try:
        from pydantic import BaseModel
    except ImportError:
        class BaseModel:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
            def dict(self):
                return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    # Import FastAPI
    FALLBACK_MODE = False
    FastAPI = None
    HTTPException = None
    CORSMiddleware = None
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
    except Exception as e:
        FALLBACK_MODE = True
        logger.error(f"FastAPI import failed: {e}")

    # Import local modules - CRITICAL: wrap each import separately
    ProjectContext = None
    DevOpsFiles = None
    JobResponse = None
    JobStatus = None
    get_template = None
    create_job = None
    get_job = None
    update_job_status = None
    IMPORTS_OK = False

    # Try importing models first
    try:
        from models import ProjectContext, DevOpsFiles, JobResponse, JobStatus
        IMPORTS_OK = True
        logger.info("Imported models successfully")
    except Exception as e:
        logger.error(f"Failed to import models: {e}")
        # Create fallback models
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

    # Try importing templates
    try:
        from templates import get_template
        logger.info("Imported templates successfully")
    except Exception as e:
        logger.error(f"Failed to import templates: {e}")
        def get_template(stack):
            return None

    # Try importing job_queue
    try:
        from job_queue import create_job, get_job, update_job_status
        logger.info("Imported job_queue successfully")
    except Exception as e:
        logger.error(f"Failed to import job_queue: {e}")
        def create_job(context):
            raise RuntimeError("Job creation unavailable")
        def get_job(job_id):
            return None
        def update_job_status(job_id, status, result=None, error=None):
            pass

    # Initialize app
    _mangum_available = False
    mangum_handler = None

    if not FALLBACK_MODE and FastAPI:
        try:
            # Create FastAPI app
            app = FastAPI(title="Spectra API", description="AI-powered DevOps file generator", version="0.2.0")

            # CORS configuration
            def parse_cors_origins():
                origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
                if not origins_str:
                    return [], []
                regular = []
                regex = []
                for o in origins_str.split(","):
                    o = o.strip()
                    if not o:
                        continue
                    if o == "*":
                        regular.append(o)
                    elif o.startswith(("http://", "https://")):
                        regular.append(o.rstrip("/"))
                    elif o.startswith("regex:"):
                        p = o[6:].strip()
                        if p:
                            regex.append(p)
                return regular, regex

            regular_origins, regex_origins = parse_cors_origins()
            cors_creds = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
            if cors_creds and (not regular_origins and not regex_origins or "*" in regular_origins):
                cors_creds = False
            if not regular_origins and not regex_origins and not cors_creds:
                regular_origins = ["*"]

            cors_config = {"allow_credentials": cors_creds, "allow_methods": ["*"], "allow_headers": ["*"]}
            if regular_origins:
                cors_config["allow_origins"] = regular_origins
            if regex_origins:
                cors_config["allow_origin_regex"] = "|".join(f"({p})" for p in regex_origins)

            app.add_middleware(CORSMiddleware, **cors_config)

            # Gemini client function
            def get_gemini_client():
                import google.genai as genai
                key = os.getenv("OPENAI_API_KEY")
                if not key:
                    raise ValueError("OPENAI_API_KEY not set")
                genai.configure(api_key=key)
                return genai.GenerativeModel('gemini-2.5-flash')

            # LLM response function
            async def get_llm_response(context: ProjectContext, timeout: float = 120.0) -> DevOpsFiles:
                try:
                    model = get_gemini_client()
                except ValueError:
                    raise HTTPException(status_code=500, detail="API key not configured")

                files_str = "\n".join([f"--- {f} ---\n{c}\n" for f, c in context.files.items()])
                prompt = f"""You are 'Spectra', an expert DevOps engineer. Generate production-ready DevOps files.

Project: {context.stack}
Files:
{files_str}

Return ONLY valid JSON with keys: dockerfile, compose, github_action."""

                def _call_sync():
                    try:
                        resp = model.generate_content(prompt, generation_config={"temperature": 0.1, "max_output_tokens": 3000})
                        if not resp or not hasattr(resp, 'text'):
                            raise ValueError("Invalid Gemini response")
                        return resp.text.strip()
                    except Exception as e:
                        logger.error(f"Gemini error: {e}")
                        raise

                try:
                    if hasattr(asyncio, 'to_thread'):
                        text = await asyncio.wait_for(asyncio.to_thread(_call_sync), timeout=timeout)
                    else:
                        loop = asyncio.get_event_loop()
                        text = await asyncio.wait_for(loop.run_in_executor(None, _call_sync), timeout=timeout)
                    
                    if text.startswith("```json"):
                        text = text.replace("```json", "").replace("```", "").strip()
                    elif text.startswith("```"):
                        text = text.replace("```", "").strip()
                    
                    data = json.loads(text)
                    return DevOpsFiles(dockerfile=data.get('dockerfile'), compose=data.get('compose'), github_action=data.get('github_action'))
                except asyncio.TimeoutError:
                    raise HTTPException(status_code=504, detail=f"Timeout after {timeout}s")
                except json.JSONDecodeError as e:
                    raise HTTPException(status_code=500, detail=f"JSON parse error: {e}")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

            # Routes
            @app.post("/")
            async def generate_devops(context: ProjectContext):
                try:
                    template = get_template(context.stack)
                    if template:
                        return template.dict()
                    ctx_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(ctx_dict)
                    return {"job_id": job_id, "status": "pending"}
                except Exception as e:
                    logger.error(f"generate_devops error: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            @app.post("/jobs")
            async def create_job_endpoint(context: ProjectContext):
                try:
                    template = get_template(context.stack)
                    if template:
                        return {"status": "completed", "result": template.dict()}
                    ctx_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(ctx_dict)
                    return JobResponse(job_id=job_id, status="pending")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))

            @app.get("/job/{job_id}")
            async def get_job_status(job_id: str):
                data = get_job(job_id)
                if not data:
                    raise HTTPException(status_code=404, detail="Job not found")
                result = DevOpsFiles(**data["result"]) if data.get("result") else None
                return JobStatus(job_id=job_id, status=data["status"], result=result, error=data.get("error"))

            @app.post("/process/{job_id}")
            async def process_job(job_id: str):
                data = get_job(job_id)
                if not data:
                    raise HTTPException(status_code=404, detail="Job not found")
                if data["status"] != "pending":
                    return {"message": f"Job {data['status']}"}
                update_job_status(job_id, "processing")
                try:
                    ctx = ProjectContext(**data["context"])
                    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120.0"))
                    result = await get_llm_response(ctx, timeout=timeout)
                    update_job_status(job_id, "completed", result=result.dict())
                    return {"message": "Job processed", "job_id": job_id}
                except HTTPException:
                    raise
                except Exception as e:
                    update_job_status(job_id, "failed", error=str(e))
                    raise HTTPException(status_code=500, detail=str(e))

            @app.get("/health")
            def health():
                return {"status": "ok", "service": "spectra-api", "version": "0.2.0"}

            @app.get("/")
            def root():
                return {"service": "Spectra API", "version": "0.2.0", "endpoints": ["POST /", "POST /jobs", "GET /job/{id}", "POST /process/{id}", "GET /health"]}

            # Try Mangum
            try:
                from mangum import Mangum
                mangum_handler = Mangum(app, lifespan="off")
                _mangum_available = True
            except Exception:
                _mangum_available = False

        except Exception as e:
            logger.error(f"FastAPI app creation failed: {e}")
            logger.error(traceback.format_exc())
            app = None

    # Fallback app creation
    if app is None:
        try:
            if not FALLBACK_MODE and FastAPI:
                app = FastAPI(title="Spectra API", version="0.2.0")
                @app.get("/health")
                def h(): return {"status": "ok", "mode": "minimal"}
                @app.get("/")
                def r(): return {"service": "Spectra API", "status": "minimal"}
            elif FALLBACK_MODE:
                try:
                    from fastapi import FastAPI
                    app = FastAPI(title="Spectra API", version="0.2.0")
                    @app.get("/health")
                    def h(): return {"status": "ok", "mode": "fallback"}
                except Exception:
                    app = _create_minimal_asgi_app()
            else:
                app = _create_minimal_asgi_app()
        except Exception as e:
            logger.error(f"Fallback app creation failed: {e}")
            app = _create_minimal_asgi_app()

    # Handler function
    def handler(event=None, context=None):
        try:
            if not FALLBACK_MODE and _mangum_available and mangum_handler:
                try:
                    r = mangum_handler(event, context)
                    if isinstance(r, dict) and "statusCode" in r:
                        return r
                    return {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(r) if not isinstance(r, str) else r}
                except Exception:
                    pass
            return {"statusCode": 503, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Unavailable"})}
        except Exception:
            return {"statusCode": 500, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Error"})}

except BaseException as e:
    # Catch EVERYTHING including SystemExit, KeyboardInterrupt
    print(f"FATAL MODULE ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    print(traceback.format_exc(), file=sys.stderr, flush=True)
    app = _create_minimal_asgi_app()
    
    def handler(event=None, context=None):
        return {"statusCode": 500, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Fatal error"})}

# Final safety check - app MUST exist
if app is None:
    app = _create_minimal_asgi_app()
