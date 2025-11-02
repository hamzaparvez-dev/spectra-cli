"""Project file scanning logic to identify stack and gather context."""

import os
import json
from typing import Optional
from rich import print

MAX_FILE_SIZE_BYTES = 10000  # 10KB limit for context
RELEVANT_FILES = [
    'package.json', 'requirements.txt', 'pom.xml', 'go.mod',
    'docker-compose.yml', 'Dockerfile', 'main.py', 'app.py', 'server.js', 'index.js',
    'package-lock.json', 'yarn.lock', 'Pipfile', 'pyproject.toml', 'setup.py',
    'build.gradle', 'gradle.properties', 'composer.json', 'Cargo.toml'
]

# Additional ignore patterns
IGNORE_PATTERNS = {
    'node_modules', '.git', '.venv', 'venv', 'env', '__pycache__',
    '.next', '.nuxt', 'dist', 'build', '.cache'
}


def scan_project(path: str) -> Optional[str]:
    """
    Scans the project directory, identifies the stack, and gathers context
    from relevant files. Returns a JSON string of the context.
    
    Args:
        path: The project directory path to scan
        
    Returns:
        JSON string containing stack and files, or None if no relevant files found
    """
    print(f":mag: [bold cyan]Scanning project at {path}...[/bold cyan]")
    
    context = {
        "stack": "unknown",
        "files": {}
    }
    
    found_files = []
    path = os.path.abspath(os.path.expanduser(path))
    
    if not os.path.isdir(path):
        print(f":x: [red]Error: {path} is not a valid directory.[/red]")
        return None

    for root, dirs, files in os.walk(path):
        # Skip ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_PATTERNS]
        
        # Ignore hidden directories
        if any(part.startswith('.') and part != '.' for part in root.split(os.sep)):
            continue
            
        for file in files:
            if file in RELEVANT_FILES:
                file_path = os.path.join(root, file)
                
                # Check file size
                try:
                    file_size = os.path.getsize(file_path)
                    if file_size > MAX_FILE_SIZE_BYTES:
                        print(f":warning: Skipping {file_path}, file is too large ({file_size} bytes).")
                        continue
                except OSError:
                    print(f":warning: Could not read size of {file_path}, skipping.")
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    relative_path = os.path.relpath(file_path, path)
                    context["files"][relative_path] = content
                    found_files.append(relative_path)
                    
                    # Stack detection with priority
                    if file == 'package.json':
                        context['stack'] = 'nodejs'
                    elif file == 'requirements.txt' or file == 'Pipfile' or file == 'pyproject.toml':
                        if context['stack'] == 'unknown':
                            context['stack'] = 'python'
                    elif file == 'pom.xml':
                        context['stack'] = 'java_maven'
                    elif file == 'go.mod':
                        context['stack'] = 'golang'
                    elif file == 'build.gradle':
                        context['stack'] = 'java_gradle'
                    elif file == 'composer.json':
                        context['stack'] = 'php'
                    elif file == 'Cargo.toml':
                        context['stack'] = 'rust'

                except UnicodeDecodeError:
                    print(f":warning: Skipping {file_path}, not a text file.")
                except Exception as e:
                    print(f":x: Error reading {file_path}: {e}")

    if not found_files:
        print(":warning: No relevant project files found.")
        return None

    print(f":white_check_mark: [bold green]Scan complete.[/bold green] Found stack: [bold]{context['stack']}[/bold]")
    return json.dumps(context, indent=2)

