# Tilly Super App - Quick Start Guide

Get up and running in 5 minutes! 🚀

---

## ⚡ Super Quick Start (Docker)

```bash
# 1. Clone repo (if not already cloned)
git clone https://github.com/alltvfree/gift-top-up.git
cd gift-top-up

# 2. Switch to development branch
git checkout claude/app-build-qyq3iv

# 3. Start everything
docker-compose up -d

# 4. Verify it's working
curl http://localhost:3001/health

# You should see: {"status":"OK",...}
```

**Done!** Your app is running:
- 📱 Frontend: Ready for development at `frontend/`
- 🔙 Backend: Running at `http://localhost:3001`
- 🗄️ Database: PostgreSQL on `localhost:5432`
- ⚡ Cache: Redis on `localhost:6379`

---

## 👨‍💻 Start Developing

### Terminal 1: Backend
```bash
cd backend
npm install
npm run dev
```

### Terminal 2: Frontend
```bash
cd frontend
npm install
npm run dev
```

### Terminal 3: Database (Optional)
```bash
# View database
psql -U tilly_user -d tilly_app -h localhost

# Inside psql:
\dt              # List tables
SELECT * FROM users;
SELECT * FROM wallets;
```

---

## 🧪 Test the API

### Test Health Check
```bash
curl http://localhost:3001/health
```

### Test User Registration
```bash
curl -X POST http://localhost:3001/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "John",
    "lastName": "Doe",
    "phoneNumber": "+96079123456",
    "email": "john@example.com",
    "password": "secure123"
  }'
```

### Test User Login
```bash
curl -X POST http://localhost:3001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "phoneNumber": "+96079123456",
    "password": "secure123"
  }'
```

### Copy JWT Token
From the login response, copy the `token` value.

### Test Protected Endpoint
```bash
curl http://localhost:3001/api/v1/wallet/balance \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

---

## 📱 View the Frontend

1. Start the frontend (see above)
2. Expo will open in your browser at `http://localhost:19000`
3. Choose how to run:
   - **Web**: Press `w` for web browser
   - **iOS**: Press `i` for iOS Simulator (Mac only)
   - **Android**: Press `a` for Android Emulator
   - **Phone**: Scan QR code with Expo Go app

---

## 📁 Project Structure

```
tilly-app/
├── backend/                 # Node.js API
│   ├── src/
│   │   ├── index.ts        # Main server
│   │   ├── config/         # Database, Redis, Logger
│   │   ├── routes/         # API endpoints
│   │   └── services/       # Business logic (to implement)
│   └── package.json
├── frontend/               # React Native app
│   ├── src/
│   │   ├── screens/        # App screens
│   │   ├── services/       # API client
│   │   ├── stores/         # State management
│   │   └── App.tsx         # Main component
│   └── package.json
├── docker-compose.yml      # Docker setup
├── TILLY_APP_PLAN.md      # Full roadmap
├── IMPLEMENTATION_GUIDE.md # Step-by-step guide
├── DEVELOPMENT_CHECKLIST.md # Progress tracker
└── README.md              # Project overview
```

---

## 🔑 Important Files

| File | Purpose |
|------|---------|
| `backend/.env.example` | Backend config template |
| `backend/database/001_initial_schema.sql` | Database schema |
| `TILLY_APP_PLAN.md` | Full project roadmap |
| `IMPLEMENTATION_GUIDE.md` | Week-by-week development plan |
| `DEVELOPMENT_CHECKLIST.md` | Track progress |
| `README.md` | Project overview |

---

## 🚀 What's Already Built

✅ **Backend**
- Express.js server with TypeScript
- PostgreSQL database with 20+ tables
- Redis caching configured
- JWT authentication ready
- All API route stubs created
- Docker containerization
- Comprehensive documentation

✅ **Frontend**
- React Native with Expo
- 7 main screens created
- Navigation setup
- State management (Zustand)
- API client service
- Beautiful UI design

✅ **Database**
- Users & authentication
- Wallets & transactions
- Telecom services
- Utility payments
- Merchant payments
- Audit logging

---

## 📝 Next Steps

### Week 1-2: Authentication (Backend)
1. Implement user registration
2. Implement user login
3. Create JWT tokens
4. Protect API routes

See: `IMPLEMENTATION_GUIDE.md` → Week 1-2

### Week 3-4: Wallet System (Backend)
1. Implement balance tracking
2. Add money flow
3. P2P transfers
4. Bank withdrawals

See: `IMPLEMENTATION_GUIDE.md` → Week 3-4

### Week 5-12: Frontend Implementation
1. Connect to authentication APIs
2. Build wallet screens
3. Build telecom screens
4. Build utility screens
5. Add QR scanner
6. Add biometric auth

See: `IMPLEMENTATION_GUIDE.md` → Week 7-12

---

## 💡 Common Commands

### Backend
```bash
cd backend

npm install              # Install dependencies
npm run dev             # Start dev server (watches for changes)
npm run build           # Compile TypeScript
npm run test            # Run tests
npm run lint            # Check code style
npm start               # Start production server
```

### Frontend
```bash
cd frontend

npm install             # Install dependencies
npm run dev             # Start Expo
npm run web             # Web version
npm run test            # Run tests
npm run lint            # Check code style
```

### Docker
```bash
docker-compose up -d    # Start all services
docker-compose down     # Stop all services
docker-compose logs -f  # View logs
docker-compose ps       # Show running containers
docker-compose restart  # Restart services
```

### Database
```bash
# Connect to database
psql -U tilly_user -d tilly_app -h localhost

# View tables
\dt

# View users
SELECT * FROM users;

# View wallets
SELECT * FROM wallets;
```

---

## 🐛 Troubleshooting

### Docker won't start
```bash
# Check if ports are free
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis
lsof -i :3001  # Backend

# Kill conflicting process
kill -9 <PID>

# Try again
docker-compose up -d
```

### Backend won't connect to database
```bash
# Check PostgreSQL is running
docker-compose logs postgres

# Reset database
docker-compose down
docker-compose up -d
```

### Frontend won't start
```bash
# Clear cache
npm start -- --reset-cache

# Reinstall
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### Port already in use
```bash
# Use different port
PORT=3002 npm run dev
```

---

## 📚 Documentation Links

- **[Full Project Plan](TILLY_APP_PLAN.md)** - Complete roadmap & architecture
- **[Implementation Guide](IMPLEMENTATION_GUIDE.md)** - Week-by-week development
- **[Development Checklist](DEVELOPMENT_CHECKLIST.md)** - Progress tracking
- **[Backend README](backend/README.md)** - API documentation
- **[Frontend README](frontend/README.md)** - Mobile app guide
- **[GitHub Branch](https://github.com/alltvfree/gift-top-up/tree/claude/app-build-qyq3iv)** - View code online

---

## 🎯 Development Tips

1. **Use Postman/Insomnia** to test APIs before frontend integration
2. **Keep docker running** - Makes development much faster
3. **Use hot reload** - Both backend and frontend support auto-reload
4. **Test frequently** - Run tests before committing
5. **Check logs** - `docker-compose logs -f` is your friend
6. **Commit often** - Small, focused commits are easier to review
7. **Update checklist** - Track progress weekly

---

## 🔐 Important Notes

- **Don't commit `.env`** - Only commit `.env.example`
- **JWT Secret** - Change `JWT_SECRET` in `.env` for production
- **Database Password** - Change default password in `.env`
- **API Keys** - Add real API keys for payment gateways & telecom providers
- **Sensitive Data** - Never log passwords, tokens, or card numbers

---

## 📞 Getting Help

1. **Check Documentation** - Most answers are in the README files
2. **Review Implementation Guide** - Step-by-step instructions
3. **Check Logs** - `docker-compose logs -f` shows what's wrong
4. **Use Postman** - Test APIs before debugging in frontend
5. **Read Error Messages** - They usually tell you exactly what's wrong

---

## ✨ You're Ready!

Everything is set up. You can now:
- ✅ Run the backend
- ✅ Run the frontend
- ✅ Access the database
- ✅ Test the APIs
- ✅ Start implementing features

**Next:** Pick a feature from the [Implementation Guide](IMPLEMENTATION_GUIDE.md) and start coding! 🚀

---

## 📊 Current Status

| Component | Status | Details |
|-----------|--------|---------|
| Backend | ✅ Ready | Server running at :3001 |
| Frontend | ✅ Ready | Expo ready for development |
| Database | ✅ Ready | PostgreSQL with schema |
| Cache | ✅ Ready | Redis configured |
| Auth | ⏳ To Implement | Routes stubbed |
| Wallet | ⏳ To Implement | Routes stubbed |
| Telecom | ⏳ To Implement | Routes stubbed |
| Utilities | ⏳ To Implement | Routes stubbed |

---

Good luck! 🍀 Start with authentication, it's the foundation for everything else!

*Questions? Check the [full documentation](README.md)*
