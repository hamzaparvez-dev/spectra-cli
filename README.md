# Spectra CLI

🎯 **Generate production-ready DevOps files for your projects using AI**

Spectra CLI scans your project, identifies the tech stack, and automatically generates production-ready DevOps files including:
- **Dockerfile** - Multi-stage, optimized Docker images
- **docker-compose.yml** - Local development setup
- **GitHub Actions CI/CD** - Automated build and deployment workflows

## Features

- 🔍 **Smart Project Scanning** - Automatically detects your tech stack (Node.js, Python, Java, Go, Rust, PHP, etc.)
- 🤖 **AI-Powered Generation** - Uses GPT-4 to generate production-ready DevOps files
- ⚡ **Fast & Simple** - One command to generate everything you need
- 🔒 **Production-Ready** - Follows best practices for security and performance

## Installation

### Option 1: Install from Source (Development)

```bash
# Clone the repository
git clone https://github.com/yourusername/spectra-cli.git
cd spectra-cli

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in editable mode
pip install -e .
```

### Option 2: Install via pip (Production)

```bash
pip install spectra-cli
```

## Quick Start

1. **Navigate to your project directory:**
   ```bash
   cd /path/to/your/project
   ```

2. **Run Spectra:**
   ```bash
   spectra init
   ```

3. **That's it!** Spectra will:
   - Scan your project
   - Detect your tech stack
   - Generate Dockerfile, docker-compose.yml, and CI/CD workflows

## Configuration

### Environment Variables

- `SPECTRA_API_URL` - API endpoint URL (default: `http://127.0.0.1:8000/`)
  ```bash
  export SPECTRA_API_URL='https://your-api.vercel.app/'
  ```

### Command Options

```bash
# Scan a specific directory
spectra init /path/to/project

# Use a custom API URL
spectra init --api-url https://custom-api.example.com/

# Check version
spectra version
```

## Local Development

### Running the API Locally

1. **Install API dependencies:**
   ```bash
   pip install -r api/requirements.txt
   ```

2. **Set OpenAI API key:**
   ```bash
   export OPENAI_API_KEY='your-api-key-here'
   ```

3. **Run the API server:**
   ```bash
   uvicorn api.index:app --host 127.0.0.1 --port 8000
   ```

4. **Test the CLI:**
   ```bash
   export SPECTRA_API_URL='http://127.0.0.1:8000/'
   spectra init
   ```

## Deployment

### Deploy API to Vercel

1. **Install Vercel CLI:**
   ```bash
   npm install -g vercel
   ```

2. **Login to Vercel:**
   ```bash
   vercel login
   ```

3. **Deploy:**
   ```bash
   vercel deploy
   ```

4. **Set environment variables:**
   ```bash
   vercel env add OPENAI_API_KEY
   # Paste your OpenAI API key when prompted
   ```

5. **Redeploy to apply changes:**
   ```bash
   vercel --prod
   ```

6. **Update CLI to use production API:**
   ```bash
   export SPECTRA_API_URL='https://your-api.vercel.app/'
   ```

## Project Structure

```
spectra-cli/
├── spectra/              # CLI package
│   ├── __init__.py
│   ├── main.py          # CLI entry point
│   ├── scanner.py       # Project scanner
│   └── client.py        # API client
├── api/                 # Serverless API
│   ├── index.py        # FastAPI app
│   └── requirements.txt
├── requirements.txt     # CLI dependencies
├── pyproject.toml      # Package configuration
├── vercel.json         # Vercel config
└── README.md
```

## Supported Tech Stacks

- **Node.js** - Detected via `package.json`
- **Python** - Detected via `requirements.txt`, `Pipfile`, or `pyproject.toml`
- **Java (Maven)** - Detected via `pom.xml`
- **Java (Gradle)** - Detected via `build.gradle`
- **Go** - Detected via `go.mod`
- **Rust** - Detected via `Cargo.toml`
- **PHP** - Detected via `composer.json`

## Requirements

- Python 3.8 or higher
- OpenAI API key (for the API server)
- Internet connection (to call the API)

## Troubleshooting

### CLI can't connect to API

- Check that `SPECTRA_API_URL` is set correctly
- Verify the API server is running (if testing locally)
- Check your network connection

### No files generated

- Ensure your project contains recognizable files (package.json, requirements.txt, etc.)
- Check that the API is responding correctly
- Review API logs for errors

### OpenAI API errors

- Verify `OPENAI_API_KEY` is set correctly on the server
- Check your OpenAI account has sufficient credits
- Ensure you're using a valid API key

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- Open an issue on GitHub
- Check the documentation
- Review the troubleshooting section

---

Built with ❤️ by the Spectra team

