import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface User {
  id: string;
  phoneNumber: string;
  firstName: string;
  lastName: string;
  email?: string;
  kycStatus: string;
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  token: string | null;

  // Actions
  login: (phoneNumber: string, password: string) => Promise<void>;
  register: (data: any) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  setUser: (user: User) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  isLoading: true,
  user: null,
  token: null,

  login: async (phoneNumber: string, password: string) => {
    try {
      set({ isLoading: true });
      // TODO: Implement API call
      // const response = await apiClient.post('/auth/login', { phoneNumber, password });
      // await AsyncStorage.setItem('authToken', response.data.token);
      // set({
      //   isAuthenticated: true,
      //   token: response.data.token,
      //   user: response.data.user,
      // });
    } finally {
      set({ isLoading: false });
    }
  },

  register: async (data: any) => {
    try {
      set({ isLoading: true });
      // TODO: Implement API call
      // const response = await apiClient.post('/auth/register', data);
      // await AsyncStorage.setItem('authToken', response.data.token);
      // set({
      //   isAuthenticated: true,
      //   token: response.data.token,
      //   user: response.data.user,
      // });
    } finally {
      set({ isLoading: false });
    }
  },

  logout: async () => {
    try {
      // TODO: Implement API call to logout
      // await apiClient.post('/auth/logout');
      await AsyncStorage.removeItem('authToken');
      set({
        isAuthenticated: false,
        token: null,
        user: null,
      });
    } catch (error) {
      console.error('Logout error:', error);
    }
  },

  checkAuth: async () => {
    try {
      set({ isLoading: true });
      const token = await AsyncStorage.getItem('authToken');
      if (token) {
        // TODO: Verify token with API
        // const response = await apiClient.get('/users/profile');
        // set({
        //   isAuthenticated: true,
        //   token,
        //   user: response.data,
        // });
      } else {
        set({
          isAuthenticated: false,
          token: null,
          user: null,
        });
      }
    } finally {
      set({ isLoading: false });
    }
  },

  setUser: (user: User) => {
    set({ user });
  },
}));
