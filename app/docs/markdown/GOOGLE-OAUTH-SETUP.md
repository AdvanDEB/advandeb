# Google OAuth Configuration for Network Access

## Problem

Google OAuth blocks redirects to private IP addresses (like `http://192.168.0.51:5173`) for security reasons. You're seeing:
```
Error 400: invalid_request
device_id and device_name are required for private IP
```

## Solutions

### Option 1: Use localhost (Recommended for Development)

Access the application via `http://localhost:5173` instead of the IP address.

**Pros:**
- No configuration changes needed
- Works immediately

**Cons:**
- Only accessible from the same machine

### Option 2: Add Authorized Redirect URIs in Google Cloud Console

If you need network access (from other devices), add the IP address to Google OAuth configuration.

#### Steps:

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/
   - Select your project

2. **Navigate to Credentials**
   - APIs & Services → Credentials
   - Click on your OAuth 2.0 Client ID

3. **Add Authorized JavaScript Origins**
   ```
   http://192.168.0.51:5173
   http://localhost:5173
   ```

4. **Add Authorized Redirect URIs**
   ```
   http://192.168.0.51:5173/login
   http://localhost:5173/login
   ```

5. **Save changes**
   - Click "Save" at the bottom

6. **Wait 5-10 minutes**
   - Google needs time to propagate changes

#### Update Environment Variables

After adding URIs to Google Console, update your configuration:

**Frontend `.env.local`:**
```bash
# Use the IP or localhost depending on how you access it
VITE_API_BASE_URL=http://192.168.0.51:8000
VITE_APP_NAME=AdvanDEB Modeling Assistant
VITE_GOOGLE_CLIENT_ID=827103165308-uo0a6ieknjmlqiq2rng2pdm5pbvj4b7s.apps.googleusercontent.com
```

**Backend `.env`:**
```bash
# Keep localhost for backend API callback
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/callback
```

#### Restart Services

```bash
# Stop and restart backend
cd backend
# Press Ctrl+C to stop
uvicorn app.main:app --reload

# Stop and restart frontend
cd frontend
# Press Ctrl+C to stop
npm run dev
```

### Option 3: Use a Custom Domain with DNS (Production)

For production or team development:

1. **Set up a local DNS** (e.g., `advandeb.local`)
   - Add to `/etc/hosts`:
     ```
     192.168.0.51  advandeb.local
     ```

2. **Configure Google OAuth** with the domain:
   - Authorized JavaScript origins: `http://advandeb.local:5173`
   - Authorized redirect URIs: `http://advandeb.local:5173/login`

3. **Update environment variables** to use `advandeb.local`

### Option 4: Use ngrok (Temporary Public URL)

For testing or sharing with others outside your network:

1. **Install ngrok**
   ```bash
   # Download from https://ngrok.com/
   # Or use conda
   conda install -c conda-forge ngrok
   ```

2. **Start ngrok tunnel**
   ```bash
   # For frontend
   ngrok http 5173
   
   # For backend (in another terminal)
   ngrok http 8000
   ```

3. **Update Google OAuth** with ngrok URLs:
   - Authorized JavaScript origins: `https://xxxx-xx-xx-xx-xx.ngrok-free.app`
   - Authorized redirect URIs: `https://xxxx-xx-xx-xx-xx.ngrok-free.app/login`

4. **Update environment variables** to use ngrok URLs

## Recommended Setup for Development

### For Solo Development (Same Machine)
✅ **Use localhost** - No configuration needed
- Access at: `http://localhost:5173`

### For Team Development (Multiple Machines on Network)
✅ **Use Option 2** - Add IP addresses to Google OAuth
- Access at: `http://192.168.0.51:5173`

### For Production
✅ **Use proper domain with HTTPS**
- Example: `https://advandeb.example.com`
- Configure SSL/TLS certificates
- Use production OAuth credentials

## Current Google OAuth Configuration

Your current settings:
- **Client ID**: `827103165308-uo0a6ieknjmlqiq2rng2pdm5pbvj4b7s.apps.googleusercontent.com`
- **Authorized Origins**: Need to verify in Google Console
- **Authorized Redirects**: Need to verify in Google Console

### To Check Current Configuration:

1. Go to: https://console.cloud.google.com/apis/credentials
2. Find your OAuth 2.0 Client ID
3. Check which URIs are currently authorized
4. Add any missing URIs listed above

## Testing After Configuration

1. **Clear browser cache** (or use incognito mode)
2. **Try accessing**: `http://192.168.0.51:5173`
3. **Click "Sign in with Google"**
4. **Should redirect successfully** after ~5 minutes of Google propagation

## Troubleshooting

### Still Getting Error 400?
- Wait 10-15 minutes for Google to update
- Clear browser cookies/cache
- Try incognito/private window
- Verify URIs match exactly (no trailing slashes)

### Redirect URI Mismatch?
- Check the error message for what URI Google received
- Add that exact URI to Google Console
- URIs are case-sensitive and must match exactly

### Network Not Accessible?
- Check firewall settings
- Verify port 5173 and 8000 are open
- Confirm IP address is correct: `ip addr show`

## Quick Reference

**Add these URIs to Google Console:**

For localhost development:
```
http://localhost:5173
http://localhost:5173/login
http://localhost:8000
http://localhost:8000/api/auth/callback
```

For network access (replace with your IP):
```
http://192.168.0.51:5173
http://192.168.0.51:5173/login
http://192.168.0.51:8000
http://192.168.0.51:8000/api/auth/callback
```

**Note**: You can have multiple redirect URIs configured simultaneously!
