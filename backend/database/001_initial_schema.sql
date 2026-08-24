-- =========================================
-- TILLY APP - Initial Database Schema
-- =========================================

-- Create schema
CREATE SCHEMA IF NOT EXISTS tilly;
SET search_path TO tilly;

-- =========================================
-- USERS & AUTHENTICATION
-- =========================================

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number VARCHAR(20) NOT NULL UNIQUE,
  email VARCHAR(255) UNIQUE,
  first_name VARCHAR(100),
  last_name VARCHAR(100),
  password_hash VARCHAR(255) NOT NULL,
  date_of_birth DATE,
  nationality VARCHAR(100),
  national_id VARCHAR(50) UNIQUE,
  address TEXT,
  city VARCHAR(100),
  country VARCHAR(100),
  kyc_status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, VERIFIED, REJECTED
  kyc_verified_at TIMESTAMP,
  status VARCHAR(20) DEFAULT 'ACTIVE', -- ACTIVE, SUSPENDED, DELETED
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_phone (phone_number),
  INDEX idx_email (email),
  INDEX idx_kyc_status (kyc_status)
);

-- =========================================
-- DIGITAL WALLET & PAYMENTS
-- =========================================

CREATE TABLE wallets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE,
  balance DECIMAL(15, 2) DEFAULT 0,
  currency VARCHAR(3) DEFAULT 'MVR',
  wallet_number VARCHAR(50) UNIQUE,
  status VARCHAR(20) DEFAULT 'ACTIVE',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user (user_id),
  INDEX idx_balance (balance)
);

CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wallet_id UUID NOT NULL,
  type VARCHAR(50) NOT NULL, -- DEPOSIT, WITHDRAWAL, P2P_TRANSFER, MERCHANT_PAYMENT, BILL_PAYMENT, TOP_UP
  amount DECIMAL(15, 2) NOT NULL,
  currency VARCHAR(3) DEFAULT 'MVR',
  status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, COMPLETED, FAILED
  description TEXT,
  reference_number VARCHAR(100) UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE CASCADE,
  INDEX idx_wallet (wallet_id),
  INDEX idx_type (type),
  INDEX idx_status (status),
  INDEX idx_created (created_at)
);

CREATE TABLE p2p_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_wallet_id UUID NOT NULL,
  to_phone_number VARCHAR(20),
  amount DECIMAL(15, 2) NOT NULL,
  status VARCHAR(20) DEFAULT 'PENDING',
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  FOREIGN KEY (from_wallet_id) REFERENCES wallets(id) ON DELETE CASCADE,
  INDEX idx_from_wallet (from_wallet_id),
  INDEX idx_to_phone (to_phone_number)
);

CREATE TABLE bank_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  bank_name VARCHAR(100),
  account_number VARCHAR(50),
  account_holder_name VARCHAR(100),
  account_type VARCHAR(50), -- CHECKING, SAVINGS
  is_primary BOOLEAN DEFAULT FALSE,
  status VARCHAR(20) DEFAULT 'ACTIVE',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user (user_id),
  UNIQUE(user_id, account_number)
);

-- =========================================
-- TELECOM SERVICES
-- =========================================

CREATE TABLE telecom_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) NOT NULL,
  provider VARCHAR(50), -- FASEYHA, DHIRAAGU, OTHERS
  data_amount VARCHAR(50),
  voice_minutes VARCHAR(50),
  validity_days INT,
  price DECIMAL(10, 2),
  description TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_provider (provider),
  INDEX idx_is_active (is_active)
);

CREATE TABLE mobile_numbers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  phone_number VARCHAR(20) NOT NULL,
  provider VARCHAR(50),
  is_primary BOOLEAN DEFAULT FALSE,
  status VARCHAR(20) DEFAULT 'ACTIVE',
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user (user_id),
  UNIQUE(user_id, phone_number)
);

CREATE TABLE telecom_topups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  mobile_number VARCHAR(20),
  plan_id UUID,
  amount DECIMAL(10, 2),
  status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, COMPLETED, FAILED
  transaction_id UUID,
  reference_number VARCHAR(100) UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (plan_id) REFERENCES telecom_plans(id),
  FOREIGN KEY (transaction_id) REFERENCES transactions(id),
  INDEX idx_user (user_id),
  INDEX idx_mobile (mobile_number),
  INDEX idx_status (status)
);

CREATE TABLE postpaid_bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  mobile_number VARCHAR(20),
  provider VARCHAR(50),
  bill_amount DECIMAL(10, 2),
  due_date DATE,
  billing_period_start DATE,
  billing_period_end DATE,
  status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, PAID, OVERDUE
  paid_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user (user_id),
  INDEX idx_status (status),
  INDEX idx_due_date (due_date)
);

-- =========================================
-- UTILITY PAYMENTS
-- =========================================

CREATE TABLE utility_providers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) NOT NULL UNIQUE,
  type VARCHAR(50), -- ELECTRICITY, WATER, INTERNET, GAS, GOVERNMENT
  api_endpoint VARCHAR(255),
  api_key VARCHAR(255),
  contact_number VARCHAR(20),
  website VARCHAR(255),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_type (type)
);

CREATE TABLE utility_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  provider_id UUID NOT NULL,
  account_number VARCHAR(100),
  account_holder_name VARCHAR(100),
  is_primary BOOLEAN DEFAULT FALSE,
  status VARCHAR(20) DEFAULT 'ACTIVE',
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (provider_id) REFERENCES utility_providers(id),
  INDEX idx_user (user_id),
  INDEX idx_provider (provider_id),
  UNIQUE(user_id, provider_id, account_number)
);

CREATE TABLE utility_bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  utility_account_id UUID NOT NULL,
  amount DECIMAL(15, 2),
  currency VARCHAR(3) DEFAULT 'MVR',
  billing_period_start DATE,
  billing_period_end DATE,
  due_date DATE,
  status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, PAID, OVERDUE
  paid_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (utility_account_id) REFERENCES utility_accounts(id) ON DELETE CASCADE,
  INDEX idx_account (utility_account_id),
  INDEX idx_status (status),
  INDEX idx_due_date (due_date)
);

CREATE TABLE utility_payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  utility_bill_id UUID,
  amount DECIMAL(15, 2),
  status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, COMPLETED, FAILED
  transaction_id UUID,
  reference_number VARCHAR(100) UNIQUE,
  payment_method VARCHAR(50), -- WALLET, BANK_TRANSFER, CARD
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (utility_bill_id) REFERENCES utility_bills(id),
  FOREIGN KEY (transaction_id) REFERENCES transactions(id),
  INDEX idx_user (user_id),
  INDEX idx_status (status)
);

CREATE TABLE payment_reminders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  bill_id UUID,
  reminder_date DATE,
  reminder_type VARCHAR(50), -- EMAIL, SMS, PUSH
  status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, SENT, SNOOZED
  sent_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user (user_id),
  INDEX idx_reminder_date (reminder_date)
);

-- =========================================
-- MERCHANT PAYMENTS & QR
-- =========================================

CREATE TABLE merchants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) NOT NULL,
  category VARCHAR(50),
  logo_url VARCHAR(255),
  phone_number VARCHAR(20),
  email VARCHAR(255),
  website VARCHAR(255),
  address TEXT,
  is_verified BOOLEAN DEFAULT FALSE,
  status VARCHAR(20) DEFAULT 'ACTIVE',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_category (category),
  INDEX idx_status (status)
);

CREATE TABLE qr_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id UUID,
  wallet_id UUID,
  qr_code_data TEXT NOT NULL,
  qr_type VARCHAR(20), -- STATIC, DYNAMIC
  amount DECIMAL(15, 2),
  description TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (merchant_id) REFERENCES merchants(id),
  FOREIGN KEY (wallet_id) REFERENCES wallets(id),
  INDEX idx_merchant (merchant_id),
  INDEX idx_wallet (wallet_id)
);

CREATE TABLE merchant_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  qr_code_id UUID,
  from_wallet_id UUID,
  to_wallet_id UUID,
  amount DECIMAL(15, 2),
  status VARCHAR(20) DEFAULT 'COMPLETED',
  transaction_id UUID,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (qr_code_id) REFERENCES qr_codes(id),
  FOREIGN KEY (from_wallet_id) REFERENCES wallets(id),
  FOREIGN KEY (to_wallet_id) REFERENCES wallets(id),
  FOREIGN KEY (transaction_id) REFERENCES transactions(id),
  INDEX idx_qr (qr_code_id),
  INDEX idx_from_wallet (from_wallet_id),
  INDEX idx_to_wallet (to_wallet_id)
);

-- =========================================
-- SECURITY & AUDIT
-- =========================================

CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID,
  action VARCHAR(100),
  resource_type VARCHAR(50),
  resource_id VARCHAR(100),
  details TEXT,
  ip_address VARCHAR(45),
  user_agent TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_user (user_id),
  INDEX idx_action (action),
  INDEX idx_created (created_at)
);

CREATE TABLE device_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  device_id VARCHAR(255),
  fcm_token VARCHAR(255),
  device_type VARCHAR(50), -- IOS, ANDROID, WEB
  device_name VARCHAR(100),
  is_primary BOOLEAN DEFAULT FALSE,
  last_used TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user (user_id),
  INDEX idx_fcm (fcm_token)
);

-- =========================================
-- INDEXES FOR PERFORMANCE
-- =========================================

CREATE INDEX idx_transactions_created_wallet ON transactions(wallet_id, created_at DESC);
CREATE INDEX idx_postpaid_bills_user_status ON postpaid_bills(user_id, status);
CREATE INDEX idx_utility_bills_account_status ON utility_bills(utility_account_id, status);
CREATE INDEX idx_telecom_topups_user_created ON telecom_topups(user_id, created_at DESC);

-- =========================================
-- VIEWS FOR COMMON QUERIES
-- =========================================

CREATE VIEW user_balances AS
SELECT
  u.id,
  u.phone_number,
  u.first_name,
  u.last_name,
  w.balance,
  w.currency,
  w.created_at
FROM users u
LEFT JOIN wallets w ON u.id = w.user_id;

-- =========================================
-- FUNCTIONS FOR COMMON OPERATIONS
-- =========================================

-- Function to update wallet balance
CREATE OR REPLACE FUNCTION update_wallet_balance(
  p_wallet_id UUID,
  p_amount DECIMAL,
  p_operation VARCHAR
) RETURNS DECIMAL AS $$
DECLARE
  v_new_balance DECIMAL;
BEGIN
  IF p_operation = 'ADD' THEN
    UPDATE wallets SET balance = balance + p_amount WHERE id = p_wallet_id;
  ELSIF p_operation = 'SUBTRACT' THEN
    UPDATE wallets SET balance = balance - p_amount WHERE id = p_wallet_id;
  END IF;

  SELECT balance INTO v_new_balance FROM wallets WHERE id = p_wallet_id;
  RETURN v_new_balance;
END;
$$ LANGUAGE plpgsql;

-- Function to log audit event
CREATE OR REPLACE FUNCTION log_audit_event(
  p_user_id UUID,
  p_action VARCHAR,
  p_resource_type VARCHAR,
  p_resource_id VARCHAR,
  p_details TEXT,
  p_ip_address VARCHAR
) RETURNS UUID AS $$
DECLARE
  v_log_id UUID;
BEGIN
  INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details, ip_address)
  VALUES (p_user_id, p_action, p_resource_type, p_resource_id, p_details, p_ip_address)
  RETURNING id INTO v_log_id;

  RETURN v_log_id;
END;
$$ LANGUAGE plpgsql;

COMMIT;
