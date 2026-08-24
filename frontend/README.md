# Tilly Super App - Frontend

A modern mobile application for the Tilly Super App, built with React Native and Expo. Provides digital wallet, telecom services, and utility payment capabilities for the Maldives market.

## Quick Start

### Prerequisites
- Node.js 18+
- Expo CLI
- iOS Simulator (Mac) or Android Emulator
- Or an iOS/Android device with Expo Go app

### Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# For web
npm run web
```

## Development

### Project Structure

```
frontend/
├── src/
│   ├── screens/              # Application screens
│   │   ├── auth/            # Login & Registration
│   │   ├── dashboard/       # Home screen
│   │   ├── wallet/          # Wallet management
│   │   ├── telecom/         # Mobile top-up & data plans
│   │   ├── utilities/       # Bill payments
│   │   └── profile/         # User profile
│   ├── components/          # Reusable components
│   ├── stores/              # State management (Zustand)
│   ├── services/            # API client & services
│   ├── types/               # TypeScript type definitions
│   ├── utils/               # Utility functions
│   └── App.tsx              # Main app component
├── app.json                 # Expo configuration
├── tsconfig.json            # TypeScript configuration
└── package.json             # Dependencies
```

### Key Technologies

- **React Native** - Cross-platform mobile development
- **Expo** - Development framework & services
- **TypeScript** - Type safety
- **React Navigation** - Screen navigation
- **Zustand** - State management
- **Axios** - HTTP client
- **Expo Router** - File-based routing (optional)

### Running the App

#### iOS Simulator (Mac)
```bash
npm run dev
# Select 'i' for iOS Simulator
```

#### Android Emulator
```bash
npm run dev
# Select 'a' for Android Emulator
```

#### Web Browser
```bash
npm run web
```

#### Physical Device
1. Install Expo Go app (iOS App Store or Google Play)
2. Run `npm run dev`
3. Scan QR code with Expo Go

## Architecture

### Navigation Flow

```
Login/Register
    ↓
Dashboard (Home)
├── Wallet (Balance, Transfer, Withdraw)
├── Telecom (Top-up, Plans, Postpaid Bills)
├── Utilities (Bill Payment, Reminders)
└── Profile (Settings, Account)
```

### State Management (Zustand Stores)

- **authStore** - Authentication & user state
- **walletStore** - Wallet balance & transactions
- **telecomStore** - Mobile numbers & plans
- **utilitiesStore** - Bill accounts & payments

### API Integration

All API calls go through `services/api.ts`:

```typescript
import { apiClient } from '@/services/api';

// Login
await apiClient.login(phoneNumber, password);

// Get wallet balance
const { data } = await apiClient.getWalletBalance();

// Purchase top-up
await apiClient.purchaseTopup(phoneNumber, planId);
```

## Features Implementation

### Authentication
- [x] Login screen with phone + password
- [x] Registration with email & KYC
- [ ] Biometric login (Face ID / Fingerprint)
- [ ] Social login (Google, Apple)
- [x] Token refresh & auto-logout

### Digital Wallet
- [x] View balance
- [ ] Add money via card/bank
- [ ] P2P transfers
- [ ] Transaction history
- [ ] Bank account linking
- [ ] QR code scanning

### Telecom Services
- [x] Browse data plans
- [ ] Purchase mobile top-up
- [ ] View postpaid bills
- [ ] Pay bills
- [ ] Manage phone numbers
- [ ] Plan recommendations

### Utility Payments
- [x] Browse utility providers
- [ ] Add utility accounts
- [ ] View outstanding bills
- [ ] Make payments
- [ ] Payment history
- [ ] Set payment reminders

### Profile
- [x] View/edit profile
- [ ] Change password
- [ ] Security settings
- [ ] Notification preferences
- [ ] Linked devices
- [ ] Transaction history

## Environment Variables

Create `.env` file (or `.env.local` for sensitive data):

```env
EXPO_PUBLIC_API_URL=http://localhost:3001/api/v1
EXPO_PUBLIC_APP_NAME=Tilly
EXPO_PUBLIC_VERSION=0.1.0
```

## Testing

```bash
# Run tests
npm run test

# Run tests with coverage
npm run test:coverage
```

## Building for Production

### iOS Build
```bash
# Create EAS build
eas build --platform ios

# Build locally (requires Mac)
eas build:create --platform ios --local
```

### Android Build
```bash
# Create EAS build
eas build --platform android

# Build locally
eas build:create --platform android --local
```

### App Store Submission
```bash
# iOS TestFlight
eas submit --platform ios

# Google Play Store
eas submit --platform android
```

## Code Quality

### Linting
```bash
npm run lint
```

### Formatting
```bash
npm run format
```

### TypeScript Check
```bash
npx tsc --noEmit
```

## Debugging

### Debugger
- Press `d` in Expo CLI
- Opens React Native debugger

### Logs
```bash
# View device logs
npx expo logs
```

### Redux DevTools
For inspecting Zustand state:
```typescript
import { devtools } from 'zustand/middleware';

export const useAuthStore = create(
  devtools(
    (set) => ({
      // store logic
    }),
    { name: 'AuthStore' }
  )
);
```

## Performance Optimization

1. **Memoization**
   ```typescript
   import React, { memo } from 'react';
   const MyComponent = memo(({ prop }) => <View />);
   ```

2. **List Optimization**
   ```typescript
   <FlatList
     maxToRenderPerBatch={10}
     updateCellsBatchingPeriod={50}
     initialNumToRender={10}
   />
   ```

3. **Code Splitting**
   - Use React.lazy() for heavy components
   - Dynamic imports for large modules

## Security Best Practices

1. **Token Storage**
   - Store JWT tokens in secure storage
   - Use react-native-keychain or expo-secure-store

2. **Network Security**
   - HTTPS/TLS only
   - Certificate pinning (optional)
   - Disable logging in production

3. **Data Protection**
   - Encrypt sensitive data
   - Clear cache on logout
   - Never log sensitive data

4. **Biometric Auth**
   - Use expo-local-authentication
   - Fallback to password if unavailable

## Troubleshooting

### Metro bundler issues
```bash
npm start -- --reset-cache
```

### Dependencies not installing
```bash
rm -rf node_modules package-lock.json
npm install
```

### Expo Go connection issues
```bash
# Use tunnel connection
expo start --tunnel

# Or use LAN
expo start --lan
```

### iOS build failures
```bash
# Clear build cache
rm -rf ~/.expo

# Clean and rebuild
npm run build -- --clean
```

## Resources

- [Expo Documentation](https://docs.expo.dev)
- [React Native Docs](https://reactnative.dev)
- [React Navigation Guide](https://reactnavigation.org)
- [Zustand Guide](https://github.com/pmndrs/zustand)

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Submit pull request

## Next Steps

- [ ] Implement QR code scanner
- [ ] Add biometric authentication
- [ ] Create push notifications
- [ ] Implement payment gateway
- [ ] Add data visualization for spending
- [ ] Create in-app chat support
- [ ] Implement transaction receipts
- [ ] Add offline functionality

## Support

For issues and questions, open a GitHub issue or contact the team.

## License

This project is confidential and proprietary.
