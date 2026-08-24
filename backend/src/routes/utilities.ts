import express from 'express';
import { logger } from '../config/logger';

const router = express.Router();

// Get utility providers
router.get('/providers', (req, res) => {
  logger.info('GET /utilities/providers');
  res.status(200).json({
    providers: [
      {
        id: 'stelco',
        name: 'STELCO',
        type: 'electricity',
        logo: 'https://example.com/stelco.png',
      },
      {
        id: 'mwa',
        name: 'MWA',
        type: 'water',
        logo: 'https://example.com/mwa.png',
      },
    ],
  });
});

// Get utility bill
router.get('/bill/:provider/:accountNumber', (req, res) => {
  logger.info(`GET /utilities/bill/${req.params.provider}/${req.params.accountNumber}`);
  res.status(200).json({
    message: 'Get utility bill - to be implemented',
  });
});

// Pay utility bill
router.post('/pay-bill', (req, res) => {
  logger.info('POST /utilities/pay-bill');
  res.status(200).json({
    message: 'Pay utility bill - to be implemented',
  });
});

// Get bill history
router.get('/history/:provider/:accountNumber', (req, res) => {
  logger.info(`GET /utilities/history/${req.params.provider}/${req.params.accountNumber}`);
  res.status(200).json({
    bills: [],
  });
});

// Set payment reminder
router.post('/reminder', (req, res) => {
  logger.info('POST /utilities/reminder');
  res.status(200).json({
    message: 'Set payment reminder - to be implemented',
  });
});

export default router;
