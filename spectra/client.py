"""HTTP client to communicate with the Spectra API brain with async job polling."""

import httpx
import os
import asyncio
from typing import Optional, Dict, Any
from rich.panel import Panel
from rich import print

# The 'brain' API URL. Set SPECTRA_API_URL environment variable to configure.
# Default is the stable production domain to make the CLI work out-of-the-box.
# For local development, override with: export SPECTRA_API_URL=http://127.0.0.1:8000/
def get_api_url() -> str:
    """
    Get and normalize the API URL.
    
    Uses SPECTRA_API_URL environment variable if set.
    Defaults to the stable production URL so the CLI works without extra setup.
    For local development, set SPECTRA_API_URL to http://127.0.0.1:8000/.
    """
    url = os.getenv("SPECTRA_API_URL", "https://spectra-cli.vercel.app/")
    # Ensure URL ends with / for consistency
    if not url.endswith('/'):
        url += '/'
    return url


API_URL = get_api_url()

# Polling configuration
POLL_INTERVAL = 3  # seconds
MAX_POLL_ATTEMPTS = 40  # 2 minutes max (40 * 3s = 120s)


async def poll_job_status(job_id: str, api_url: str) -> Optional[Dict[str, Any]]:
    """
    Poll the job status endpoint until completion or failure.
    
    Args:
        job_id: Job ID to poll
        api_url: Base API URL
        
    Returns:
        DevOpsFiles dict if completed, None on failure
    """
    attempts = 0
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        while attempts < MAX_POLL_ATTEMPTS:
            try:
                response = await client.get(f"{api_url}job/{job_id}")
                response.raise_for_status()
                
                job_status = response.json()
                status = job_status.get("status")
                
                if status == "completed":
                    result = job_status.get("result")
                    if result:
                        return result
                    else:
                        print(Panel(
                            "[bold red]Job completed but no result found.[/bold red]",
                            title="Error",
                            border_style="red"
                        ))
                        return None
                        
                elif status == "failed":
                    error = job_status.get("error", "Unknown error")
                    print(Panel(
                        f"[bold red]Job failed:[/bold red] {error}",
                        title="Job Failed",
                        border_style="red"
                    ))
                    return None
                    
                elif status == "pending" or status == "processing":
                    # Continue polling
                    attempts += 1
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                else:
                    print(Panel(
                        f"[bold red]Unknown job status:[/bold red] {status}",
                        title="Error",
                        border_style="red"
                    ))
                    return None
                    
            except httpx.HTTPStatusError as e:
                # Differentiate between fatal and transient errors
                if e.response.status_code == 404:
                    # Job not found - fatal error
                    print(Panel(
                        f"[bold red]Job not found:[/bold red] {job_id}",
                        title="HTTP Error",
                        border_style="red"
                    ))
                    return None
                else:
                    # Transient error - retry on next poll
                    attempts += 1
                    if attempts >= MAX_POLL_ATTEMPTS:
                        break
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
            except Exception as e:
                # Generic error - retry on next poll
                attempts += 1
                if attempts >= MAX_POLL_ATTEMPTS:
                    break
                await asyncio.sleep(POLL_INTERVAL)
                continue
        
        # Timeout
        print(Panel(
            f"[bold red]Job polling timeout:[/bold red] Job {job_id} did not complete within {MAX_POLL_ATTEMPTS * POLL_INTERVAL} seconds.",
            title="Timeout",
            border_style="red"
        ))
        return None


async def get_deployment_files(project_context: str) -> Optional[Dict[str, Any]]:
    """
    Calls the serverless 'brain' API with the project context
    and returns the generated DevOps files.
    
    Flow:
    1. POST to / - checks templates first
    2. If template exists -> returns files immediately
    3. If no template -> returns job_id, then polls /job/{job_id}
    
    Args:
        project_context: JSON string containing project context
        
    Returns:
        Dictionary with deployment files, or None on error
    """
    api_url = get_api_url()  # Get fresh URL in case env changed
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Send request to main endpoint
            response = await client.post(
                api_url,
                content=project_context,
                headers={"Content-Type": "application/json"}
            )
            
            response.raise_for_status()
            result = response.json()
            
            # Step 2: Check if we got files directly (template cache hit)
            if "dockerfile" in result or "compose" in result or "github_action" in result:
                # Template cache hit - return immediately
                return result
            
            # Step 3: Check if we got a job_id (async processing)
            if "job_id" in result:
                job_id = result["job_id"]
                print(f":hourglass: [cyan]Job created: {job_id}[/cyan] - Starting processing...")
                
                # Trigger job processing
                try:
                    process_response = await client.post(f"{api_url}process/{job_id}")
                    if process_response.status_code == 200:
                        print(":gear: [cyan]Job processing started...[/cyan]")
                    else:
                        print(f":warning: [yellow]Could not trigger processing automatically. Status: {process_response.status_code}[/yellow]")
                except Exception as e:
                    print(f":warning: [yellow]Could not trigger processing automatically: {e}[/yellow]")
                    # Continue anyway - job might be processed by background worker
                
                # Poll for job completion
                return await poll_job_status(job_id, api_url)
            
            # Unexpected response format
            print(Panel(
                f"[bold red]Unexpected API response format:[/bold red] {result}",
                title="Error",
                border_style="red"
            ))
            return None
            
    except httpx.HTTPStatusError as e:
        error_msg = f"{e.response.status_code}"
        try:
            error_detail = e.response.json()
            error_msg += f" - {error_detail.get('detail', e.response.text)}"
        except:
            error_msg += f" - {e.response.text}"
        print(Panel(
            f"[bold red]API Error:[/bold red] {error_msg}",
            title="HTTP Error",
            border_style="red"
        ))
        return None
    except httpx.TimeoutException:
        print(Panel(
            "[bold red]Request Timeout:[/bold red] The API took too long to respond. "
            "Please try again or check your network connection.",
            title="Timeout Error",
            border_style="red"
        ))
        return None
    except httpx.RequestError as e:
        url = getattr(e.request, 'url', api_url) if hasattr(e, 'request') else api_url
        print(Panel(
            f"[bold red]Network Error:[/bold red] Failed to connect to {url}. "
            f"Is the API running? Check SPECTRA_API_URL environment variable.",
            title="Connection Error",
            border_style="red"
        ))
        return None
    except Exception as e:
        print(Panel(
            f"[bold red]An unexpected error occurred:[/bold red] {e}",
            title="Error",
            border_style="red"
        ))
        return None
