import React, { useState, useEffect } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, FlatList } from 'react-native';
import { apiClient } from '../../services/api';

interface Plan {
  id: string;
  name: string;
  validity: string;
  price: number;
  data: string;
}

export default function TelecomScreen() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadPlans();
  }, []);

  const loadPlans = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getTelecomPlans();
      setPlans(response.data.plans || []);
    } catch (error) {
      console.error('Error loading plans:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Telecom Services</Text>
      </View>

      {/* Quick Actions */}
      <View style={styles.actionsContainer}>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>📱</Text>
          <Text style={styles.actionLabel}>Mobile Top-up</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>📊</Text>
          <Text style={styles.actionLabel}>Data Plans</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>📄</Text>
          <Text style={styles.actionLabel}>Postpaid Bill</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>⚙️</Text>
          <Text style={styles.actionLabel}>Manage Numbers</Text>
        </TouchableOpacity>
      </View>

      {/* Available Plans */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Available Plans</Text>
        {loading ? (
          <Text style={styles.loadingText}>Loading plans...</Text>
        ) : plans.length > 0 ? (
          plans.map((plan) => (
            <TouchableOpacity key={plan.id} style={styles.planCard}>
              <View>
                <Text style={styles.planName}>{plan.name}</Text>
                <Text style={styles.planDetails}>
                  {plan.data} • {plan.validity}
                </Text>
              </View>
              <Text style={styles.planPrice}>{plan.price} MVR</Text>
            </TouchableOpacity>
          ))
        ) : (
          <Text style={styles.emptyStateText}>No plans available</Text>
        )}
      </View>

      {/* My Phone Numbers */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>My Numbers</Text>
          <TouchableOpacity>
            <Text style={styles.addLink}>+ Add</Text>
          </TouchableOpacity>
        </View>
        <View style={styles.emptyState}>
          <Text style={styles.emptyStateText}>No phone numbers added</Text>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  header: {
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#000',
  },
  actionsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: 8,
    marginVertical: 16,
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
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#000',
    marginBottom: 12,
  },
  addLink: {
    color: '#00A3E0',
    fontSize: 14,
    fontWeight: '600',
  },
  planCard: {
    backgroundColor: '#fff',
    padding: 16,
    borderRadius: 8,
    marginBottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  planName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#000',
  },
  planDetails: {
    fontSize: 14,
    color: '#999',
    marginTop: 4,
  },
  planPrice: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#00A3E0',
  },
  emptyState: {
    backgroundColor: '#fff',
    paddingVertical: 32,
    marginTop: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  emptyStateText: {
    color: '#999',
    fontSize: 16,
  },
  loadingText: {
    color: '#999',
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: 16,
  },
});
