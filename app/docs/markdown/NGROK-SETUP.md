# ngrok Tunnel Setup for AdvanDEB

## Overview

ngrok creates secure tunnels to expose your local development server to the internet. This is useful for:
- Testing OAuth from mobile devices
- Sharing your development environment
- Testing webhooks
- Accessing from anywhere

## Quick Start

### Option 1: Single Tunnel (Frontend Only)

```bash
# Terminal 1: Start frontend
cd frontend
npm run dev

# Terminal 2: Start ngrok tunnel
ngrok http 5173
```

**Copy the https URL** (e.g., `https://xxxx-xxx.ngrok-free.app`)

### Option 2: Multiple Tunnels (Frontend + Backend)

You need a paid ngrok account for multiple simultaneous tunnels.

```bash
# Start both tunnels
./scripts/start-ngrok.sh
```

Or manually:

```bash
# Terminal 2: Frontend tunnel
ngrok http 5173 --subdomain your-custom-name

# Terminal 3: Backend tunnel  
ngrok http 8000 --subdomain your-backend-name
```

## Configuration Steps

### 1. Get Your ngrok URLs

After starting ngrok, you'll see output like:
```
Forwarding   https://xxxx-xxx.ngrok-free.app -> http://localhost:5173
```

**Copy these URLs:**
- Frontend URL: `https://xxxx-xxx.ngrok-free.app`
- Backend URL: `https://yyyy-yyy.ngrok-free.app` (if running)

### 2. Update Google OAuth Configuration

**Go to Google Cloud Console**: https://console.cloud.google.com/apis/credentials

**Add to Authorized JavaScript Origins:**
```
https://xxxx-xxx.ngrok-free.app
```

**Add to Authorized Redirect URIs:**
```
https://xxxx-xxx.ngrok-free.app/login
```

**Save and wait 5-10 minutes** for Google to propagate changes.

### 3. Update Environment Variables

**Frontend `.env.local`:**
```bash
# If backend also has tunnel
VITE_API_BASE_URL=https://yyyy-yyy.ngrok-free.app

# If backend is still local
VITE_API_BASE_URL=http://localhost:8000

VITE_APP_NAME=AdvanDEB Modeling Assistant
VITE_GOOGLE_CLIENT_ID=827103165308-uo0a6ieknjmlqiq2rng2pdm5pbvj4b7s.apps.googleusercontent.com
```

**Backend `.env` (if using backend tunnel):**
```bash
GOOGLE_REDIRECT_URI=https://yyyy-yyy.ngrok-free.app/api/auth/callback
CORS_ORIGINS=https://xxxx-xxx.ngrok-free.app,http://localhost:5173
```

### 4. Restart Services

```bash
# Restart frontend (if env changed)
cd frontend
# Ctrl+C to stop
npm run dev

# Restart backend (if env changed)
cd backend
# Ctrl+C to stop
uvicorn app.main:app --reload
```

## Accessing the Application

1. Open your **ngrok frontend URL** in any browser (desktop, mobile, anywhere)
2. Click "Sign in with Google"
3. Should work after Google OAuth propagation (5-10 minutes)

## ngrok Free vs Paid

### Free Account
- ✅ 1 online ngrok process
- ✅ 4 tunnels/ngrok process
- ✅ Random URLs (changes each restart)
- ❌ No custom subdomains
- ⚠️ Warning banner on free URLs

### Paid Account ($8/month)
- ✅ Multiple simultaneous tunnels
- ✅ Custom subdomains (`your-name.ngrok.app`)
- ✅ No warning banner
- ✅ Reserved domains
- ✅ IP whitelisting

## Persistent ngrok with Custom Domain (Paid)

Edit `ngrok.yml`:
```yaml
authtoken: YOUR_AUTH_TOKEN
version: 2
tunnels:
  backend:
    proto: http
    addr: 8000
    subdomain: advandeb-api  # Requires paid plan
  frontend:
    proto: http
    addr: 5173
    subdomain: advandeb-app  # Requires paid plan
```

Start both:
```bash
ngrok start --all --config ngrok.yml
```

## Helper Scripts

### Start Single Tunnel
```bash
./scripts/ngrok-single.sh frontend 5173
# Or
./scripts/ngrok-single.sh backend 8000
```

### Check Active Tunnels
```bash
curl http://localhost:4040/api/tunnels | python3 -m json.tool
```

### View ngrok Dashboard
Open in browser: http://localhost:4040

## Troubleshooting

### ngrok Not Found
```bash
# Check installation
which ngrok

# Install if needed
# macOS
brew install ngrok

# Linux
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | \
  sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && \
  echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | \
  sudo tee /etc/apt/sources.list.d/ngrok.list && \
  sudo apt update && sudo apt install ngrok
```

### Auth Token Required
```bash
# Get token from https://dashboard.ngrok.com/get-started/your-authtoken
ngrok config add-authtoken YOUR_TOKEN
```

### URL Changes on Restart
- Use paid plan for persistent subdomains
- Or update Google OAuth each time (not recommended)
- Consider using localhost with port forwarding instead

### CORS Errors
Update backend `.env`:
```bash
CORS_ORIGINS=https://your-ngrok-url.ngrok-free.app,http://localhost:5173
```

### OAuth Still Failing
1. Wait 10-15 minutes after updating Google Console
2. Clear browser cache/cookies
3. Try incognito mode
4. Verify exact URLs match in Google Console (no trailing slashes)
5. Check ngrok URL hasn't changed

### ngrok Tunnel Closed
Free tunnels close after inactivity. Just restart:
```bash
ngrok http 5173
```

## Production Alternative

For production, use a proper domain with SSL:
- Deploy to cloud provider (AWS, GCP, Azure)
- Use domain like `app.advandeb.com`
- Configure SSL certificates (Let's Encrypt)
- Update Google OAuth with production URLs

## Current Setup

Your current ngrok:
- **Frontend tunnel**: `https://adeb.ngrok.app` (if configured)
- **Running**: Check with `ps aux | grep ngrok`
- **Dashboard**: http://localhost:4040

To use with OAuth:
1. Add `https://adeb.ngrok.app` to Google Console
2. Add `https://adeb.ngrok.app/login` to redirect URIs
3. Wait 5-10 minutes
4. Access app via ngrok URL

## Next Steps

1. ✅ ngrok is installed
2. ✅ Tunnel is running
3. ⏳ Add URLs to Google OAuth Console
4. ⏳ Update environment variables if needed
5. ⏳ Test login flow

**Remember**: Free ngrok URLs change each time you restart ngrok!
