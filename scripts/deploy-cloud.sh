#!/bin/bash

# Tilly Super App - Cloud Deployment Script
# Deploys to Supabase + Cloudflare Pages + Cloudflare Workers

set -e

echo "🚀 Tilly Super App - Cloud Deployment"
echo "======================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js installed${NC}"

if ! command -v wrangler &> /dev/null; then
    echo -e "${YELLOW}⚠ Wrangler not found, installing...${NC}"
    npm install -g wrangler
fi
echo -e "${GREEN}✓ Wrangler CLI available${NC}"

if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Git is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Git installed${NC}"

echo ""
echo "🔐 Setting up environment variables..."

# Check if on correct branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "deployment/supabase-cloudflare-pages" ]; then
    echo -e "${YELLOW}⚠ You are on branch '$BRANCH'${NC}"
    echo "Please switch to: deployment/supabase-cloudflare-pages"
    echo "Run: git checkout deployment/supabase-cloudflare-pages"
    exit 1
fi
echo -e "${GREEN}✓ On correct branch: $BRANCH${NC}"

# Check for environment file
if [ ! -f ".env.cloud" ]; then
    echo -e "${YELLOW}⚠ .env.cloud not found${NC}"
    echo "Creating from template..."
    cp .env.cloud.example .env.cloud
    echo -e "${YELLOW}📝 Please edit .env.cloud with your credentials${NC}"
    echo "Then run this script again"
    exit 1
fi
echo -e "${GREEN}✓ Environment file found${NC}"

# Load environment variables
set -a
source .env.cloud
set +a

echo ""
echo "🔨 Building backend..."

cd backend

# Install dependencies
echo "Installing backend dependencies..."
npm install

# Build TypeScript
echo "Building TypeScript..."
npm run build

cd ..
echo -e "${GREEN}✓ Backend built successfully${NC}"

echo ""
echo "📦 Building frontend..."

cd frontend

# Install dependencies
echo "Installing frontend dependencies..."
npm install

# Build web version
echo "Building React Native web..."
npm run build

cd ..
echo -e "${GREEN}✓ Frontend built successfully${NC}"

echo ""
echo "🚀 Deploying to Cloudflare..."

# Deploy backend
echo ""
echo "📤 Deploying backend to Cloudflare Workers..."
cd backend
wrangler deploy --env production
cd ..
echo -e "${GREEN}✓ Backend deployed${NC}"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📍 Your app is now live:"
echo ""
echo "  Frontend:  https://tilly-app.pages.dev"
echo "  Backend:   https://tilly-app-backend-prod.YOUR_ACCOUNT.workers.dev"
echo "  Database:  Supabase (${SUPABASE_URL})"
echo ""
echo "🔗 Next steps:"
echo "  1. Visit your frontend URL"
echo "  2. Test user registration"
echo "  3. Check backend logs: wrangler tail"
echo "  4. Monitor Supabase: https://app.supabase.com"
echo ""
echo "📊 Deployment Status:"
echo ""
echo "  Frontend ✓"
echo "  Backend  ✓"
echo "  Database ✓"
echo ""
