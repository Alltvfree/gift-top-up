# Tilly Super App - Cloud Deployment Guide

Deploy to **Supabase** (Database) + **Cloudflare Pages** (Frontend) + **Cloudflare Workers** (Backend)

## 🚀 Quick Overview

| Component | Service | Benefits |
|-----------|---------|----------|
| **Database** | Supabase | PostgreSQL, Auth, Realtime |
| **Frontend** | Cloudflare Pages | Free, fast, auto-deploy |
| **Backend** | Cloudflare Workers | Serverless, always free tier |
| **Total Cost** | ~$25-40/month | Scalable pay-as-you-go |

---

## 📋 Prerequisites

1. **Supabase Account** - https://supabase.com (free tier available)
2. **Cloudflare Account** - https://dash.cloudflare.com (free)
3. **GitHub Account** - For automatic deployments
4. **Node.js 18+** - For local development

---

## 🔧 Step 1: Set Up Supabase

### 1.1 Create Supabase Project

```bash
# Go to https://supabase.com
# Sign up / Log in
# Click "New Project"

Project Details:
- Name: tilly-app
- Database Password: [Create strong password, save it!]
- Region: Choose closest to your users
- Plan: Free (starts here)
```

### 1.2 Get Connection Details

After project creation:

```
1. Go to Project Settings → Database
2. Copy connection string (looks like):
   postgresql://postgres:PASSWORD@db.PROJECT_ID.supabase.co:5432/postgres

3. Go to Project Settings → API
4. Copy these:
   - Project URL: https://PROJECT_ID.supabase.co
   - Anon Key: eyJhbGci...
   - Service Role Key: eyJhbGci...
```

### 1.3 Initialize Database Schema

```bash
# Option A: Using SQL Editor in Supabase Dashboard
# 1. Go to SQL Editor
# 2. Click "New Query"
# 3. Paste content from: backend/database/001_initial_schema.sql
# 4. Click "RUN"

# Option B: Using psql command line
psql postgresql://postgres:PASSWORD@db.PROJECT_ID.supabase.co:5432/postgres \
  -f backend/database/001_initial_schema.sql
```

### 1.4 Enable Authentication (Optional)

```
1. Go to Authentication → Providers
2. Enable Email/Password
3. Go to Authentication → URL Configuration
4. Add your Cloudflare Pages domain
```

---

## 🌐 Step 2: Deploy Frontend to Cloudflare Pages

### 2.1 Prepare Frontend

Create build configuration:

```bash
# Copy this to: frontend/.vercelignore (or create cloudflare config)
node_modules
.expo
.env.local
```

### 2.2 Connect GitHub Repository

```
1. Go to https://dash.cloudflare.com
2. Go to Pages
3. Click "Create a project"
4. Select "Connect to Git"
5. Authorize GitHub
6. Select: alltvfree/gift-top-up
7. Choose branch: deployment/supabase-cloudflare-pages
```

### 2.3 Configure Build Settings

```
Production branch: deployment/supabase-cloudflare-pages
Framework: Expo (or "None" - we'll use custom)
Build command: cd frontend && npm install && npm run build
Build output directory: frontend/.expo/web
Environment variables: (see below)
```

### 2.4 Add Environment Variables

In Cloudflare Pages project settings, add:

```
EXPO_PUBLIC_API_URL=https://tilly-api.YOUR_DOMAIN.workers.dev/api/v1
EXPO_PUBLIC_APP_NAME=Tilly
EXPO_PUBLIC_VERSION=0.1.0
```

### 2.5 Deploy

```bash
# Push to deployment branch to trigger auto-deploy
git push origin deployment/supabase-cloudflare-pages
```

**Your frontend is now live at:** `https://your-project.pages.dev`

---

## ⚙️ Step 3: Deploy Backend to Cloudflare Workers

### 3.1 Install Wrangler CLI

```bash
npm install -g wrangler
```

### 3.2 Create wrangler.toml

```toml
# backend/wrangler.toml
name = "tilly-app-backend"
type = "javascript"
account_id = "YOUR_ACCOUNT_ID"
workers_dev = true
main = "src/index.ts"
compatibility_date = "2024-01-01"

[env.production]
name = "tilly-app-backend-prod"

[[r2_buckets]]
binding = "BUCKET"
bucket_name = "tilly-uploads"

[[d1_databases]]
binding = "DB"
database_name = "tilly"
database_id = "YOUR_DATABASE_ID"

[env.production.vars]
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR_ANON_KEY"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVICE_ROLE_KEY"
JWT_SECRET = "your-super-secret-key-change-in-production"
CORS_ORIGIN = "https://your-project.pages.dev"
```

### 3.3 Install Supabase Client

```bash
cd backend
npm install @supabase/supabase-js
```

### 3.4 Update Backend to Use Supabase

Replace `backend/src/config/database.ts`:

```typescript
// backend/src/config/database.ts
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.SUPABASE_URL || '';
const supabaseKey = process.env.SUPABASE_ANON_KEY || '';

export const supabase = createClient(supabaseUrl, supabaseKey);

export async function initializeDatabase(): Promise<void> {
  try {
    const { data, error } = await supabase
      .from('users')
      .select('count', { count: 'exact' })
      .limit(1);
    
    if (error) throw error;
    console.log('✓ Database connected');
  } catch (error) {
    console.error('Failed to connect to database:', error);
    throw error;
  }
}

export async function query(text: string, params?: any[]): Promise<any> {
  // For Supabase, you'd use the query builder or RPC functions
  // This is a simplified version
  try {
    const result = await supabase.rpc('execute_query', {
      query_text: text,
      query_params: params
    });
    return result;
  } catch (error) {
    console.error('Database query error:', error);
    throw error;
  }
}

export async function getClient() {
  return supabase;
}
```

### 3.5 Update Main Server for Workers

Modify `backend/src/index.ts`:

```typescript
// backend/src/index.ts
import express from 'express';
import helmet from 'helmet';
import cors from 'cors';

const app = express();

// Middleware
app.use(helmet());
app.use(cors({
  origin: process.env.CORS_ORIGIN || '*',
  credentials: true,
}));
app.use(express.json());

// Health check
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'OK',
    timestamp: new Date().toISOString(),
  });
});

// Routes
app.use('/api/v1/auth', require('./routes/auth').default);
app.use('/api/v1/wallet', require('./routes/wallet').default);
app.use('/api/v1/telecom', require('./routes/telecom').default);
app.use('/api/v1/utilities', require('./routes/utilities').default);

// Error handling
app.use((err: any, req: express.Request, res: express.Response, next: express.NextFunction) => {
  console.error('Error:', err);
  res.status(err.status || 500).json({
    error: {
      message: err.message || 'Internal Server Error',
      status: err.status || 500,
    },
  });
});

// Export for Cloudflare Workers
export default {
  fetch: app,
  scheduled: async (event: any) => {
    // Handle scheduled tasks if needed
  },
};
```

### 3.6 Deploy to Cloudflare Workers

```bash
cd backend

# Authenticate with Cloudflare
wrangler login

# Deploy
wrangler deploy

# View logs
wrangler tail
```

**Your backend is now live at:** `https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev`

---

## 🔐 Step 4: Configure Environment Variables

### Create `.env.production` for Backend

```env
# backend/.env.production
NODE_ENV=production
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
JWT_SECRET=your-production-jwt-secret-change-this
CORS_ORIGIN=https://your-project.pages.dev
LOG_LEVEL=info
```

### Create `.env.production` for Frontend

```env
# frontend/.env.production
EXPO_PUBLIC_API_URL=https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev/api/v1
EXPO_PUBLIC_APP_NAME=Tilly
EXPO_PUBLIC_VERSION=0.1.0
```

---

## 🔗 Step 5: Connect Everything

### Update Frontend API Client

```typescript
// frontend/src/services/api.ts
const API_BASE_URL = 
  process.env.EXPO_PUBLIC_API_URL || 
  'http://localhost:3001/api/v1';

// The rest of the code stays the same
```

### Test the Connection

```bash
# Frontend
curl https://your-project.pages.dev

# Backend health check
curl https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev/health

# Backend API
curl https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev/api/v1/wallet/balance
```

---

## 📊 Cost Estimate

### Supabase (Free Tier Included)
- Database: $0 (free up to 500MB)
- Auth: $0 (free up to 100,000 users)
- Storage: $0 (free 1GB)
- Beyond free:
  - Database: Pay per row ($0.0001 per row)
  - Storage: $0.06 per GB

### Cloudflare
- Pages: $0 (free for unlimited projects)
- Workers: $0 (free up to 100,000 requests/day)
- Beyond free:
  - Workers: $0.50 per million requests
  - KV Storage: $0.50 per million read operations

**Estimated Cost: $5-40/month depending on usage**

---

## 🚀 Auto-Deployment Setup

### Frontend Auto-Deploy

```yaml
# Automatic when you push to deployment/supabase-cloudflare-pages
git push origin deployment/supabase-cloudflare-pages
# → Cloudflare Pages automatically builds and deploys
```

### Backend Auto-Deploy

Option 1: GitHub Actions (Recommended)

```yaml
# .github/workflows/deploy-backend.yml
name: Deploy Backend to Cloudflare Workers

on:
  push:
    branches: [deployment/supabase-cloudflare-pages]
    paths:
      - 'backend/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - run: npm install -g wrangler
      - run: cd backend && npm install
      - run: cd backend && wrangler deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
```

Setup secrets in GitHub:
```
1. Go to Repository Settings → Secrets
2. Add:
   - CLOUDFLARE_API_TOKEN
   - SUPABASE_URL
   - SUPABASE_ANON_KEY
   - SUPABASE_SERVICE_ROLE_KEY
```

---

## 🐛 Troubleshooting

### Frontend Not Loading

```bash
# Check build logs in Cloudflare Pages
# Ensure EXPO_PUBLIC_API_URL is correct
# Check CORS settings on backend
```

### Backend Returning 404

```bash
# Check wrangler.toml configuration
# Verify environment variables are set
# Check function routes are exported correctly
```

### Database Connection Failed

```bash
# Verify Supabase URL and keys
# Check database is initialized with schema
# Test connection: 
curl https://tilly-app-backend.workers.dev/health
```

### CORS Errors

```typescript
// Update CORS in backend/src/index.ts
app.use(cors({
  origin: [
    'https://your-project.pages.dev',
    'http://localhost:3000',  // for local development
    'http://localhost:8081',  // for Expo local
  ],
  credentials: true,
}));
```

---

## 📝 Deployment Checklist

### Before Deploying

- [ ] Supabase project created
- [ ] Database schema initialized
- [ ] Environment variables saved securely
- [ ] GitHub repository connected to Cloudflare
- [ ] Wrangler CLI installed and authenticated
- [ ] .env files created locally

### During Deployment

- [ ] Frontend builds successfully
- [ ] Backend deploys to Workers
- [ ] Health check passes
- [ ] API endpoints respond
- [ ] Frontend connects to backend
- [ ] Authentication works

### After Deployment

- [ ] Test user registration
- [ ] Test user login
- [ ] Test wallet endpoints
- [ ] Test with real data
- [ ] Monitor error logs
- [ ] Set up alerts

---

## 🔄 Local Development with Cloud Services

You can develop locally while using cloud services:

```bash
# backend/.env.local
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
NODE_ENV=development

# frontend/.env.local
EXPO_PUBLIC_API_URL=http://localhost:3001/api/v1
```

```bash
# Terminal 1: Backend
cd backend
npm install
npm run dev

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

---

## 📚 Useful Links

- [Supabase Docs](https://supabase.com/docs)
- [Cloudflare Pages Docs](https://developers.cloudflare.com/pages/)
- [Cloudflare Workers Docs](https://developers.cloudflare.com/workers/)
- [Supabase JavaScript Client](https://supabase.com/docs/reference/javascript)
- [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/)

---

## 🎯 Next Steps

1. ✅ Create Supabase project
2. ✅ Initialize database
3. ✅ Deploy frontend to Cloudflare Pages
4. ✅ Deploy backend to Cloudflare Workers
5. ✅ Test all endpoints
6. ⏳ Implement authentication
7. ⏳ Implement features
8. ⏳ Monitor and optimize

---

**Happy cloud deployment!** 🚀
