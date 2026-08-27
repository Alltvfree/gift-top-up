import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient } from '../services/api';

interface User {
  id: string;
  phoneNumber: string;
  firstName: string;
  lastName: string;
  email?: string;
  kycStatus: string;
}

interface RegisterData {
  firstName: string;
  lastName: string;
  phoneNumber: string;
  email?: string;
  password: string;
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  token: string | null;

  // Actions
  login: (phoneNumber: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  setUser: (user: User) => void;
}

function extractErrorMessage(error: any, fallback: string): string {
  return error?.response?.data?.error?.message || error?.message || fallback;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  isLoading: true,
  user: null,
  token: null,

  login: async (phoneNumber: string, password: string) => {
    try {
      set({ isLoading: true });
      const response = await apiClient.login(phoneNumber, password);
      const { token, user } = response.data;
      await AsyncStorage.setItem('authToken', token);
      set({
        isAuthenticated: true,
        token,
        user,
      });
    } catch (error: any) {
      throw new Error(extractErrorMessage(error, 'Login failed. Please try again.'));
    } finally {
      set({ isLoading: false });
    }
  },

  register: async (data: RegisterData) => {
    try {
      set({ isLoading: true });
      const response = await apiClient.register(data);
      const { token, user } = response.data;
      await AsyncStorage.setItem('authToken', token);
      set({
        isAuthenticated: true,
        token,
        user,
      });
    } catch (error: any) {
      throw new Error(extractErrorMessage(error, 'Registration failed. Please try again.'));
    } finally {
      set({ isLoading: false });
    }
  },

  logout: async () => {
    try {
      await apiClient.logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      await AsyncStorage.removeItem('authToken');
      set({
        isAuthenticated: false,
        token: null,
        user: null,
      });
    }
  },

  checkAuth: async () => {
    try {
      set({ isLoading: true });
      const token = await AsyncStorage.getItem('authToken');
      if (token) {
        const response = await apiClient.getProfile();
        set({
          isAuthenticated: true,
          token,
          user: response.data,
        });
      } else {
        set({
          isAuthenticated: false,
          token: null,
          user: null,
        });
      }
    } catch (error) {
      // Token invalid/expired or profile endpoint unavailable - fall back
      // to a logged-out state rather than getting stuck loading forever.
      await AsyncStorage.removeItem('authToken');
      set({
        isAuthenticated: false,
        token: null,
        user: null,
      });
    } finally {
      set({ isLoading: false });
    }
  },

  setUser: (user: User) => {
    set({ user });
  },
}));
