import React, { useEffect, useState } from 'react';
import { Text } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import * as SplashScreen from 'expo-splash-screen';

// Screens
import LoginScreen from './screens/auth/LoginScreen';
import RegisterScreen from './screens/auth/RegisterScreen';
import HomeScreen from './screens/dashboard/HomeScreen';
import WalletScreen from './screens/wallet/WalletScreen';
import TelecomScreen from './screens/telecom/TelecomScreen';
import UtilitiesScreen from './screens/utilities/UtilitiesScreen';
import ProfileScreen from './screens/profile/ProfileScreen';

// Store
import { useAuthStore } from './stores/authStore';

// Navigation types
export type RootStackParamList = {
  Login: undefined;
  Register: undefined;
  MainApp: undefined;
};

export type MainTabParamList = {
  Home: undefined;
  Wallet: undefined;
  Telecom: undefined;
  Utilities: undefined;
  Profile: undefined;
};

const Stack = createStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();

SplashScreen.preventAutoHideAsync();

function AuthStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
      }}
    >
      <Stack.Screen name="Login" component={LoginScreen} />
      <Stack.Screen name="Register" component={RegisterScreen} />
    </Stack.Navigator>
  );
}

function MainTabNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: true,
        tabBarActiveTintColor: '#00A3E0',
        tabBarInactiveTintColor: '#999',
      }}
    >
      <Tab.Screen
        name="Home"
        component={HomeScreen}
        options={{
          title: 'Dashboard',
          tabBarLabel: 'Dashboard',
          tabBarIcon: ({ color }) => <HomeIcon color={color} />,
        }}
      />
      <Tab.Screen
        name="Wallet"
        component={WalletScreen}
        options={{
          title: 'Wallet',
          tabBarLabel: 'Wallet',
          tabBarIcon: ({ color }) => <WalletIcon color={color} />,
        }}
      />
      <Tab.Screen
        name="Telecom"
        component={TelecomScreen}
        options={{
          title: 'Telecom',
          tabBarLabel: 'Telecom',
          tabBarIcon: ({ color }) => <PhoneIcon color={color} />,
        }}
      />
      <Tab.Screen
        name="Utilities"
        component={UtilitiesScreen}
        options={{
          title: 'Bills',
          tabBarLabel: 'Bills',
          tabBarIcon: ({ color }) => <BillIcon color={color} />,
        }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{
          title: 'Profile',
          tabBarLabel: 'Profile',
          tabBarIcon: ({ color }) => <ProfileIcon color={color} />,
        }}
      />
    </Tab.Navigator>
  );
}

export default function App() {
  const { isAuthenticated, isLoading, checkAuth } = useAuthStore();
  const [appIsReady, setAppIsReady] = useState(false);

  useEffect(() => {
    async function prepare() {
      try {
        // Load cached auth state
        await checkAuth();
      } catch (e) {
        console.warn(e);
      } finally {
        setAppIsReady(true);
        await SplashScreen.hideAsync();
      }
    }

    prepare();
  }, []);

  if (!appIsReady || isLoading) {
    return null;
  }

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {!isAuthenticated ? (
          <Stack.Screen
            name="Login"
            component={AuthStack}
            options={{
              animationEnabled: false,
            }}
          />
        ) : (
          <Stack.Screen
            name="MainApp"
            component={MainTabNavigator}
            options={{
              animationEnabled: false,
            }}
          />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

// Placeholder icon components
const HomeIcon = ({ color }: { color: string }) => <Text style={{ color }}>🏠</Text>;
const WalletIcon = ({ color }: { color: string }) => <Text style={{ color }}>💳</Text>;
const PhoneIcon = ({ color }: { color: string }) => <Text style={{ color }}>📱</Text>;
const BillIcon = ({ color }: { color: string }) => <Text style={{ color }}>📄</Text>;
const ProfileIcon = ({ color }: { color: string }) => <Text style={{ color }}>👤</Text>;
