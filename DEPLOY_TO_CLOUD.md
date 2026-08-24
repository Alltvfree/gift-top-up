# Deploy Tilly to Cloud - 10 Minute Quick Start

**⚡ Get your app live in the cloud using Supabase + Cloudflare Pages + Cloudflare Workers**

---

## 🎯 What You'll Get

- **Frontend** hosted on Cloudflare Pages (FREE)
- **Backend** running on Cloudflare Workers (FREE tier + $0.50 per million requests after)
- **Database** on Supabase (FREE tier + usage-based pricing)
- **Auto-deployment** when you push code

**Total estimated cost: $0-40/month depending on usage**

---

## ⏱️ Step 1: Create Supabase Project (2 minutes)

### 1.1 Go to Supabase

```bash
# Open in browser:
https://supabase.com
```

### 1.2 Sign Up / Log In

Click **"Sign Up"** or **"Log In"**

### 1.3 Create New Project

```
1. Click "New Project"
2. Fill in:
   - Organization: Choose or create
   - Project Name: tilly-app
   - Database Password: [Create strong password - SAVE IT!]
   - Region: Choose closest to you
   - Plan: Free (default)
3. Click "Create new project"
4. Wait 2-3 minutes for setup
```

### 1.4 Get Your Credentials

After project is created:

```
1. Go to Project Settings (⚙️) → API
2. Copy these THREE things:
   
   Project URL: https://xxx.supabase.co
   Anon Key: eyJhbGci...
   Service Role Key: eyJhbGci...
   
3. Save them somewhere safe
```

### 1.5 Initialize Database

```
1. In Supabase dashboard, go to "SQL Editor"
2. Click "New Query"
3. Paste this file's content:
   /home/user/gift-top-up/backend/database/001_initial_schema.sql
4. Click "RUN"
5. Wait for completion ✓
```

---

## ⏱️ Step 2: Create Cloudflare Account & Get Credentials (2 minutes)

### 2.1 Go to Cloudflare

```bash
# Open in browser:
https://dash.cloudflare.com
```

### 2.2 Sign Up / Log In

### 2.3 Get Your Credentials

```
1. Go to "Overview" (sidebar)
2. Find "Account ID" - copy it
3. Go to "My Profile" (top right) → "API Tokens"
4. Click "Create Token"
   - Select "Edit Cloudflare Workers"
   - Click "Use template"
   - Review permissions
   - Click "Create Token"
5. Copy the token value
6. You now have:
   - Account ID: xxx
   - API Token: xxx
```

---

## ⏱️ Step 3: Set Up Environment Variables (1 minute)

### 3.1 Create Cloud Env File

```bash
cd /home/user/gift-top-up

# Copy template
cp .env.cloud.example .env.cloud

# Edit with your credentials
# On Mac: nano .env.cloud
# On Windows: notepad .env.cloud
```

### 3.2 Fill in Values

```env
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...

CLOUDFLARE_API_TOKEN=xxx
CLOUDFLARE_ACCOUNT_ID=xxx

JWT_SECRET=your-secret-key-here
CORS_ORIGIN=https://tilly-app.pages.dev
EXPO_PUBLIC_API_URL=https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev/api/v1
```

### 3.3 Save File

---

## ⏱️ Step 4: Connect GitHub to Cloudflare Pages (2 minutes)

### 4.1 Go to Cloudflare Pages

```bash
# Open in browser:
https://dash.cloudflare.com
# Sidebar: Pages
```

### 4.2 Create New Project

```
1. Click "Create a project"
2. Click "Connect to Git"
3. Authorize GitHub when prompted
4. Select your repository: alltvfree/gift-top-up
5. Choose branch: deployment/supabase-cloudflare-pages
```

### 4.3 Configure Build Settings

```
Build command: cd frontend && npm install && npm run build
Build output directory: frontend/.expo/web
Root directory: (leave empty)
```

### 4.4 Set Environment Variables

```
Add these in Cloudflare Pages settings:

EXPO_PUBLIC_API_URL = https://tilly-api.YOUR_ACCOUNT.workers.dev/api/v1
EXPO_PUBLIC_APP_NAME = Tilly
EXPO_PUBLIC_VERSION = 0.1.0
```

### 4.5 Deploy

```
Click "Save and Deploy"
Wait 2-3 minutes...
Your frontend is live at: https://tilly-app.pages.dev
```

---

## ⏱️ Step 5: Deploy Backend to Cloudflare Workers (2 minutes)

### 5.1 Install Wrangler CLI

```bash
npm install -g wrangler
```

### 5.2 Authenticate

```bash
wrangler login
# Browser window will open
# Click "Allow" to authorize
```

### 5.3 Deploy Backend

```bash
cd backend
wrangler deploy --env production
```

### 5.4 Wait for Deployment

```
Your backend is now live at:
https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev
```

---

## ✅ Step 6: Verify Everything Works (1 minute)

### 6.1 Test Backend Health

```bash
# Replace YOUR_ACCOUNT with your actual account
curl https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev/health
```

Should return:
```json
{"status":"OK","timestamp":"2024-...","uptime":...}
```

### 6.2 Test Frontend

```bash
# Open in browser:
https://tilly-app.pages.dev
```

Should load the login screen ✓

### 6.3 Test API Connection

```bash
# From frontend, try to login/register
# Check console (F12) for errors
# Should see API calls to your backend
```

---

## 🎉 You're Live!

Your app is now deployed to the cloud:

```
📱 Frontend:  https://tilly-app.pages.dev
⚙️  Backend:   https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev
🗄️  Database: Supabase
```

---

## 📊 Monitoring & Debugging

### View Backend Logs

```bash
wrangler tail
```

### Check Supabase

```bash
# Go to:
https://app.supabase.com/project/YOUR_PROJECT_ID

# View:
- Tables and data
- Logs
- Usage
```

### Monitor Cloudflare

```bash
# Go to:
https://dash.cloudflare.com/pages

# View:
- Deployments
- Build logs
- Analytics
```

---

## 🔄 Update Your App

### When you make changes:

```bash
# Commit changes
git add .
git commit -m "feat: your changes"

# Push to cloud branch
git push origin deployment/supabase-cloudflare-pages
```

**Automatic deployment happens! ✨**

- Frontend redeploys automatically (Cloudflare Pages)
- Backend redeploys automatically (GitHub Actions + Wrangler)

---

## 🆘 Troubleshooting

### Frontend shows 404

```
1. Check build logs in Cloudflare Pages
2. Verify EXPO_PUBLIC_API_URL is correct
3. Check if backend is running
```

### Backend returns errors

```bash
# Check logs
wrangler tail

# Verify environment variables
wrangler env list

# Redeploy
wrangler deploy --env production
```

### Database connection fails

```
1. Verify SUPABASE_URL and keys in .env.cloud
2. Check if database is initialized with schema
3. Verify IP allowlist in Supabase (should be unrestricted)
```

### CORS errors

```typescript
// Edit backend/src/index.ts
app.use(cors({
  origin: [
    'https://tilly-app.pages.dev',
    'https://your-custom-domain.com'
  ]
}));
```

---

## 📚 Full Documentation

For detailed information, see:
- `CLOUD_DEPLOYMENT.md` - Complete setup guide
- `IMPLEMENTATION_GUIDE.md` - How to add features
- `DEVELOPMENT_CHECKLIST.md` - Track progress

---

## 🚀 Next: Implement Features

Now that your app is live, you can:

1. **Test authentication** (register/login)
2. **Add wallet functionality**
3. **Implement telecom services**
4. **Add utility payments**
5. **Collect user feedback**

See `IMPLEMENTATION_GUIDE.md` for step-by-step feature development.

---

## 💡 Tips for Success

1. **Keep secrets safe** - Never commit .env files
2. **Test locally first** - Use local setup for development
3. **Use git branches** - Keep main clean, work on feature branches
4. **Monitor costs** - Check Supabase and Cloudflare dashboards
5. **Gradual rollout** - Test with beta users before full launch

---

**Your Tilly app is now live on the cloud! 🎉**

Questions? Check the documentation or review the logs!

Next: Read `IMPLEMENTATION_GUIDE.md` to add features.
