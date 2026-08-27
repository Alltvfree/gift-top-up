import type { SupabaseClient } from '@supabase/supabase-js';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import { createUser, getOrCreateWallet, getUser, getUserByPhone } from '../config/supabase';

export class AuthError extends Error {
  status: number;
  constructor(message: string, status = 400) {
    super(message);
    this.status = status;
  }
}

export interface RegisterInput {
  firstName: string;
  lastName: string;
  phoneNumber: string;
  email?: string;
  password: string;
}

export interface LoginInput {
  phoneNumber: string;
  password: string;
}

export function toPublicUser(user: any) {
  return {
    id: user.id,
    firstName: user.first_name,
    lastName: user.last_name,
    phoneNumber: user.phone_number,
    email: user.email,
    kycStatus: user.kyc_status,
  };
}

export async function registerUser(db: SupabaseClient, jwtSecret: string, input: RegisterInput) {
  const { firstName, lastName, phoneNumber, email, password } = input || ({} as RegisterInput);

  if (!firstName || !lastName || !phoneNumber || !password) {
    throw new AuthError('Please fill in all required fields', 400);
  }
  if (password.length < 6) {
    throw new AuthError('Password must be at least 6 characters', 400);
  }

  const existing = await getUserByPhone(db, phoneNumber);
  if (existing) {
    throw new AuthError('An account with this phone number already exists', 409);
  }

  const passwordHash = await bcrypt.hash(password, 10);

  const user = await createUser(db, {
    phone_number: phoneNumber,
    email: email || undefined,
    first_name: firstName,
    last_name: lastName,
    password_hash: passwordHash,
  });

  const wallet = await getOrCreateWallet(db, user.id);

  const token = jwt.sign({ sub: user.id, phoneNumber: user.phone_number }, jwtSecret, {
    expiresIn: '7d',
  });

  return {
    token,
    user: toPublicUser(user),
    wallet: { balance: wallet.balance, currency: wallet.currency },
  };
}

export async function loginUser(db: SupabaseClient, jwtSecret: string, input: LoginInput) {
  const { phoneNumber, password } = input || ({} as LoginInput);

  if (!phoneNumber || !password) {
    throw new AuthError('Phone number and password are required', 400);
  }

  const user = await getUserByPhone(db, phoneNumber);
  if (!user) {
    throw new AuthError('Invalid phone number or password', 401);
  }

  const valid = await bcrypt.compare(password, user.password_hash);
  if (!valid) {
    throw new AuthError('Invalid phone number or password', 401);
  }

  const wallet = await getOrCreateWallet(db, user.id);

  const token = jwt.sign({ sub: user.id, phoneNumber: user.phone_number }, jwtSecret, {
    expiresIn: '7d',
  });

  return {
    token,
    user: toPublicUser(user),
    wallet: { balance: wallet.balance, currency: wallet.currency },
  };
}

/**
 * Verify a "Bearer <token>" Authorization header and return the user id
 * it was issued for. Throws AuthError(401) if missing/invalid/expired.
 */
export function verifyAuthHeader(authHeader: string | undefined | null, jwtSecret: string): string {
  const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : undefined;
  if (!token) {
    throw new AuthError('Missing or invalid Authorization header', 401);
  }

  try {
    const payload = jwt.verify(token, jwtSecret) as { sub: string };
    if (!payload?.sub) {
      throw new AuthError('Invalid token', 401);
    }
    return payload.sub;
  } catch {
    throw new AuthError('Invalid or expired token', 401);
  }
}

/**
 * Look up the current user's public profile from a verified Authorization
 * header.
 */
export async function getProfile(
  db: SupabaseClient,
  jwtSecret: string,
  authHeader: string | undefined | null
) {
  const userId = verifyAuthHeader(authHeader, jwtSecret);
  const user = await getUser(db, userId);
  if (!user) {
    throw new AuthError('User not found', 404);
  }
  return toPublicUser(user);
}
