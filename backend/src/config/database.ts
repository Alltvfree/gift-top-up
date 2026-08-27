import { Pool, PoolClient } from 'pg';
import { logger } from './logger';

const pool = new Pool({
  user: process.env.DB_USER || 'tilly_user',
  password: process.env.DB_PASSWORD,
  host: process.env.DB_HOST || 'localhost',
  port: parseInt(process.env.DB_PORT || '5432'),
  database: process.env.DB_NAME || 'tilly_app',
});

// Connection event handlers
pool.on('error', (err: Error) => {
  logger.error('Unexpected error on idle client', err);
});

pool.on('connect', () => {
  logger.debug('New client connected to database');
});

pool.on('remove', () => {
  logger.debug('Client removed from pool');
});

export async function initializeDatabase(): Promise<void> {
  try {
    const client = await pool.connect();
    const result = await client.query('SELECT NOW()');
    client.release();
    logger.info(`Database connected at ${result.rows[0].now}`);
  } catch (error) {
    logger.error('Failed to connect to database:', error);
    throw error;
  }
}

export async function query(text: string, params?: any[]): Promise<any> {
  const start = Date.now();
  try {
    const result = await pool.query(text, params);
    const duration = Date.now() - start;
    logger.debug(`Executed query in ${duration}ms`);
    return result;
  } catch (error) {
    logger.error('Database query error:', error);
    throw error;
  }
}

export async function getClient(): Promise<PoolClient> {
  return pool.connect();
}

export async function closeDatabase(): Promise<void> {
  await pool.end();
  logger.info('Database connection pool closed');
}

export default pool;
