import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:3001/api/v1';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 30000,
    });

    // Add request interceptor
    this.client.interceptors.request.use(async (config) => {
      const token = await AsyncStorage.getItem('authToken');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    // Add response interceptor
    this.client.interceptors.response.use(
      (response) => response,
      async (error) => {
        if (error.response?.status === 401) {
          // Handle unauthorized - clear token and redirect to login
          await AsyncStorage.removeItem('authToken');
          // Redirect to login screen
        }
        return Promise.reject(error);
      }
    );
  }

  // Auth endpoints
  async login(phoneNumber: string, password: string) {
    return this.client.post('/auth/login', { phoneNumber, password });
  }

  async register(data: any) {
    return this.client.post('/auth/register', data);
  }

  async logout() {
    return this.client.post('/auth/logout');
  }

  async refresh() {
    return this.client.post('/auth/refresh');
  }

  // User endpoints
  async getProfile() {
    return this.client.get('/users/profile');
  }

  async updateProfile(data: any) {
    return this.client.put('/users/profile', data);
  }

  async submitKYC(data: any) {
    return this.client.post('/users/kyc', data);
  }

  // Wallet endpoints
  async getWalletBalance() {
    return this.client.get('/wallet/balance');
  }

  async addMoney(amount: number, paymentMethod: string) {
    return this.client.post('/wallet/add-money', { amount, paymentMethod });
  }

  async transfer(recipientPhone: string, amount: number, note?: string) {
    return this.client.post('/wallet/transfer', {
      recipientPhone,
      amount,
      note,
    });
  }

  async getTransactions(limit = 10, offset = 0) {
    return this.client.get('/wallet/transactions', {
      params: { limit, offset },
    });
  }

  async withdraw(bankAccountId: string, amount: number) {
    return this.client.post('/wallet/withdraw', { bankAccountId, amount });
  }

  // Telecom endpoints
  async getTelecomPlans() {
    return this.client.get('/telecom/plans');
  }

  async purchaseTopup(phoneNumber: string, planId: string) {
    return this.client.post('/telecom/topup', { phoneNumber, planId });
  }

  async getPostpaidBill(phoneNumber: string) {
    return this.client.get(`/telecom/bill/${phoneNumber}`);
  }

  async payPostpaidBill(billId: string, amount: number) {
    return this.client.post('/telecom/pay-bill', { billId, amount });
  }

  async getTelecomBalance(phoneNumber: string) {
    return this.client.get(`/telecom/balance/${phoneNumber}`);
  }

  // Utility endpoints
  async getUtilityProviders() {
    return this.client.get('/utilities/providers');
  }

  async getUtilityBill(provider: string, accountNumber: string) {
    return this.client.get(`/utilities/bill/${provider}/${accountNumber}`);
  }

  async payUtilityBill(billId: string, amount: number) {
    return this.client.post('/utilities/pay-bill', { billId, amount });
  }

  async getUtilityHistory(provider: string, accountNumber: string) {
    return this.client.get(`/utilities/history/${provider}/${accountNumber}`);
  }

  async setPaymentReminder(billId: string, reminderDate: string) {
    return this.client.post('/utilities/reminder', { billId, reminderDate });
  }

  // Generic request method
  async request(config: AxiosRequestConfig) {
    return this.client.request(config);
  }
}

export const apiClient = new ApiClient();
