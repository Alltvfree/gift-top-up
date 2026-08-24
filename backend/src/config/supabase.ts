import { createClient } from '@supabase/supabase-js';
import { logger } from './logger';

const supabaseUrl = process.env.SUPABASE_URL || '';
const supabaseKey = process.env.SUPABASE_ANON_KEY || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

if (!supabaseUrl || !supabaseKey) {
  logger.error('Supabase environment variables not set');
}

// Client for user operations (uses anon key)
export const supabaseClient = createClient(supabaseUrl, supabaseKey, {
  auth: {
    persistSession: false,
  },
});

// Admin client for admin operations (uses service role key)
export const supabaseAdmin = supabaseServiceKey
  ? createClient(supabaseUrl, supabaseServiceKey, {
      auth: {
        persistSession: false,
      },
    })
  : supabaseClient;

/**
 * Initialize Supabase connection
 */
export async function initializeSupabase(): Promise<void> {
  try {
    // Test connection by checking if we can access auth
    const { data, error } = await supabaseClient.auth.getUser();
    if (error && error.status !== 401) {
      // 401 is expected when not authenticated
      throw error;
    }
    logger.info('✓ Supabase connected');
  } catch (error) {
    logger.error('Failed to connect to Supabase:', error);
    throw error;
  }
}

/**
 * Execute a query using Supabase
 * For simple queries, use the query builder
 * For complex queries, use RPC functions
 */
export async function query(
  table: string,
  operation: 'select' | 'insert' | 'update' | 'delete',
  data: any = {}
): Promise<any> {
  try {
    let result: any;

    switch (operation) {
      case 'select':
        result = await supabaseClient
          .from(table)
          .select(data.columns || '*')
          .match(data.match || {})
          .limit(data.limit || 100);
        break;

      case 'insert':
        result = await supabaseClient
          .from(table)
          .insert(data.values);
        break;

      case 'update':
        result = await supabaseClient
          .from(table)
          .update(data.values)
          .match(data.match);
        break;

      case 'delete':
        result = await supabaseClient
          .from(table)
          .delete()
          .match(data.match);
        break;
    }

    if (result.error) {
      throw new Error(`Supabase error: ${result.error.message}`);
    }

    return result;
  } catch (error) {
    logger.error(`Database ${operation} error:`, error);
    throw error;
  }
}

/**
 * Call a Supabase RPC function
 */
export async function callRpc(
  functionName: string,
  params: Record<string, any> = {}
): Promise<any> {
  try {
    const { data, error } = await supabaseClient.rpc(functionName, params);

    if (error) {
      throw new Error(`RPC error: ${error.message}`);
    }

    return data;
  } catch (error) {
    logger.error(`RPC call error for ${functionName}:`, error);
    throw error;
  }
}

/**
 * Get a user by ID
 */
export async function getUser(userId: string): Promise<any> {
  const { data, error } = await supabaseClient
    .from('users')
    .select('*')
    .eq('id', userId)
    .single();

  if (error) throw error;
  return data;
}

/**
 * Get user by phone number
 */
export async function getUserByPhone(phoneNumber: string): Promise<any> {
  const { data, error } = await supabaseClient
    .from('users')
    .select('*')
    .eq('phone_number', phoneNumber)
    .single();

  if (error && error.code === 'PGRST116') {
    // Not found error
    return null;
  }

  if (error) throw error;
  return data;
}

/**
 * Create a new user
 */
export async function createUser(userData: {
  id: string;
  phone_number: string;
  email?: string;
  first_name: string;
  last_name: string;
  password_hash: string;
}): Promise<any> {
  const { data, error } = await supabaseClient
    .from('users')
    .insert([userData])
    .select()
    .single();

  if (error) throw error;
  return data;
}

/**
 * Get or create wallet for user
 */
export async function getOrCreateWallet(userId: string): Promise<any> {
  const { data, error } = await supabaseClient
    .from('wallets')
    .select('*')
    .eq('user_id', userId)
    .single();

  if (error && error.code === 'PGRST116') {
    // Wallet doesn't exist, create it
    const { v4: uuidv4 } = require('uuid');
    const { data: newWallet, error: createError } = await supabaseClient
      .from('wallets')
      .insert([
        {
          id: uuidv4(),
          user_id: userId,
          balance: 0,
          currency: 'MVR',
        },
      ])
      .select()
      .single();

    if (createError) throw createError;
    return newWallet;
  }

  if (error) throw error;
  return data;
}

/**
 * Get wallet balance
 */
export async function getWalletBalance(userId: string): Promise<number> {
  const wallet = await getOrCreateWallet(userId);
  return wallet?.balance || 0;
}

/**
 * Update wallet balance
 */
export async function updateWalletBalance(
  userId: string,
  amount: number,
  operation: 'add' | 'subtract'
): Promise<number> {
  const wallet = await getOrCreateWallet(userId);

  let newBalance: number;
  if (operation === 'add') {
    newBalance = (wallet.balance || 0) + amount;
  } else {
    newBalance = (wallet.balance || 0) - amount;
  }

  if (newBalance < 0) {
    throw new Error('Insufficient balance');
  }

  const { data, error } = await supabaseClient
    .from('wallets')
    .update({ balance: newBalance })
    .eq('user_id', userId)
    .select()
    .single();

  if (error) throw error;
  return newBalance;
}

/**
 * Log transaction
 */
export async function logTransaction(transaction: {
  wallet_id: string;
  type: string;
  amount: number;
  currency?: string;
  status?: string;
  description?: string;
  reference_number?: string;
}): Promise<any> {
  const { v4: uuidv4 } = require('uuid');

  const { data, error } = await supabaseClient
    .from('transactions')
    .insert([
      {
        id: uuidv4(),
        ...transaction,
        currency: transaction.currency || 'MVR',
        status: transaction.status || 'COMPLETED',
      },
    ])
    .select()
    .single();

  if (error) throw error;
  return data;
}

export default {
  supabaseClient,
  supabaseAdmin,
  initializeSupabase,
  query,
  callRpc,
  getUser,
  getUserByPhone,
  createUser,
  getOrCreateWallet,
  getWalletBalance,
  updateWalletBalance,
  logTransaction,
};
