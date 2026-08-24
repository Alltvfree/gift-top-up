import express from 'express';
import { logger } from '../config/logger';

const router = express.Router();

// Get wallet balance
router.get('/balance', (req, res) => {
  logger.info('GET /wallet/balance');
  res.status(200).json({
    balance: 0,
    currency: 'MVR',
    lastUpdated: new Date(),
  });
});

// Add money to wallet
router.post('/add-money', (req, res) => {
  logger.info('POST /wallet/add-money');
  res.status(200).json({
    message: 'Add money to wallet - to be implemented',
  });
});

// P2P transfer
router.post('/transfer', (req, res) => {
  logger.info('POST /wallet/transfer');
  res.status(200).json({
    message: 'P2P transfer - to be implemented',
  });
});

// Transaction history
router.get('/transactions', (req, res) => {
  logger.info('GET /wallet/transactions');
  res.status(200).json({
    transactions: [],
  });
});

// Withdraw to bank
router.post('/withdraw', (req, res) => {
  logger.info('POST /wallet/withdraw');
  res.status(200).json({
    message: 'Withdraw to bank - to be implemented',
  });
});

export default router;
