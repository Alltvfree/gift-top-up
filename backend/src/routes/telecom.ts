import express from 'express';
import { logger } from '../config/logger';

const router = express.Router();

// Get available plans
router.get('/plans', (req, res) => {
  logger.info('GET /telecom/plans');
  res.status(200).json({
    plans: [
      {
        id: 'plan-1',
        name: 'Daily Bundle',
        validity: '24 hours',
        price: 5,
        data: '1 GB',
      },
      {
        id: 'plan-2',
        name: 'Weekly Bundle',
        validity: '7 days',
        price: 25,
        data: '5 GB',
      },
    ],
  });
});

// Purchase top-up
router.post('/topup', (req, res) => {
  logger.info('POST /telecom/topup');
  res.status(200).json({
    message: 'Mobile top-up purchase - to be implemented',
  });
});

// Get bill amount
router.get('/bill/:phoneNumber', (req, res) => {
  logger.info(`GET /telecom/bill/${req.params.phoneNumber}`);
  res.status(200).json({
    message: 'Get bill amount - to be implemented',
  });
});

// Pay postpaid bill
router.post('/pay-bill', (req, res) => {
  logger.info('POST /telecom/pay-bill');
  res.status(200).json({
    message: 'Pay postpaid bill - to be implemented',
  });
});

// Check balance
router.get('/balance/:phoneNumber', (req, res) => {
  logger.info(`GET /telecom/balance/${req.params.phoneNumber}`);
  res.status(200).json({
    balance: 0,
    currency: 'MVR',
  });
});

export default router;
