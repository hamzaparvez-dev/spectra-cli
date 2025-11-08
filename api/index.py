"""FastAPI serverless function for Spectra API brain with async job queue."""

# CRITICAL: This module must NEVER crash during import
# Vercel requires a valid 'app' variable to exist, or Python exits with status 1

import sys
import os
import json
import traceback
import importlib.util

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

# Safe import function that catches ALL errors
def _safe_import(module_name):
    """Safely import a module, returning None if import fails."""
    try:
        try:
            api_dir = os.path.dirname(os.path.abspath(__file__))
            if api_dir and api_dir not in sys.path:
                sys.path.insert(0, api_dir)
        except Exception:
            pass
        try:
            return __import__(module_name, fromlist=[''])
        except Exception:
            try:
                spec = importlib.util.find_spec(module_name)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return module
            except Exception:
                pass
        return None
    except BaseException:
        return None

# Wrap EVERYTHING in try-except to prevent any crash
try:
    import logging
    import asyncio
    import uuid
    from typing import Optional, Dict, Any

    # Initialize logger with fallback
    logger = None
    try:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s', force=True)
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
    except Exception:
        class SimpleLogger:
            def info(self, msg): print(f"INFO: {msg}", file=sys.stderr, flush=True)
            def warning(self, msg): print(f"WARNING: {msg}", file=sys.stderr, flush=True)
            def error(self, msg): print(f"ERROR: {msg}", file=sys.stderr, flush=True)
            def setLevel(self, level): pass
        logger = SimpleLogger()

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
    except Exception:
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

    # Import local modules - use safe import for each
    ProjectContext = None
    DevOpsFiles = None
    JobResponse = None
    JobStatus = None
    get_template = None
    create_job = None
    get_job = None
    update_job_status = None

    # Try importing models
    try:
        models_module = _safe_import('models')
        if models_module:
            ProjectContext = getattr(models_module, 'ProjectContext', None)
            DevOpsFiles = getattr(models_module, 'DevOpsFiles', None)
            JobResponse = getattr(models_module, 'JobResponse', None)
            JobStatus = getattr(models_module, 'JobStatus', None)
            if all([ProjectContext, DevOpsFiles, JobResponse, JobStatus]):
                logger.info("Imported models successfully")
            else:
                raise AttributeError("Missing model classes")
        else:
            raise ImportError("Could not load models module")
    except Exception as e:
        logger.error(f"Failed to import models: {e}")
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
    
    # Try importing templates - this is the risky one
    try:
        templates_module = _safe_import('templates')
        if templates_module:
            get_template = getattr(templates_module, 'get_template', None)
            if get_template:
                logger.info("Imported templates successfully")
            else:
                raise AttributeError("get_template not found")
        else:
            raise ImportError("Could not load templates module")
    except Exception as e:
        logger.error(f"Failed to import templates: {e}")
        logger.error(traceback.format_exc())
        def get_template(stack):
            return None

    # Try importing job_queue
    try:
        job_queue_module = _safe_import('job_queue')
        if job_queue_module:
            create_job = getattr(job_queue_module, 'create_job', None)
            get_job = getattr(job_queue_module, 'get_job', None)
            update_job_status = getattr(job_queue_module, 'update_job_status', None)
            if all([create_job, get_job, update_job_status]):
                logger.info("Imported job_queue successfully")
            else:
                raise AttributeError("Missing job_queue functions")
        else:
            raise ImportError("Could not load job_queue module")
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
            app = FastAPI(title="Spectra API", description="AI-powered DevOps file generator", version="0.2.0")

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

            def get_gemini_client():
                import google.genai as genai
                key = os.getenv("OPENAI_API_KEY")
                if not key:
                    raise ValueError("OPENAI_API_KEY not set")
                genai.configure(api_key=key)
                return genai.GenerativeModel('gemini-1.5-flash')

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

            @app.post("/")
            async def generate_devops(context: ProjectContext):
                try:
                    template = get_template(context.stack) if get_template else None
                    if template:
                        return template.dict() if hasattr(template, 'dict') else dict(template)
                    ctx_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(ctx_dict) if create_job else str(uuid.uuid4())
                    return {"job_id": job_id, "status": "pending"}
                except Exception as e:
                    logger.error(f"generate_devops error: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            @app.post("/jobs")
            async def create_job_endpoint(context: ProjectContext):
                try:
                    template = get_template(context.stack) if get_template else None
                    if template:
                        return {"status": "completed", "result": template.dict() if hasattr(template, 'dict') else dict(template)}
                    ctx_dict = context.dict() if hasattr(context, 'dict') else dict(context)
                    job_id = create_job(ctx_dict) if create_job else str(uuid.uuid4())
                    return JobResponse(job_id=job_id, status="pending")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))

            @app.get("/job/{job_id}")
            async def get_job_status(job_id: str):
                data = get_job(job_id) if get_job else None
                if not data:
                    raise HTTPException(status_code=404, detail="Job not found")
                result = None
                if data.get("result"):
                    try:
                        result = DevOpsFiles(**data["result"])
                    except Exception:
                        result = None
                return JobStatus(job_id=job_id, status=data.get("status", "unknown"), result=result, error=data.get("error"))

            @app.post("/process/{job_id}")
            async def process_job(job_id: str):
                data = get_job(job_id) if get_job else None
                if not data:
                    raise HTTPException(status_code=404, detail="Job not found")
                if data.get("status") != "pending":
                    return {"message": f"Job {data.get('status', 'unknown')}"}
                if update_job_status:
                    update_job_status(job_id, "processing")
                try:
                    ctx = ProjectContext(**data.get("context", {}))
                    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120.0"))
                    result = await get_llm_response(ctx, timeout=timeout)
                    if update_job_status:
                        update_job_status(job_id, "completed", result=result.dict() if hasattr(result, 'dict') else dict(result))
                    return {"message": "Job processed", "job_id": job_id}
                except HTTPException:
                    raise
                except Exception as e:
                    if update_job_status:
                        update_job_status(job_id, "failed", error=str(e))
                    raise HTTPException(status_code=500, detail=str(e))

            @app.get("/health")
            def health():
                return {"status": "ok", "service": "spectra-api", "version": "0.2.0"}

            @app.get("/")
            def root():
                """API information endpoint."""
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
                def r():
                    return {"service": "Spectra API", "version": "0.2.0", "status": "minimal"}
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
    print(f"FATAL MODULE ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    print(traceback.format_exc(), file=sys.stderr, flush=True)
    app = _create_minimal_asgi_app()
    
    def handler(event=None, context=None):
        return {"statusCode": 500, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": "Fatal error"})}

# Final safety check - app MUST exist
if app is None:
    app = _create_minimal_asgi_app()
