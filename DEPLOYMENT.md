# Vercel Deployment Checklist

## Pre-Deployment

- [x] All dependencies updated in `api/requirements.txt`
- [x] OpenRouter API integration complete
- [x] Critical bug fixed (app initialization)
- [x] Local testing passed (health, templates, CLI)
- [x] `vercel.json` configured correctly
- [x] `.env.example` created with proper documentation

## Deployment Steps

### 1. Get OpenRouter API Key
- Visit: https://openrouter.ai/keys
- Sign up (free, no credit card required)
- Create new API key
- Copy the key

### 2. Install Vercel CLI (if not installed)
```bash
npm install -g vercel
```

### 3. Login to Vercel
```bash
vercel login
```

### 4. Deploy to Production
```bash
cd /Users/admin/Downloads/spectra-cli/spectra-cli
vercel --prod
```

### 5. Configure Environment Variables
```bash
vercel env add OPENROUTER_API_KEY production
# Paste your OpenRouter API key when prompted
```

### 6. Redeploy to Apply Environment Variables
```bash
vercel --prod
```

### 7. Test Production API
```bash
# Get your production URL from Vercel output
export PROD_URL="https://your-app.vercel.app"

# Test health endpoint
curl $PROD_URL/health

# Test root endpoint
curl $PROD_URL/

# Test template matching
curl -X POST $PROD_URL/ \
  -H "Content-Type: application/json" \
  -d '{"stack":"nodejs","files":{"package.json":"{}"}}'
```

### 8. Update CLI to Use Production API
```bash
export SPECTRA_API_URL="https://your-app.vercel.app/"
```

### 9. Test CLI with Production API
```bash
cd test-projects/python
rm -f Dockerfile docker-compose.yml
rm -rf .github
spectra init .
```

## Post-Deployment Verification

- [ ] Health endpoint returns 200 OK
- [ ] Root endpoint shows API info
- [ ] Template matching works for common stacks
- [ ] CLI can connect to production API
- [ ] Generated files are production-ready
- [ ] No errors in Vercel logs

## Rollback Plan

If deployment fails:
1. Check Vercel logs: `vercel logs`
2. Verify environment variables: `vercel env ls`
3. Test locally first
4. Redeploy previous version if needed

## Production URL

After deployment, update these files with your production URL:
- `README.md` (line 21)
- `.env.example`
- Documentation references

## Notes

- Free tier limits: Check OpenRouter usage
- Vercel timeout: 300s (configured in vercel.json)
- Memory: 1024MB (configured in vercel.json)
- Python version: 3.11 (configured in vercel.json)
