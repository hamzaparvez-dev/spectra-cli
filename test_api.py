#!/usr/bin/env python3
"""Test script for Spectra API - Simple way to verify your deployment is working."""

import sys
import json
import requests
from typing import Optional

API_URL = "https://spectra-cli.vercel.app"

def test_health(api_url: str) -> bool:
    """Test the health endpoint."""
    print("1️⃣ Testing Health Endpoint...")
    try:
        response = requests.get(f"{api_url}/health", timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"   ✅ Health check passed: {data}")
        return True
    except Exception as e:
        print(f"   ❌ Health check failed: {e}")
        return False

def test_root_get(api_url: str) -> bool:
    """Test the root GET endpoint (should return HTML)."""
    print("\n2️⃣ Testing Root Endpoint (GET - should return HTML)...")
    try:
        response = requests.get(f"{api_url}/", timeout=10)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '')
        if 'text/html' in content_type:
            print(f"   ✅ Root endpoint returns HTML (Status: {response.status_code})")
            return True
        else:
            print(f"   ⚠️  Root endpoint returned {content_type} instead of HTML")
            return False
    except Exception as e:
        print(f"   ❌ Root endpoint test failed: {e}")
        return False

def test_template_cache(api_url: str) -> bool:
    """Test template caching with Python stack."""
    print("\n3️⃣ Testing Template Cache (Python stack)...")
    try:
        payload = {
            "stack": "python",
            "files": {
                "main.py": "print('Hello, World!')"
            }
        }
        response = requests.post(
            f"{api_url}/",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        # Check if we got files directly (template hit) or job_id (async)
        if "dockerfile" in data or "compose" in data or "github_action" in data:
            print(f"   ✅ Template cache hit! Got files instantly.")
            print(f"   📄 Files returned: {list(data.keys())}")
            return True
        elif "job_id" in data:
            print(f"   ⚠️  No template found, job created: {data.get('job_id')}")
            return True
        else:
            print(f"   ⚠️  Unexpected response: {data}")
            return False
    except Exception as e:
        print(f"   ❌ Template cache test failed: {e}")
        return False

def test_job_creation(api_url: str) -> Optional[str]:
    """Test job creation with custom stack."""
    print("\n4️⃣ Testing Job Creation (Custom stack)...")
    try:
        payload = {
            "stack": "custom-test",
            "files": {
                "app.js": "console.log('test');"
            }
        }
        response = requests.post(
            f"{api_url}/",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if "job_id" in data:
            job_id = data["job_id"]
            print(f"   ✅ Job created: {job_id}")
            return job_id
        else:
            print(f"   ⚠️  Unexpected response: {data}")
            return None
    except Exception as e:
        print(f"   ❌ Job creation failed: {e}")
        return None

def test_job_status(api_url: str, job_id: str) -> bool:
    """Test job status endpoint."""
    print(f"\n5️⃣ Checking Job Status for {job_id}...")
    try:
        response = requests.get(f"{api_url}/job/{job_id}", timeout=10)
        response.raise_for_status()
        data = response.json()
        status = data.get("status", "unknown")
        print(f"   ✅ Job status: {status}")
        if status == "completed":
            print(f"   🎉 Job completed! Result available.")
        elif status == "failed":
            error = data.get("error", "Unknown error")
            print(f"   ❌ Job failed: {error}")
        return True
    except Exception as e:
        print(f"   ❌ Job status check failed: {e}")
        return False

def main():
    """Run all tests."""
    api_url = sys.argv[1] if len(sys.argv) > 1 else API_URL
    
    print(f"🧪 Testing Spectra API at: {api_url}\n")
    print("=" * 60)
    
    results = []
    results.append(test_health(api_url))
    results.append(test_root_get(api_url))
    results.append(test_template_cache(api_url))
    
    job_id = test_job_creation(api_url)
    if job_id:
        results.append(test_job_status(api_url, job_id))
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All tests passed! Your API is working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

