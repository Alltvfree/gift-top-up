import express from 'express';
import helmet from 'helmet';
import cors from 'cors';
import morgan from 'morgan';
import dotenv from 'dotenv';
import { logger } from './config/logger';
import { initializeDatabase } from './config/database';
import { initializeRedis } from './config/redis';

// Load environment variables
dotenv.config();

// Initialize Express app
const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(helmet());
app.use(cors({
  origin: process.env.CORS_ORIGIN?.split(',') || '*',
  credentials: true,
}));
app.use(morgan('combined', { stream: { write: (message) => logger.info(message) } }));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'OK',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
  });
});

// API Routes (to be implemented)
app.use('/api/v1/auth', require('./routes/auth').default);
app.use('/api/v1/users', require('./routes/users').default);
app.use('/api/v1/wallet', require('./routes/wallet').default);
app.use('/api/v1/telecom', require('./routes/telecom').default);
app.use('/api/v1/utilities', require('./routes/utilities').default);

// Error handling middleware
app.use((err: any, req: express.Request, res: express.Response, next: express.NextFunction) => {
  logger.error('Error:', err);
  res.status(err.status || 500).json({
    error: {
      message: err.message || 'Internal Server Error',
      status: err.status || 500,
    },
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    error: {
      message: 'Route not found',
      status: 404,
    },
  });
});

// Initialize services and start server
async function startServer() {
  try {
    logger.info('Initializing Tilly App Backend...');

    // Initialize database
    logger.info('Connecting to PostgreSQL database...');
    await initializeDatabase();
    logger.info('✓ Database connected');

    // Initialize Redis cache
    logger.info('Connecting to Redis cache...');
    await initializeRedis();
    logger.info('✓ Redis connected');

    // Start server
    app.listen(PORT, () => {
      logger.info(`✓ Server running on http://localhost:${PORT}`);
      logger.info(`✓ API documentation: http://localhost:${PORT}/api/docs`);
      logger.info(`✓ Health check: http://localhost:${PORT}/health`);
    });
  } catch (error) {
    logger.error('Failed to start server:', error);
    process.exit(1);
  }
}

// Handle graceful shutdown
process.on('SIGTERM', () => {
  logger.info('SIGTERM received, shutting down gracefully...');
  process.exit(0);
});

process.on('SIGINT', () => {
  logger.info('SIGINT received, shutting down gracefully...');
  process.exit(0);
});

startServer();
