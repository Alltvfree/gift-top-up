import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from 'react-native';
import { useAuthStore } from '../../stores/authStore';
import { apiClient } from '../../services/api';

export default function HomeScreen() {
  const { user } = useAuthStore();
  const [walletBalance, setWalletBalance] = useState<number>(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDashboardData();
  }, []);

  const loadDashboardData = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getWalletBalance();
      setWalletBalance(response.data.balance);
    } catch (error) {
      console.error('Error loading dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.container}>
      {/* Wallet Card */}
      <View style={styles.walletCard}>
        <Text style={styles.walletLabel}>Wallet Balance</Text>
        <Text style={styles.walletAmount}>
          {walletBalance.toLocaleString('en-US', {
            style: 'currency',
            currency: 'MVR',
          })}
        </Text>
      </View>

      {/* Quick Actions */}
      <View style={styles.quickActionsContainer}>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>💳</Text>
          <Text style={styles.actionLabel}>Add Money</Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>📤</Text>
          <Text style={styles.actionLabel}>Transfer</Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>📱</Text>
          <Text style={styles.actionLabel}>Top-up</Text>
        </TouchableOpacity>

        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>📄</Text>
          <Text style={styles.actionLabel}>Pay Bills</Text>
        </TouchableOpacity>
      </View>

      {/* Recent Transactions */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Recent Transactions</Text>
        <Text style={styles.emptyState}>No transactions yet</Text>
      </View>

      {/* Services */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Services</Text>
        <TouchableOpacity style={styles.serviceItem}>
          <Text style={styles.serviceIcon}>📱</Text>
          <View>
            <Text style={styles.serviceTitle}>Mobile Top-up</Text>
            <Text style={styles.serviceDesc}>Recharge & buy data</Text>
          </View>
        </TouchableOpacity>

        <TouchableOpacity style={styles.serviceItem}>
          <Text style={styles.serviceIcon}>⚡</Text>
          <View>
            <Text style={styles.serviceTitle}>Utility Bills</Text>
            <Text style={styles.serviceDesc}>Pay electricity, water & internet</Text>
          </View>
        </TouchableOpacity>

        <TouchableOpacity style={styles.serviceItem}>
          <Text style={styles.serviceIcon}>🏪</Text>
          <View>
            <Text style={styles.serviceTitle}>QR Payments</Text>
            <Text style={styles.serviceDesc}>Scan & pay at merchants</Text>
          </View>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  walletCard: {
    backgroundColor: '#00A3E0',
    margin: 16,
    padding: 24,
    borderRadius: 16,
    color: '#fff',
  },
  walletLabel: {
    color: '#fff',
    fontSize: 14,
    opacity: 0.9,
  },
  walletAmount: {
    color: '#fff',
    fontSize: 32,
    fontWeight: 'bold',
    marginTop: 8,
  },
  quickActionsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: 8,
    marginVertical: 8,
  },
  actionButton: {
    width: '25%',
    alignItems: 'center',
    padding: 8,
  },
  actionIcon: {
    fontSize: 32,
    marginBottom: 8,
  },
  actionLabel: {
    fontSize: 12,
    textAlign: 'center',
    color: '#333',
  },
  section: {
    marginTop: 16,
    paddingHorizontal: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 12,
    color: '#000',
  },
  emptyState: {
    textAlign: 'center',
    color: '#999',
    paddingVertical: 24,
  },
  serviceItem: {
    flexDirection: 'row',
    backgroundColor: '#fff',
    padding: 16,
    marginBottom: 8,
    borderRadius: 8,
    alignItems: 'center',
  },
  serviceIcon: {
    fontSize: 32,
    marginRight: 16,
  },
  serviceTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#000',
  },
  serviceDesc: {
    fontSize: 14,
    color: '#999',
    marginTop: 4,
  },
});
