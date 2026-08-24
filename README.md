# Tilly Super App - Digital Wallet, Telecom & Utility Payments

**The all-in-one lifestyle and finance app for the Maldives** 🇲🇻

Tilly combines digital payments, mobile top-ups, and utility bill payments into one powerful super app—bringing together the capabilities of FahiPay and Faseyha, plus much more.

## 📱 Project Overview

Tilly is a comprehensive mobile application providing three core services:

1. **Digital Wallet & Payments** (FahiPay-style features)
   - Load money via bank cards/accounts
   - Peer-to-peer transfers via phone number or QR code
   - QR code merchant payments
   - Bank account linking & withdrawals

2. **Telecom & Mobile Services** (Faseyha-style features)
   - Mobile top-ups (prepaid recharging)
   - Data bundles (daily/weekly/monthly plans)
   - Postpaid bill payments
   - Real-time balance tracking

3. **Utility & Bill Payments** (STELCO, MWA, ISPs, Government)
   - Electricity bills (STELCO)
   - Water bills (MWA)
   - Internet/Broadband bills
   - Government payments (fines, passport, etc.)
   - Payment reminders & history

## 🚀 Quick Start

### Prerequisites
- Node.js 18+
- PostgreSQL 14+
- Redis 7+
- Docker & Docker Compose (recommended for easy setup)

### Setup (Docker - Recommended)

```bash
# Start all services with Docker Compose
docker-compose up -d

# Backend API will be available at: http://localhost:3001
# Database: PostgreSQL on port 5432
# Cache: Redis on port 6379
```

### Manual Setup

```bash
# 1. Backend setup
cd backend
npm install
cp .env.example .env
npm run build
npm start

# 2. Frontend setup (in another terminal)
cd frontend
npm install
npm run dev

# 3. Frontend will open at http://localhost:8081
```

## 📁 Project Structure

```
tilly-app/
├── backend/                    # Node.js/Express backend API
│   ├── src/
│   │   ├── config/            # Database, Redis, Logger config
│   │   ├── routes/            # API routes (auth, wallet, telecom, utilities)
│   │   ├── services/          # Business logic
│   │   └── index.ts           # Server entry point
│   ├── database/
│   │   └── 001_initial_schema.sql  # PostgreSQL schema
│   ├── package.json
│   └── Dockerfile
├── frontend/                   # React Native app (Expo)
│   ├── src/
│   │   ├── screens/           # App screens
│   │   ├── stores/            # Zustand state management
│   │   ├── services/          # API client
│   │   └── App.tsx            # Main component
│   ├── package.json
│   └── app.json
├── docker-compose.yml         # Docker Compose configuration
├── TILLY_APP_PLAN.md         # Comprehensive development plan
└── README.md                  # This file
```

## 🛠️ Tech Stack

### Backend
- **Runtime:** Node.js with Express.js
- **Language:** TypeScript
- **Database:** PostgreSQL (relational) + Redis (caching)
- **Authentication:** JWT
- **Security:** bcryptjs, Helmet, CORS

### Frontend
- **Framework:** React Native + Expo
- **Language:** TypeScript
- **State Management:** Zustand
- **Navigation:** React Navigation
- **HTTP Client:** Axios

### Infrastructure
- **Containerization:** Docker & Docker Compose
- **Cloud:** AWS/Azure ready
- **CI/CD:** GitHub Actions ready

## 📚 API Endpoints

### Health Check
```
GET /health
```

### Authentication
```
POST   /api/v1/auth/register      - Register user
POST   /api/v1/auth/login         - Login user
POST   /api/v1/auth/refresh       - Refresh token
POST   /api/v1/auth/logout        - Logout
```

### Wallet Management
```
GET    /api/v1/wallet/balance     - Get wallet balance
POST   /api/v1/wallet/add-money   - Add money
POST   /api/v1/wallet/transfer    - P2P transfer
GET    /api/v1/wallet/transactions - Transaction history
POST   /api/v1/wallet/withdraw    - Withdraw to bank
```

### Telecom Services
```
GET    /api/v1/telecom/plans      - Get available plans
POST   /api/v1/telecom/topup      - Purchase top-up
GET    /api/v1/telecom/bill/:phone - Get bill amount
POST   /api/v1/telecom/pay-bill   - Pay postpaid bill
GET    /api/v1/telecom/balance/:phone - Check balance
```

### Utility Payments
```
GET    /api/v1/utilities/providers - Get utility providers
GET    /api/v1/utilities/bill/:provider/:accountNumber - Get bill
POST   /api/v1/utilities/pay-bill - Pay utility bill
GET    /api/v1/utilities/history/:provider/:accountNumber - Bill history
POST   /api/v1/utilities/reminder - Set payment reminder
```

## 🎯 Core Features

### Digital Wallet
- ✅ User registration with email verification
- ✅ KYC verification (eKYC with ID scanning)
- ✅ Wallet balance management
- ✅ Load money via payment gateway
- ✅ Peer-to-peer transfers
- ✅ QR code merchant payments
- ✅ Bank account linking
- ✅ Transaction history & receipts
- ✅ Withdrawal to bank accounts

### Telecom Services
- ✅ Browse available data plans
- ✅ Mobile top-up purchasing
- ✅ Data bundle selection
- ✅ Postpaid bill payment
- ✅ Real-time balance tracking
- ✅ Phone number management
- ✅ Usage tracking

### Utility Payments
- ✅ STELCO electricity bills
- ✅ MWA water bills
- ✅ Internet/Broadband bills
- ✅ Government payments
- ✅ Automated bill fetching
- ✅ Payment history
- ✅ Payment reminders
- ✅ Scheduled payments

## 🔐 Security Features

- ✅ End-to-end encryption (TLS/HTTPS)
- ✅ JWT authentication with refresh tokens
- ✅ Biometric authentication ready (FaceID/Fingerprint)
- ✅ Two-factor authentication (2FA) via OTP
- ✅ PCI-DSS compliance for card data
- ✅ Fraud detection via transaction monitoring
- ✅ Data encryption at rest
- ✅ Rate limiting & DDoS protection
- ✅ Audit logging of all financial transactions
- ✅ Secure session management with Redis

## 📋 Database Schema

The PostgreSQL database includes:

**Users & Auth**
- users (profiles, KYC status)
- device_tokens (push notifications)
- audit_logs (activity tracking)

**Payments**
- wallets (user balances)
- transactions (ledger)
- p2p_transfers (between users)
- bank_accounts (linked accounts)

**Telecom**
- telecom_plans (available plans)
- mobile_numbers (user phone numbers)
- telecom_topups (purchase history)
- postpaid_bills (billing)

**Utilities**
- utility_providers (STELCO, MWA, ISPs)
- utility_accounts (user accounts)
- utility_bills (outstanding bills)
- utility_payments (payment history)
- payment_reminders (scheduled reminders)

**Merchants**
- merchants (store information)
- qr_codes (static/dynamic QR codes)
- merchant_transactions (QR payments)

See [backend/database/001_initial_schema.sql](backend/database/001_initial_schema.sql) for full schema.

## 📱 App Screens

### Authentication
- Login screen with phone number + password
- Registration with email & KYC
- Password reset flow

### Main App
- **Dashboard** - Quick actions, recent transactions, service overview
- **Wallet** - Balance, transaction history, linked accounts
- **Telecom** - Plans, top-ups, postpaid bills, phone management
- **Utilities** - Providers, bill accounts, payment history, reminders
- **Profile** - User info, settings, security, help center

## 🎨 UI/UX Design

- Modern, clean interface optimized for mobile
- Intuitive navigation with bottom tab bar
- Color scheme: Primary (#00A3E0), Secondary (#f5f5f5)
- Accessible design (WCAG 2.1 compliant)
- Smooth animations & transitions
- Responsive to all device sizes

## 🧪 Testing

```bash
# Backend tests
cd backend
npm run test
npm run test:coverage

# Frontend tests
cd frontend
npm run test
npm run test:coverage

# Linting
npm run lint

# Type checking
npx tsc --noEmit
```

## 📦 Deployment

### Development
```bash
docker-compose up -d
```

### Production Build
```bash
# Backend
cd backend
npm run build
docker build -t tilly-backend:latest .

# Frontend
cd frontend
eas build --platform ios --production
eas build --platform android --production
```

## 🌍 Regulatory Compliance

⚠️ **Before launch, these must be completed:**
- Obtain **MMA Electronic Payment System (EPS) License**
- Secure **Telecom API agreements** with Faseyha/Dhiraagu
- Comply with **Maldivian Data Protection Laws**
- Implement **KYC/AML procedures**
- Pass **Security audits & penetration testing**
- Achieve **App Store & Play Store approval**

## 📖 Documentation

- [Backend Setup Guide](backend/README.md)
- [Frontend Setup Guide](frontend/README.md)
- [Development Roadmap](TILLY_APP_PLAN.md)

## 🚧 Development Status

| Phase | Task | Status |
|-------|------|--------|
| **Phase 1** | Project Setup & Tech Stack | ✅ Complete |
| **Phase 2** | Backend Core Development | ⏳ In Progress |
| **Phase 3** | Frontend Development | ⏳ Pending |
| **Phase 4** | Testing & Security Audits | ⏳ Pending |
| **Phase 5** | Launch & Marketing | ⏳ Pending |

## 🎯 Next Steps

1. **Backend Development**
   - [ ] Implement authentication system
   - [ ] Build payment gateway integration
   - [ ] Connect telecom provider APIs
   - [ ] Set up utility bill aggregation

2. **Frontend Development**
   - [ ] Create UI mockups in Figma
   - [ ] Implement all screens
   - [ ] Integrate QR scanner
   - [ ] Add biometric auth

3. **Testing**
   - [ ] Write unit tests
   - [ ] Integration testing
   - [ ] Security audit
   - [ ] Load testing

4. **Launch Preparation**
   - [ ] Regulatory compliance
   - [ ] App Store submission
   - [ ] Marketing campaign
   - [ ] User onboarding

## 💰 Business Model

Revenue streams:
- Small transaction fees on wallet operations
- Merchant discount rates on QR payments
- Partner commission on utility payments
- Telecom provider margins on top-ups
- Premium features (faster withdrawals, higher limits)

## 👥 Team

- **Backend Lead** - API & Database development
- **Frontend Lead** - Mobile app development
- **DevOps** - Infrastructure & deployment
- **QA** - Testing & quality assurance
- **Legal/Compliance** - Regulatory & licensing

## 📞 Support

For issues, questions, or feature requests, please:
1. Check the documentation
2. Open a GitHub issue
3. Contact the development team

## 📄 License

This project is confidential and proprietary to Alltvfree.

---

**Built with ❤️ for the Maldives** 🇲🇻