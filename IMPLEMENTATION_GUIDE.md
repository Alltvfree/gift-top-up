# Tilly Super App - Implementation Guide

This guide walks you through implementing the features in Tilly Super App, starting from the foundation that's already been set up.

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Phase 2: Backend Development](#phase-2-backend-development)
3. [Phase 3: Frontend Development](#phase-3-frontend-development)
4. [Testing & Deployment](#testing--deployment)

---

## Getting Started

### Prerequisites Checklist
- [ ] Node.js 18+ installed
- [ ] PostgreSQL 14+ installed
- [ ] Redis 7+ installed
- [ ] Docker & Docker Compose (optional but recommended)
- [ ] Postman or Insomnia for API testing
- [ ] GitHub account with repo access

### Initial Setup

#### 1. Clone and Setup Repository
```bash
# Clone the repository
git clone https://github.com/alltvfree/gift-top-up.git
cd gift-top-up

# Switch to development branch
git checkout claude/app-build-qyq3iv

# Create feature branches from here
git checkout -b feature/authentication
```

#### 2. Start Services (Docker Method - Easiest)
```bash
# From project root
docker-compose up -d

# Verify services
docker ps

# Check logs
docker-compose logs -f backend
```

#### 3. Verify Setup
```bash
# Test backend health
curl http://localhost:3001/health

# You should see:
# {"status":"OK","timestamp":"2026-08-24T...","uptime":...}
```

---

## Phase 2: Backend Development

The backend is the foundation for everything. Implement in this order:

### Week 1-2: Authentication System

#### 1. Create User Model & Service
```bash
# Create new files
backend/src/models/User.ts
backend/src/services/AuthService.ts
backend/src/middleware/authMiddleware.ts
backend/src/types/index.ts
```

#### 2. Implement User Registration (backend/src/services/AuthService.ts)
```typescript
import bcryptjs from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { query } from '../config/database';
import { v4 as uuidv4 } from 'uuid';

export class AuthService {
  async registerUser(data: {
    firstName: string;
    lastName: string;
    phoneNumber: string;
    email: string;
    password: string;
  }) {
    // Hash password
    const passwordHash = await bcryptjs.hash(data.password, 10);
    
    // Create user in database
    const userId = uuidv4();
    const result = await query(
      `INSERT INTO users (id, phone_number, email, first_name, last_name, password_hash)
       VALUES ($1, $2, $3, $4, $5, $6)
       RETURNING id, phone_number, email, first_name, last_name`,
      [userId, data.phoneNumber, data.email, data.firstName, data.lastName, passwordHash]
    );
    
    // Create wallet for user
    await query(
      `INSERT INTO wallets (id, user_id, balance, currency)
       VALUES ($1, $2, $3, $4)`,
      [uuidv4(), userId, 0, 'MVR']
    );
    
    // Generate token
    const token = this.generateToken(result.rows[0]);
    
    return {
      user: result.rows[0],
      token
    };
  }

  async loginUser(phoneNumber: string, password: string) {
    const result = await query(
      'SELECT * FROM users WHERE phone_number = $1',
      [phoneNumber]
    );
    
    if (result.rows.length === 0) {
      throw new Error('User not found');
    }
    
    const user = result.rows[0];
    const validPassword = await bcryptjs.compare(password, user.password_hash);
    
    if (!validPassword) {
      throw new Error('Invalid password');
    }
    
    const token = this.generateToken(user);
    return { user, token };
  }

  private generateToken(user: any) {
    return jwt.sign(
      { id: user.id, phoneNumber: user.phone_number },
      process.env.JWT_SECRET || 'secret',
      { expiresIn: process.env.JWT_EXPIRY || '7d' }
    );
  }
}
```

#### 3. Update Auth Routes (backend/src/routes/auth.ts)
```typescript
import express from 'express';
import { AuthService } from '../services/AuthService';
import { logger } from '../config/logger';

const router = express.Router();
const authService = new AuthService();

router.post('/register', async (req, res, next) => {
  try {
    const result = await authService.registerUser(req.body);
    res.status(201).json(result);
  } catch (error) {
    next(error);
  }
});

router.post('/login', async (req, res, next) => {
  try {
    const { phoneNumber, password } = req.body;
    const result = await authService.loginUser(phoneNumber, password);
    res.status(200).json(result);
  } catch (error) {
    next(error);
  }
});

export default router;
```

#### 4. Create Auth Middleware
```typescript
// backend/src/middleware/authMiddleware.ts
import jwt from 'jsonwebtoken';

export function authMiddleware(req: any, res: any, next: any) {
  const token = req.headers.authorization?.split(' ')[1];
  
  if (!token) {
    return res.status(401).json({ error: 'No token provided' });
  }
  
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET || 'secret');
    req.user = decoded;
    next();
  } catch (error) {
    res.status(401).json({ error: 'Invalid token' });
  }
}
```

### Week 3-4: Digital Wallet System

#### 1. Create Wallet Service
```bash
# Create file
backend/src/services/WalletService.ts
```

#### 2. Implement Wallet Operations
```typescript
// Key methods to implement:
// - getBalance(userId)
// - addMoney(userId, amount, paymentMethod)
// - transfer(fromUserId, toPhoneNumber, amount)
// - withdrawToBank(userId, bankAccountId, amount)
// - getTransactionHistory(userId, limit, offset)
```

#### 3. Update Wallet Routes
```bash
# Implement in: backend/src/routes/wallet.ts
# POST   /wallet/add-money
# GET    /wallet/balance
# POST   /wallet/transfer
# GET    /wallet/transactions
# POST   /wallet/withdraw
```

### Week 5-6: External API Integrations

#### 1. Payment Gateway Integration
```bash
# Create file
backend/src/services/PaymentGatewayService.ts

# Implement methods for:
# - Visa/Mastercard processing
# - Local bank account linking
# - Payment confirmation webhooks
```

#### 2. Telecom Provider Integration
```bash
# Create file
backend/src/services/TelecomService.ts

# Implement methods for:
# - Faseyha/Dhiraagu API calls
# - Top-up processing
# - Bill fetching
# - Balance checking
```

#### 3. Utility Provider Integration
```bash
# Create file
backend/src/services/UtilityService.ts

# Implement methods for:
# - STELCO API integration
# - MWA API integration
# - ISP API integration
# - Bill aggregation
```

### Testing the Backend

#### 1. Create Test File
```bash
touch backend/tests/auth.test.ts
```

#### 2. Write Unit Tests
```typescript
import { describe, it, expect } from 'vitest';
import { AuthService } from '../src/services/AuthService';

describe('AuthService', () => {
  it('should register a new user', async () => {
    const authService = new AuthService();
    const result = await authService.registerUser({
      firstName: 'John',
      lastName: 'Doe',
      phoneNumber: '+96079123456',
      email: 'john@example.com',
      password: 'secure123'
    });
    
    expect(result.user).toBeDefined();
    expect(result.token).toBeDefined();
  });
});
```

#### 3. Run Tests
```bash
cd backend
npm run test
npm run test:coverage
```

---

## Phase 3: Frontend Development

The frontend connects users to the backend services.

### Week 7-8: UI Mockups & Design

#### 1. Create Figma Mockups
- [ ] Create Figma project for Tilly
- [ ] Design all 7 screens
- [ ] Create component library
- [ ] Get design approval

#### 2. Key Screens to Design
1. **Authentication**
   - Login screen
   - Registration screen
   - Password reset

2. **Dashboard**
   - Wallet overview
   - Quick actions
   - Recent transactions
   - Service shortcuts

3. **Wallet**
   - Balance display
   - Transaction list
   - Add money flow
   - Withdrawal flow

4. **Telecom**
   - Browse plans
   - Select phone number
   - Purchase flow
   - Bill payment

5. **Utilities**
   - Provider selection
   - Account management
   - Bill viewing
   - Payment flow

6. **Profile**
   - User information
   - Settings
   - Security options
   - Logout

### Week 9-12: Frontend Implementation

#### 1. Implement Login Flow
```bash
# Update files:
# frontend/src/screens/auth/LoginScreen.tsx
# frontend/src/screens/auth/RegisterScreen.tsx

# Key implementation:
# - Form validation
# - API integration
# - Error handling
# - Token storage
# - Navigation after login
```

#### 2. Implement Wallet Screens
```bash
# Update files:
# frontend/src/screens/wallet/WalletScreen.tsx
# frontend/src/screens/wallet/AddMoneyScreen.tsx
# frontend/src/screens/wallet/TransferScreen.tsx

# Key features:
# - Display balance
# - Transaction history
# - Add money dialog
# - Transfer form
# - Error handling
```

#### 3. Implement Telecom Screens
```bash
# Create files:
# frontend/src/screens/telecom/PlansScreen.tsx
# frontend/src/screens/telecom/TopupScreen.tsx
# frontend/src/screens/telecom/BillPaymentScreen.tsx

# Key features:
# - Browse plans
# - Select phone number
# - Purchase flow
# - Payment confirmation
```

#### 4. Implement Utilities Screens
```bash
# Create files:
# frontend/src/screens/utilities/ProvidersScreen.tsx
# frontend/src/screens/utilities/BillsScreen.tsx
# frontend/src/screens/utilities/PaymentScreen.tsx

# Key features:
# - Provider list
# - Account management
# - Bill viewing
# - Payment processing
```

#### 5. Implement QR Code Scanner
```bash
# Install dependency
npm install react-native-qrcode-scanner react-native-camera

# Create component
# frontend/src/components/QRScanner.tsx

# Integrate with payment flow
# When QR scanned → process payment
```

#### 6. Implement Biometric Auth (Optional)
```bash
# Install dependency
npm install expo-local-authentication

# Update LoginScreen
# Add fingerprint/face ID option
# Fallback to password if unavailable
```

---

## Testing & Deployment

### Week 13-14: Testing

#### 1. Frontend Testing
```bash
cd frontend
npm run test

# Create test files:
# frontend/tests/screens/LoginScreen.test.tsx
# frontend/tests/screens/WalletScreen.test.tsx
# frontend/tests/services/api.test.ts
```

#### 2. Integration Testing
```bash
# Test entire flows:
# 1. User registration → login → wallet access
# 2. Add money → P2P transfer
# 3. Select telecom plan → purchase
# 4. View utility bill → pay bill
```

#### 3. API Testing
```bash
# Use Postman/Insomnia to test:
# - All auth endpoints
# - All wallet endpoints
# - All telecom endpoints
# - All utility endpoints

# Test error cases:
# - Invalid credentials
# - Insufficient balance
# - Network errors
# - Rate limiting
```

### Week 15-16: Security & Performance

#### 1. Security Audit
```bash
# Review:
# - JWT token handling
# - Password hashing
# - Data encryption
# - API authentication
# - CORS configuration
# - Rate limiting
```

#### 2. Penetration Testing
- [ ] Hire ethical hackers
- [ ] Test for vulnerabilities
- [ ] Fix any issues found
- [ ] Get security certification

#### 3. Performance Optimization
```bash
# Backend:
# - Add database indexes
# - Optimize queries
# - Cache frequently accessed data
# - Enable compression

# Frontend:
# - Code splitting
# - Lazy loading
# - Image optimization
# - Remove unused dependencies
```

### Week 17+: Launch Preparation

#### 1. Regulatory Compliance
- [ ] MMA Electronic Payment System (EPS) License
- [ ] Telecom API agreements with Faseyha/Dhiraagu
- [ ] Data protection compliance
- [ ] KYC/AML procedures

#### 2. App Store Submission
```bash
# iOS
eas build --platform ios --production
eas submit --platform ios

# Android
eas build --platform android --production
eas submit --platform android
```

#### 3. Beta Testing
- [ ] Internal testing team
- [ ] Beta release on TestFlight (iOS) & Google Play (Android)
- [ ] Gather feedback
- [ ] Fix issues

#### 4. Marketing & Launch
- [ ] Create marketing materials
- [ ] Launch PR campaign
- [ ] Promotional offers
- [ ] User onboarding tutorials

---

## Development Workflow

### Daily Development Process

1. **Start of Day**
   ```bash
   git pull origin claude/app-build-qyq3iv
   git checkout -b feature/your-feature
   ```

2. **During Development**
   ```bash
   # Keep backend running
   cd backend && npm run dev
   
   # Keep frontend running (in another terminal)
   cd frontend && npm run dev
   
   # Test API calls
   # Use Postman or curl
   curl -X POST http://localhost:3001/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"phoneNumber":"+96079123456","password":"secure123"}'
   ```

3. **Commit Your Work**
   ```bash
   git add .
   git commit -m "feat: Implement authentication system
   
   - Add user registration endpoint
   - Add user login endpoint
   - Implement JWT token generation
   - Add auth middleware
   - Hash passwords with bcryptjs"
   ```

4. **End of Day**
   ```bash
   git push origin feature/your-feature
   ```

### Testing Before Commit

```bash
# Backend
cd backend
npm run lint
npm run test

# Frontend
cd frontend
npm run lint
npm run test

# Type checking
npx tsc --noEmit
```

---

## Debugging Tips

### Backend Debugging

#### Check Database
```bash
# Connect to PostgreSQL
psql -U tilly_user -d tilly_app -h localhost

# View users
SELECT * FROM users;

# View wallets
SELECT * FROM wallets;

# View transactions
SELECT * FROM transactions;
```

#### Check Logs
```bash
# View backend logs
docker-compose logs -f backend

# View database logs
docker-compose logs -f postgres

# View Redis logs
docker-compose logs -f redis
```

#### API Testing
```bash
# Using curl
curl -X GET http://localhost:3001/api/v1/wallet/balance \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Using Postman
# 1. Copy JWT from login response
# 2. Paste in Authorization header (Bearer token)
# 3. Send request
```

### Frontend Debugging

#### React Native Debugger
```bash
# Press 'd' in Expo CLI to open debugger
# Check console logs
# Inspect component state
# Network tab for API calls
```

#### View Device Logs
```bash
expo logs
```

#### Check Network Requests
```bash
# In code, add logging to apiClient
// frontend/src/services/api.ts
this.client.interceptors.response.use(
  (response) => {
    console.log('API Response:', response);
    return response;
  }
);
```

---

## Common Issues & Solutions

### Issue: Database Connection Error
```
Error: connect ECONNREFUSED 127.0.0.1:5432
```
**Solution:**
```bash
# Check if PostgreSQL is running
docker ps | grep postgres

# If not running, start services
docker-compose up -d postgres
```

### Issue: Port Already in Use
```
Error: listen EADDRINUSE: address already in use :::3001
```
**Solution:**
```bash
# Kill process using port 3001
lsof -i :3001
kill -9 <PID>

# Or use different port in .env
PORT=3002
```

### Issue: API Endpoint Not Found
```
Error: Cannot POST /api/v1/auth/register
```
**Solution:**
- Check that route is exported in main server file
- Verify route path matches frontend call
- Check for typos in route definition

### Issue: JWT Token Invalid
```
Error: Invalid token
```
**Solution:**
- Make sure JWT_SECRET is same in .env
- Check token expiration time
- Refresh token if expired

---

## Useful Commands

```bash
# Backend commands
cd backend
npm install              # Install dependencies
npm run dev             # Start development server
npm run build           # Build TypeScript
npm run test            # Run tests
npm run lint            # Check code style
npm run format          # Auto-format code
npm start               # Start production server

# Frontend commands
cd frontend
npm install             # Install dependencies
npm run dev             # Start Expo development
npm run web             # Start web version
npm run test            # Run tests
npm run lint            # Check code style
npm run format          # Auto-format code

# Docker commands
docker-compose up -d    # Start all services
docker-compose down     # Stop all services
docker-compose logs -f  # View logs
docker-compose ps       # View running containers

# Database commands
psql -U tilly_user -d tilly_app -h localhost  # Connect to DB
npm run db:migrate      # Run migrations
npm run db:seed         # Seed test data
```

---

## Resources

- [Express.js Docs](https://expressjs.com)
- [React Native Docs](https://reactnative.dev)
- [PostgreSQL Docs](https://www.postgresql.org/docs)
- [JWT.io](https://jwt.io)
- [Expo Docs](https://docs.expo.dev)
- [React Navigation](https://reactnavigation.org)

---

## Next: Specific Implementation Tasks

Choose a feature and start implementing! Here's the recommended order:

1. **Authentication** (highest priority)
   - User registration
   - User login
   - Token management
   - Protected routes

2. **Wallet Core**
   - Get balance
   - View transactions
   - Add money
   - Transfer to other users

3. **Telecom Services**
   - Browse plans
   - Purchase top-ups
   - View postpaid bills
   - Pay bills

4. **Utility Payments**
   - List providers
   - Add utility accounts
   - View bills
   - Make payments

5. **Advanced Features**
   - QR code scanning
   - Biometric authentication
   - Push notifications
   - Analytics

---

Good luck! 🚀 Start with authentication, it's the foundation for everything else.
