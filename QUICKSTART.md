# Quick Start Guide - OpenRouter Setup

## 1. Get Your Free OpenRouter API Key

1. Visit https://openrouter.ai/keys
2. Sign up (no credit card required)
3. Create a new API key
4. Copy the key

## 2. Configure Local Environment

Create a `.env` file in the project root:

```bash
# Copy from example
cp .env.example .env

# Edit .env and add your key
OPENROUTER_API_KEY=your_actual_key_here
SPECTRA_API_URL=http://127.0.0.1:8000/
```

## 3. Install Dependencies

```bash
# Install API dependencies
pip install -r api/requirements.txt

# Install CLI dependencies
pip install -r requirements.txt

# Install CLI in editable mode
pip install -e .
```

## 4. Test Locally

### Start the API Server
```bash
export OPENROUTER_API_KEY='your_key_here'
uvicorn api.index:app --host 127.0.0.1 --port 8000
```

### Test the CLI
In a new terminal:
```bash
export SPECTRA_API_URL='http://127.0.0.1:8000/'
cd /path/to/test/project
spectra init
```

## 5. Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy
vercel --prod

# Set environment variable
vercel env add OPENROUTER_API_KEY
# Paste your key when prompted

# Redeploy to apply
vercel --prod
```

## 6. Use Production API

```bash
export SPECTRA_API_URL='https://your-app.vercel.app/'
spectra init
```

## Common Stacks (Instant Response)

These stacks get instant template responses:
- ✅ Python (requirements.txt, pyproject.toml, Pipfile)
- ✅ Node.js (package.json)
- ✅ Go (go.mod)
- ✅ Rust (Cargo.toml)
- ✅ Java Maven (pom.xml)
- ✅ Java Gradle (build.gradle)

Custom stacks use async processing with OpenRouter API.
