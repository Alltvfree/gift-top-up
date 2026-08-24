# Tilly Super App - Backend API

A comprehensive backend API for the Tilly Super App, providing digital wallet, telecom, and utility payment services for the Maldives market.

## Quick Start

### Prerequisites
- Node.js 18+
- PostgreSQL 14+
- Redis 7+
- Docker & Docker Compose (optional)

### Installation

#### Option 1: Using Docker Compose (Recommended)

```bash
# From the project root
docker-compose up -d

# Backend will be available at http://localhost:3001
```

#### Option 2: Manual Setup

1. **Install dependencies:**
   ```bash
   cd backend
   npm install
   ```

2. **Set up PostgreSQL:**
   ```bash
   # Create database and user
   createdb tilly_app
   createuser tilly_user -P  # Enter password when prompted
   ```

3. **Initialize database schema:**
   ```bash
   psql -U tilly_user -d tilly_app -f database/001_initial_schema.sql
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Start Redis:**
   ```bash
   redis-server
   ```

6. **Start the backend:**
   ```bash
   npm run dev
   ```

The API will be available at `http://localhost:3001`

## API Documentation

### Base URL
```
http://localhost:3001/api/v1
```

### Health Check
```
GET /health
```

### Authentication Routes
- `POST /auth/register` - Register new user
- `POST /auth/login` - Login user
- `POST /auth/refresh` - Refresh authentication token
- `POST /auth/logout` - Logout user

### User Routes
- `GET /users/profile` - Get user profile
- `PUT /users/profile` - Update user profile
- `POST /users/kyc` - Submit KYC verification

### Wallet Routes
- `GET /wallet/balance` - Get wallet balance
- `POST /wallet/add-money` - Add money to wallet
- `POST /wallet/transfer` - P2P transfer
- `GET /wallet/transactions` - Get transaction history
- `POST /wallet/withdraw` - Withdraw to bank account

### Telecom Routes
- `GET /telecom/plans` - Get available data plans
- `POST /telecom/topup` - Purchase mobile top-up
- `GET /telecom/bill/:phoneNumber` - Get postpaid bill amount
- `POST /telecom/pay-bill` - Pay postpaid bill
- `GET /telecom/balance/:phoneNumber` - Check balance

### Utility Routes
- `GET /utilities/providers` - Get utility providers
- `GET /utilities/bill/:provider/:accountNumber` - Get utility bill
- `POST /utilities/pay-bill` - Pay utility bill
- `GET /utilities/history/:provider/:accountNumber` - Get bill history
- `POST /utilities/reminder` - Set payment reminder

## Project Structure

```
backend/
├── src/
│   ├── config/           # Configuration files (database, redis, logger)
│   ├── routes/           # API route handlers
│   ├── middleware/       # Express middleware (auth, validation, etc.)
│   ├── services/         # Business logic services
│   ├── models/           # Database models
│   ├── utils/            # Utility functions
│   ├── types/            # TypeScript type definitions
│   └── index.ts          # Main entry point
├── database/
│   └── 001_initial_schema.sql   # Database schema
├── tests/                # Unit and integration tests
├── logs/                 # Application logs
├── Dockerfile            # Docker container definition
├── package.json          # NPM dependencies
├── tsconfig.json         # TypeScript configuration
└── README.md            # This file
```

## Database Schema

The database includes the following main tables:

### Core Tables
- **users** - User accounts and profiles
- **wallets** - Digital wallets
- **transactions** - Transaction ledger

### Payment Tables
- **p2p_transfers** - Peer-to-peer transfers
- **bank_accounts** - Linked bank accounts
- **merchants** - Merchant information
- **qr_codes** - QR code data

### Telecom Tables
- **telecom_plans** - Available data/voice plans
- **mobile_numbers** - User phone numbers
- **telecom_topups** - Top-up purchases
- **postpaid_bills** - Postpaid billing

### Utility Tables
- **utility_providers** - Utility companies
- **utility_accounts** - User utility accounts
- **utility_bills** - Utility bills
- **utility_payments** - Bill payments
- **payment_reminders** - Payment reminders

### Security Tables
- **audit_logs** - Audit trail
- **device_tokens** - Push notification tokens

## Development

### Running Tests
```bash
npm run test
npm run test:coverage
```

### Linting & Formatting
```bash
npm run lint
npm run format
```

### Building for Production
```bash
npm run build
npm start
```

## Environment Variables

See `.env.example` for all available configuration options:

```env
# Server
NODE_ENV=development
PORT=3001

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/tilly_app
DB_HOST=localhost
DB_PORT=5432
DB_USER=tilly_user
DB_PASSWORD=secure_password
DB_NAME=tilly_app

# Redis
REDIS_URL=redis://localhost:6379

# JWT
JWT_SECRET=your_jwt_secret
JWT_EXPIRY=7d

# External APIs
FASEYHA_API_KEY=your_key
PAYMENT_GATEWAY_KEY=your_key

# CORS
CORS_ORIGIN=http://localhost:3000,http://localhost:8081
```

## Security Considerations

- All passwords are hashed using bcryptjs
- JWTs are used for API authentication
- Environment variables store sensitive data
- CORS is configured for specified origins
- Helmet middleware provides security headers
- All financial transactions are logged and audited
- Data is encrypted in transit (HTTPS in production)

## Deployment

### Using Docker

```bash
# Build image
docker build -t tilly-backend:latest .

# Run container
docker run -p 3001:3001 \
  -e NODE_ENV=production \
  -e DATABASE_URL=postgresql://user:pass@postgres:5432/tilly_app \
  -e REDIS_URL=redis://redis:6379 \
  tilly-backend:latest
```

### Cloud Deployment

The backend is designed to be deployed to:
- AWS (ECS, Elastic Beanstalk, Lambda)
- Google Cloud (Cloud Run, App Engine)
- Azure (App Service, Container Instances)
- DigitalOcean (App Platform, Kubernetes)

## Monitoring & Logging

- Logs are written to `logs/` directory
- Winston logger provides structured logging
- Request logging via Morgan middleware
- Application health check at `/health`

## Common Issues

### Database Connection Error
```
psql: error: could not translate host name "localhost" to address
```
**Solution:** Ensure PostgreSQL is running and credentials in `.env` are correct

### Port Already in Use
```
Error: listen EADDRINUSE: address already in use :::3001
```
**Solution:** Change PORT in `.env` or kill process using port 3001

### Redis Connection Error
```
Error: ECONNREFUSED 127.0.0.1:6379
```
**Solution:** Ensure Redis is running with `redis-server`

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Create a pull request

## Next Steps

- [ ] Implement authentication system
- [ ] Build payment gateway integration
- [ ] Develop telecom API connections
- [ ] Create utility bill aggregation
- [ ] Implement QR code scanning
- [ ] Add transaction notifications
- [ ] Set up monitoring & alerting

## Support

For issues and questions, please open a GitHub issue or contact the development team.

## License

This project is confidential and proprietary.
