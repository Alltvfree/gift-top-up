import express from 'express';
import { logger } from '../config/logger';
import { getSupabaseAdmin } from '../config/supabase';
import { AuthError, loginUser, registerUser } from '../services/authService';

const router = express.Router();

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-me';

// Register user
router.post('/register', async (req, res) => {
  try {
    const result = await registerUser(getSupabaseAdmin(), JWT_SECRET, req.body);
    logger.info(`User registered: ${result.user.phoneNumber}`);
    res.status(201).json(result);
  } catch (error: any) {
    const status = error instanceof AuthError ? error.status : 500;
    if (status === 500) logger.error('Register error:', error);
    res.status(status).json({ error: { message: error.message || 'Registration failed', status } });
  }
});

// Login user
router.post('/login', async (req, res) => {
  try {
    const result = await loginUser(getSupabaseAdmin(), JWT_SECRET, req.body);
    logger.info(`User logged in: ${result.user.phoneNumber}`);
    res.status(200).json(result);
  } catch (error: any) {
    const status = error instanceof AuthError ? error.status : 500;
    if (status === 500) logger.error('Login error:', error);
    res.status(status).json({ error: { message: error.message || 'Login failed', status } });
  }
});

// Refresh token
router.post('/refresh', (req, res) => {
  logger.info('POST /auth/refresh');
  res.status(200).json({
    message: 'Token refresh - to be implemented',
  });
});

// Logout
router.post('/logout', (req, res) => {
  logger.info('POST /auth/logout');
  res.status(200).json({ message: 'Logged out' });
});

export default router;
