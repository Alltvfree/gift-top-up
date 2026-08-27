import express from 'express';
import { logger } from '../config/logger';
import { getSupabaseAdmin } from '../config/supabase';
import { AuthError, getProfile } from '../services/authService';

const router = express.Router();

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-me';

// Get user profile
router.get('/profile', async (req, res) => {
  try {
    const profile = await getProfile(getSupabaseAdmin(), JWT_SECRET, req.headers.authorization);
    res.status(200).json(profile);
  } catch (error: any) {
    const status = error instanceof AuthError ? error.status : 500;
    if (status === 500) logger.error('Get profile error:', error);
    res.status(status).json({ error: { message: error.message || 'Failed to load profile', status } });
  }
});

// Update user profile
router.put('/profile', (req, res) => {
  logger.info('PUT /users/profile');
  res.status(200).json({
    message: 'Update user profile - to be implemented',
  });
});

// KYC verification
router.post('/kyc', (req, res) => {
  logger.info('POST /users/kyc');
  res.status(200).json({
    message: 'KYC verification - to be implemented',
  });
});

export default router;
