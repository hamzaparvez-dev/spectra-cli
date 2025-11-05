"""HTTP client to communicate with the Spectra API brain."""

import httpx
import os
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


async def get_deployment_files(project_context: str) -> Optional[Dict[str, Any]]:
    """
    Calls the serverless 'brain' API with the project context
    and returns the generated DevOps files.
    
    Args:
        project_context: JSON string containing project context
        
    Returns:
        Dictionary with deployment files, or None on error
    """
    api_url = get_api_url()  # Get fresh URL in case env changed
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                api_url,
                content=project_context,
                headers={"Content-Type": "application/json"}
            )
            
            response.raise_for_status()  # Raises exception for 4xx/5xx
            
            return response.json()
            
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

