Building "Spectra CLI" MVP
🎯 Project Goal
To build a Python-based CLI (spectra) that scans a local project, sends its context to a serverless API "brain," and receives production-ready DevOps files (Dockerfile, docker-compose.yml, ci-cd.yml) in return.

🗂️ Project Structure
We will create a monorepo containing the CLI and the serverless API.

spectra-cli-mvp/
├── spectra/                  # The local CLI application
│   ├── __init__.py
│   ├── main.py             # Typer CLI logic
│   ├── scanner.py          # Project file scanning logic
│   └── client.py           # HTTP client to call the 'brain'
│
├── api/                      # The serverless 'brain' (for Vercel)
│   ├── index.py            # FastAPI app
│   └── requirements.txt    # API dependencies
│
├── .gitignore
├── requirements.txt          # CLI dependencies
└── README.md
Part 1: The spectra CLI Application
Step 1.1: Initialize Project Structure
Create the directory structure and placeholder files.

Prompt (for your terminal):

Bash

mkdir spectra-cli-mvp
cd spectra-cli-mvp
mkdir -p spectra api
touch spectra/__init__.py spectra/main.py spectra/scanner.py spectra/client.py
touch api/index.py api/requirements.txt
touch requirements.txt .gitignore README.md
Step 1.2: Set up CLI Dependencies
File: requirements.txt

Prompt (for requirements.txt):

# This file is for the local CLI
typer[all]
httpx
rich
File: .gitignore

Prompt (for .gitignore):

# Python
__pycache__/
*.pyc
.env
.venv/
build/
dist/
*.egg-info/

# Vercel
.vercel/
Step 1.3: Build the Project Scanner
This module finds key files and determines the project's stack.

File: spectra/scanner.py

Prompt (for spectra/scanner.py):

Python

import os
import json
from rich import print

MAX_FILE_SIZE_BYTES = 10000 # 10KB limit for context
RELEVANT_FILES = [
    'package.json', 'requirements.txt', 'pom.xml', 'go.mod',
    'docker-compose.yml', 'Dockerfile', 'main.py', 'app.py', 'server.js', 'index.js'
]

def scan_project(path: str) -> str:
    """
    Scans the project directory, identifies the stack, and gathers context
    from relevant files. Returns a JSON string of the context.
    """
    print(f":mag: [bold cyan]Scanning project at {path}...[/bold cyan]")
    
    context = {
        "stack": "unknown",
        "files": {}
    }
    
    found_files = []

    for root, _, files in os.walk(path):
        # Ignore hidden directories
        if any(part.startswith('.') for part in root.split(os.sep)):
            continue
            
        for file in files:
            if file in RELEVANT_FILES:
                file_path = os.path.join(root, file)
                
                # Check file size
                if os.path.getsize(file_path) > MAX_FILE_SIZE_BYTES:
                    print(f":warning: Skipping {file_path}, file is too large.")
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    relative_path = os.path.relpath(file_path, path)
                    context["files"][relative_path] = content
                    found_files.append(relative_path)
                    
                    # Basic stack detection
                    if file == 'package.json':
                        context['stack'] = 'nodejs'
                    elif file == 'requirements.txt':
                        context['stack'] = 'python'
                    elif file == 'pom.xml':
                        context['stack'] = 'java_maven'
                    elif file == 'go.mod':
                        context['stack'] = 'golang'

                except Exception as e:
                    print(f":x: Error reading {file_path}: {e}")

    if not found_files:
        print(":warning: No relevant project files found.")
        return None

    print(f":white_check_mark: [bold green]Scan complete.[/bold green] Found stack: [bold]{context['stack']}[/bold]")
    return json.dumps(context)
Step 1.4: Build the API Client
This module calls our serverless "brain."

File: spectra/client.py

Prompt (for spectra/client.py):

Python

import httpx
import os
from rich.panel import Panel
from rich import print

# The 'brain' API URL. We'll set this in our environment.
# For local testing: http://127.0.0.1:8000/
# For production: (Vercel URL)
API_URL = os.getenv("SPECTRA_API_URL", "http://127.0.0.1:8000/") 

async def get_deployment_files(project_context: str) -> dict:
    """
    Calls the serverless 'brain' API with the project context
    and returns the generated DevOps files.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(API_URL, content=project_context, headers={"Content-Type": "application/json"})
            
            response.raise_for_status() # Raises exception for 4xx/5xx
            
            return response.json()
            
    except httpx.HTTPStatusError as e:
        print(Panel(f"[bold red]API Error:[/bold red] {e.response.status_code} - {e.response.text}", title="HTTP Error", border_style="red"))
        return None
    except httpx.RequestError as e:
        print(Panel(f"[bold red]Network Error:[/bold red] Failed to connect to {e.request.url}. Is the API running?", title="Connection Error", border_style="red"))
        return None
    except Exception as e:
        print(Panel(f"[bold red]An unexpected error occurred:[/bold red] {e}", title="Error", border_style="red"))
        return None
Step 1.5: Build the Main CLI Logic
This ties the scanner and client together into a user-facing command.

File: spectra/main.py

Prompt (for spectra/main.py):

Python

import typer
import asyncio
from rich import print
from rich.spinner import Spinner
from rich.panel import Panel
import os

from .scanner import scan_project
from .client import get_deployment_files

app = typer.Typer()

def write_files(files: dict):
    """Writes the generated files to the disk."""
    total_files = len(files)
    written_count = 0
    
    print("\n:floppy_disk: [bold green]Writing generated files...[/bold green]")
    
    for filename, content in files.items():
        if not content:
            print(f":warning: No content generated for {filename}, skipping.")
            total_files -= 1
            continue
        
        # Special case for GitHub Actions
        if filename.startswith('.github'):
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  :page_facing_up: Created {filename}")
            written_count += 1
        except Exception as e:
            print(f"  :x: [red]Failed to write {filename}: {e}[/red]")
            
    print(f"\n:sparkles: [bold]Successfully wrote {written_count}/{total_files} files.[/bold]")

@app.command()
def init():
    """
    Scan the current project and generate all required DevOps files.
    """
    print(Panel("Welcome to [bold magenta]Spectra CLI[/bold magenta]!", title="Spectra", border_style="magenta"))
    
    project_context = scan_project('.')
    
    if not project_context:
        print(":x: [red]Could not analyze project. Exiting.[/red]")
        raise typer.Exit(1)
        
    spinner = Spinner("dots", text=" :brain: Asking the AI brain to generate DevOps files (this may take a minute)...")
    generated_files = None
    
    with spinner:
        generated_files = asyncio.run(get_deployment_files(project_context))
        
    if not generated_files:
        print(":x: [red]Failed to get a response from the AI brain. Exiting.[/red]")
        raise typer.Exit(1)

    # The API returns a dict like {'dockerfile': '...', 'compose': '...'}
    # We map them to filenames.
    file_map = {
        "Dockerfile": generated_files.get("dockerfile"),
        "docker-compose.yml": generated_files.get("compose"),
        ".github/workflows/ci-cd.yml": generated_files.get("github_action")
    }
    
    write_files(file_map)
    
    print("\n:rocket: [bold green]All done![/bold green] Your project is ready to launch.")
    print("Run [cyan]docker-compose up --build[/cyan] to test locally.")

if __name__ == "__main__":
    app()
Part 2: The Serverless "Brain" (API)
Step 2.1: Set up API Dependencies
This API will use FastAPI to receive requests and OpenAI's library to call the LLM.

File: api/requirements.txt

Prompt (for api/requirements.txt):

# This file is for the Vercel Serverless Function
fastapi
uvicorn
openai
pydantic
Step 2.2: Build the API Endpoint
This is the core logic. It receives the context, formats a prompt, calls the LLM, and returns the structured JSON response.

File: api/index.py

Prompt (for api/index.py):

Python

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import openai
import os
import json
from rich import print

# Vercel auto-loads .env variables, but we'll use os.getenv for safety
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

class ProjectContext(BaseModel):
    stack: str
    files: dict

class DevOpsFiles(BaseModel):
    dockerfile: str | None
    compose: str | None
    github_action: str | None

def get_llm_response(context: ProjectContext) -> DevOpsFiles:
    """
    Calls the OpenAI API to generate the DevOps files.
    """
    if not openai.api_key:
        print(":x: [bold red]FATAL: OPENAI_API_KEY is not set![/bold red]")
        raise HTTPException(status_code=500, detail="OpenAI API key is not configured on the server.")

    # Convert file context to a more readable string for the prompt
    file_context_str = "\n".join([
        f"--- File: {filename} ---\n{content}\n"
        for filename, content in context.files.items()
    ])
    
    system_prompt = "You are 'Spectra', an expert DevOps engineer. Your sole purpose is to generate production-ready DevOps files based on a project's context. You MUST return ONLY a valid JSON object with three keys: 'dockerfile', 'compose', and 'github_action'."
    
    user_prompt = f"""
    A developer needs DevOps files for their project.
    
    Project Context:
    - Detected Stack: {context.stack}
    - Relevant Files:
    {file_context_str}
    
    Instructions:
    1.  **dockerfile**: Create a multi-stage, production-optimized Dockerfile. It must be efficient and secure.
    2.  **compose**: Create a `docker-compose.yml` file for local development. It should build from the Dockerfile and map the necessary ports.
    3.  **github_action**: Create a GitHub Actions workflow file (`.github/workflows/ci-cd.yml`). It should trigger on push to 'main', build the Docker image, and push it to GitHub Container Registry (GHCR).
    
    Return ONLY the valid, minified JSON object.
    Example: {{"dockerfile": "FROM...", "compose": "version: '3.8'...", "github_action": "name: CI/CD..."}}
    """
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4-turbo", # or gpt-3.5-turbo for speed
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        
        response_json_str = response.choices[0].message.content
        print(":robot: AI Response received.")
        
        # Parse the JSON string from the LLM
        data = json.loads(response_json_str)
        
        return DevOpsFiles(
            dockerfile=data.get('dockerfile'),
            compose=data.get('compose'),
            github_action=data.get('github_action')
        )
        
    except Exception as e:
        print(f":x: [bold red]Error calling OpenAI or parsing response: {e}[/bold red]")
        raise HTTPException(status_code=500, detail=f"AI model error: {e}")


@app.post("/", response_model=DevOpsFiles)
async def generate_devops(request: Request):
    """
    Main API endpoint. Receives project context and returns DevOps files.
    """
    print(":signal_strength: API request received.")
    try:
        raw_body = await request.body()
        data = json.loads(raw_body)
        context = ProjectContext(**data)
        
        print(f":file_folder: Processing project with stack: {context.stack}")
        
        files = get_llm_response(context)
        
        print(":white_check_mark: [bold green]Successfully generated files.[/bold green]")
        return files
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")
    except Exception as e:
        # Catch any other unexpected errors
        print(f":x: [bold red]An unexpected error occurred in the API: {e}[/bold red]")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
Part 3: Execution & Deployment
Step 3.1: Run the API Locally
Install API dependencies: pip install -r api/requirements.txt

Set OpenAI Key: export OPENAI_API_KEY='your-api-key-here'

Run API: uvicorn api.index:app --host 127.0.0.1 --port 8000

The API is now running at http://127.0.0.1:8000/

Step 3.2: Run the CLI Locally
Install CLI dependencies: pip install -r requirements.txt (or better, use a venv).

Install your CLI in editable mode: pip install -e .

Set the API URL: export SPECTRA_API_URL='http://127.0.0.1:8000/'

Test it: Go to a simple test project (e.g., a "hello world" Node.js app) and run: spectra init

Step 3.3: Deploy the "Brain" to Vercel
Install Vercel CLI: npm install -g vercel

Login: vercel login

Deploy: From the spectra-cli-mvp root, run vercel deploy.

Set Secrets: Vercel will deploy, but it will fail without the API key.

Run: vercel env add OPENAI_API_KEY (and paste your key).

Redeploy to apply the key.

Get Production URL: Vercel will give you a production URL (e.g., https://spectra-api.vercel.app).

Step 3.4: Point CLI to Production
Set the environment variable permanently for your CLI users (or hard-code it in client.py for the MVP):

export SPECTRA_API_URL='https://your-api.vercel.app/'

Your CLI is now globally functional.