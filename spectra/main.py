"""Main CLI entry point using Typer."""

import typer
import asyncio
from rich import print
from rich.spinner import Spinner
from rich.panel import Panel
import os
from typing import Dict, Optional

from .scanner import scan_project
from .client import get_deployment_files

app = typer.Typer(
    name="spectra",
    help="Spectra CLI - Generate production-ready DevOps files for your projects.",
    add_completion=False
)


def write_files(files: Dict[str, Optional[str]]) -> int:
    """
    Writes the generated files to the disk.
    
    Args:
        files: Dictionary mapping filenames to file contents
        
    Returns:
        Number of files successfully written
    """
    total_files = len([f for f in files.values() if f])  # Count non-empty files
    written_count = 0
    
    print("\n:floppy_disk: [bold green]Writing generated files...[/bold green]")
    
    for filename, content in files.items():
        if not content:
            print(f":warning: No content generated for {filename}, skipping.")
            continue
        
        # Ensure directory exists for nested paths
        dir_path = os.path.dirname(filename)
        if dir_path:
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                print(f"  :x: [red]Failed to create directory {dir_path}: {e}[/red]")
                continue
            
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  :page_facing_up: Created {filename}")
            written_count += 1
        except OSError as e:
            print(f"  :x: [red]Failed to write {filename}: {e}[/red]")
        except Exception as e:
            print(f"  :x: [red]Unexpected error writing {filename}: {e}[/red]")
            
    print(f"\n:sparkles: [bold]Successfully wrote {written_count}/{total_files} files.[/bold]")
    return written_count


@app.command()
def init(
    path: str = typer.Argument(".", help="Path to the project directory to scan"),
    api_url: Optional[str] = typer.Option(None, "--api-url", "-u", help="Override the API URL")
):
    """
    Scan the current project and generate all required DevOps files.
    
    This command will:
    1. Scan your project to identify the tech stack
    2. Send context to the AI brain
    3. Generate Dockerfile, docker-compose.yml, and GitHub Actions CI/CD workflow
    """
    print(Panel(
        "Welcome to [bold magenta]Spectra CLI[/bold magenta]!\n\n"
        "Generating production-ready DevOps files for your project...",
        title="Spectra",
        border_style="magenta"
    ))
    
    # Override API URL if provided
    if api_url:
        os.environ["SPECTRA_API_URL"] = api_url
    
    project_context = scan_project(path)
    
    if not project_context:
        print(":x: [red]Could not analyze project. Exiting.[/red]")
        raise typer.Exit(1)
        
    spinner = Spinner(
        "dots",
        text=" :brain: Asking the AI brain to generate DevOps files (this may take a minute)..."
    )
    generated_files = None
    
    with spinner:
        generated_files = asyncio.run(get_deployment_files(project_context))
        
    if not generated_files:
        print(":x: [red]Failed to get a response from the AI brain. Exiting.[/red]")
        raise typer.Exit(1)

    # The API returns a dict like {'dockerfile': '...', 'compose': '...', 'github_action': '...'}
    # We map them to filenames.
    file_map = {
        "Dockerfile": generated_files.get("dockerfile"),
        "docker-compose.yml": generated_files.get("compose"),
        ".github/workflows/ci-cd.yml": generated_files.get("github_action")
    }
    
    written = write_files(file_map)
    
    if written > 0:
        print("\n:rocket: [bold green]All done![/bold green] Your project is ready to launch.")
        print("Run [cyan]docker-compose up --build[/cyan] to test locally.")
    else:
        print("\n:x: [red]No files were generated. Please check the API response.[/red]")
        raise typer.Exit(1)


@app.command()
def version():
    """Show the version of Spectra CLI."""
    from . import __version__
    print(f"Spectra CLI version [bold cyan]{__version__}[/bold cyan]")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()

