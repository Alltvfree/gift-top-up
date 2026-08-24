import React, { useState, useEffect } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from 'react-native';
import { apiClient } from '../../services/api';

interface Provider {
  id: string;
  name: string;
  type: string;
  logo: string;
}

export default function UtilitiesScreen() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadProviders();
  }, []);

  const loadProviders = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getUtilityProviders();
      setProviders(response.data.providers || []);
    } catch (error) {
      console.error('Error loading providers:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Utility Bills</Text>
      </View>

      {/* Quick Actions */}
      <View style={styles.actionsContainer}>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>⚡</Text>
          <Text style={styles.actionLabel}>Electricity</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>💧</Text>
          <Text style={styles.actionLabel}>Water</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>🌐</Text>
          <Text style={styles.actionLabel}>Internet</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionButton}>
          <Text style={styles.actionIcon}>🏛️</Text>
          <Text style={styles.actionLabel}>Government</Text>
        </TouchableOpacity>
      </View>

      {/* Utility Providers */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Available Providers</Text>
        {loading ? (
          <Text style={styles.loadingText}>Loading providers...</Text>
        ) : providers.length > 0 ? (
          providers.map((provider) => (
            <TouchableOpacity key={provider.id} style={styles.providerCard}>
              <Text style={styles.providerIcon}>🏢</Text>
              <View style={styles.providerInfo}>
                <Text style={styles.providerName}>{provider.name}</Text>
                <Text style={styles.providerType}>{provider.type}</Text>
              </View>
              <Text style={styles.arrow}>›</Text>
            </TouchableOpacity>
          ))
        ) : (
          <Text style={styles.emptyStateText}>No providers available</Text>
        )}
      </View>

      {/* My Bills */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>My Bills</Text>
          <TouchableOpacity>
            <Text style={styles.addLink}>+ Add Account</Text>
          </TouchableOpacity>
        </View>
        <View style={styles.emptyState}>
          <Text style={styles.emptyStateText}>No bill accounts added</Text>
        </View>
      </View>

      {/* Payment Reminders */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Payment Reminders</Text>
        <View style={styles.emptyState}>
          <Text style={styles.emptyStateText}>No upcoming reminders</Text>
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
  providerCard: {
    backgroundColor: '#fff',
    padding: 16,
    borderRadius: 8,
    marginBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
  },
  providerIcon: {
    fontSize: 32,
    marginRight: 12,
  },
  providerInfo: {
    flex: 1,
  },
  providerName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#000',
  },
  providerType: {
    fontSize: 14,
    color: '#999',
    marginTop: 4,
  },
  arrow: {
    fontSize: 20,
    color: '#ccc',
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
