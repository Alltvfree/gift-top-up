# Tilly Super App - Development Roadmap

**Vision:** A comprehensive Super App for the Maldives combining digital payments, telecom services, and utility bill payments.

## Project Overview

Tilly is an all-in-one lifestyle and finance application that brings together:
- **Digital Wallet & Payments** (FahiPay-style features)
- **Telecom & Mobile Services** (Faseyha-style features)
- **Utility & Bill Payments** (STELCO, MWA, ISPs, government)

---

## Technology Stack

### Frontend
- **Framework:** Flutter (cross-platform iOS/Android) or React Native
- **Alternative Web:** React.js + TypeScript with Tailwind CSS
- **State Management:** Provider (Flutter) / Redux (React)

### Backend
- **Runtime:** Node.js with Express.js or Go (Golang)
- **Language:** TypeScript/Node.js recommended for rapid development
- **Database:** PostgreSQL (relational data) + Redis (caching/sessions)
- **API:** RESTful API with JWT authentication

### Infrastructure
- **Cloud:** AWS or Azure
- **Containerization:** Docker
- **CI/CD:** GitHub Actions

---

## Project Structure

```
tilly-app/
├── frontend/                 # Mobile app (Flutter/React Native)
│   ├── lib/                 # Dart/JavaScript source
│   ├── assets/              # Images, fonts, icons
│   └── pubspec.yaml         # Dependencies
├── backend/                 # Node.js/Go server
│   ├── src/
│   │   ├── auth/           # Authentication & KYC
│   │   ├── wallet/         # Digital wallet system
│   │   ├── telecom/        # Telecom integrations
│   │   ├── utilities/      # Utility payments
│   │   └── api/            # External API integrations
│   ├── database/
│   │   ├── migrations/     # Database schema
│   │   └── seeds/          # Initial data
│   └── package.json
├── docs/                    # Documentation
├── docker-compose.yml       # Development environment
└── README.md

```

---

## Development Phases

### Phase 1: Foundation (Weeks 1-2)
- [x] Project setup & tech stack initialization
- [ ] Database schema design
- [ ] API architecture documentation
- [ ] Development environment setup (Docker)

### Phase 2: Backend Core (Weeks 3-6)
- [ ] User authentication system
- [ ] Digital wallet ledger system
- [ ] Payment gateway integrations
- [ ] Telecom API connections
- [ ] Utility payment system

### Phase 3: Frontend Development (Weeks 7-12)
- [ ] App UI/UX design (Figma mockups)
- [ ] Authentication screens
- [ ] Wallet screens
- [ ] Telecom service screens
- [ ] Utility payment screens
- [ ] QR scanner integration

### Phase 4: Testing & Security (Weeks 13-16)
- [ ] Unit tests
- [ ] Integration tests
- [ ] Security audits
- [ ] Penetration testing
- [ ] Performance optimization

### Phase 5: Launch (Week 17+)
- [ ] App Store & Play Store submission
- [ ] Marketing campaigns
- [ ] User onboarding
- [ ] Live monitoring

---

## Core Modules

### 1. Digital Wallet & Payments (FahiPay-style)
**Features:**
- User registration & KYC (eKYC with ID scanning)
- Wallet creation & balance management
- Load money via bank cards/accounts
- P2P transfers (phone number/QR code)
- Merchant payments (QR scanning)
- Transaction history
- Withdrawal to bank accounts

**Technology:**
- Secure wallet ledger system
- Payment gateway API (Visa/Mastercard)
- Bank integration APIs (BML, MAL, SBI)

### 2. Telecom & Mobile Services (Faseyha-style)
**Features:**
- Mobile top-up (Prepaid recharge)
- Data & voice bundles (daily/weekly/monthly)
- Postpaid bill payment
- Usage tracking
- Plan comparison
- Auto-recharge options

**Technology:**
- Telecom provider APIs (Faseyha/Dhiraagu)
- Real-time balance tracking
- Notification system

### 3. Utility & Bill Payments
**Features:**
- Electricity bills (STELCO)
- Water bills (MWA)
- Internet/Broadband bills
- Government payments (fines, passport, transport)
- Bill history
- Payment reminders
- Scheduled payments

**Technology:**
- Utility provider APIs
- Bill aggregation system
- Automated payment processing

---

## Security Requirements

✅ **End-to-end encryption** for all data in transit and at rest
✅ **Authentication:** Biometric (FaceID/Fingerprint) + 2FA
✅ **PCI-DSS Compliance** for card data
✅ **Fraud Detection:** AI-driven transaction monitoring
✅ **Data Protection:** GDPR/local privacy law compliance
✅ **Penetration Testing** before launch

---

## Regulatory Compliance

⚠️ **CRITICAL - Must handle before launch:**
- **MMA License:** Electronic Payment System (EPS) license
- **Telecom Agreements:** API access with Faseyha/Dhiraagu
- **Data Privacy:** Maldivian data protection compliance
- **KYC/AML:** Know Your Customer and Anti-Money Laundering procedures

---

## Team & Responsibilities

- **Backend Lead:** API development, database, integrations
- **Frontend Lead:** Mobile app, UI/UX implementation
- **DevOps:** Infrastructure, CI/CD, deployment
- **QA:** Testing, security audits
- **Legal:** Regulatory compliance, licensing

---

## Key Milestones

| Milestone | Target Date | Status |
|-----------|------------|--------|
| Project Setup Complete | Week 2 | ⏳ In Progress |
| Backend MVP Ready | Week 6 | ⏳ Pending |
| UI Mockups Complete | Week 8 | ⏳ Pending |
| Frontend Alpha | Week 12 | ⏳ Pending |
| Security Audit | Week 15 | ⏳ Pending |
| App Store Submission | Week 17 | ⏳ Pending |
| Public Beta Launch | Week 20 | ⏳ Pending |

---

## Success Metrics

- User acquisition targets
- Transaction volume & frequency
- App rating (target: 4.5+ stars)
- Uptime & performance (99.9% SLA)
- User retention rate
- Security incidents (target: 0)

---

## Next Steps

1. ✅ Finalize tech stack (Node.js + React Native)
2. ⏳ Set up development environment
3. ⏳ Create Figma UI mockups
4. ⏳ Begin backend development
5. ⏳ Implement authentication system
