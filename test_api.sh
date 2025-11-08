#!/bin/bash
# Test script for Spectra API
# Usage: ./test_api.sh [API_URL]

API_URL="${1:-https://spectra-cli.vercel.app}"

echo "🧪 Testing Spectra API at: $API_URL"
echo ""

# Test 1: Health Check
echo "1️⃣ Testing Health Endpoint..."
curl -s "$API_URL/health" | jq '.' || echo "❌ Health check failed"
echo ""

# Test 2: Root Endpoint (should return HTML)
echo "2️⃣ Testing Root Endpoint (GET)..."
curl -s -I "$API_URL/" | head -5
echo ""

# Test 3: Template Cache Test (Python)
echo "3️⃣ Testing Template Cache (Python stack)..."
curl -s -X POST "$API_URL/" \
  -H "Content-Type: application/json" \
  -d '{"stack": "python", "files": {"main.py": "print(\"Hello\")"}}' | jq '.' || echo "❌ Template test failed"
echo ""

# Test 4: Job Creation Test (Custom stack)
echo "4️⃣ Testing Job Creation (Custom stack)..."
JOB_RESPONSE=$(curl -s -X POST "$API_URL/" \
  -H "Content-Type: application/json" \
  -d '{"stack": "custom", "files": {"app.js": "console.log(\"test\")"}}')
echo "$JOB_RESPONSE" | jq '.' || echo "❌ Job creation failed"

JOB_ID=$(echo "$JOB_RESPONSE" | jq -r '.job_id // empty')
if [ -n "$JOB_ID" ]; then
  echo "✅ Job created: $JOB_ID"
  echo ""
  echo "5️⃣ Checking Job Status..."
  sleep 2
  curl -s "$API_URL/job/$JOB_ID" | jq '.' || echo "❌ Job status check failed"
fi

echo ""
echo "✅ Testing complete!"

