import { createClient } from 'redis';
import { logger } from './logger';

const redisClient = createClient({
  url: process.env.REDIS_URL || 'redis://localhost:6379',
});

redisClient.on('error', (err) => logger.error('Redis Client Error', err));
redisClient.on('connect', () => logger.info('Redis Client Connected'));
redisClient.on('ready', () => logger.info('Redis Client Ready'));

export async function initializeRedis(): Promise<void> {
  try {
    await redisClient.connect();
    const ping = await redisClient.ping();
    logger.info(`Redis ping: ${ping}`);
  } catch (error) {
    logger.error('Failed to connect to Redis:', error);
    throw error;
  }
}

export async function redisGet(key: string): Promise<string | null> {
  try {
    return await redisClient.get(key);
  } catch (error) {
    logger.error(`Redis GET error for key ${key}:`, error);
    return null;
  }
}

export async function redisSet(
  key: string,
  value: string,
  expirySeconds?: number,
): Promise<boolean> {
  try {
    if (expirySeconds) {
      await redisClient.setEx(key, expirySeconds, value);
    } else {
      await redisClient.set(key, value);
    }
    return true;
  } catch (error) {
    logger.error(`Redis SET error for key ${key}:`, error);
    return false;
  }
}

export async function redisDel(key: string): Promise<boolean> {
  try {
    const result = await redisClient.del(key);
    return result > 0;
  } catch (error) {
    logger.error(`Redis DEL error for key ${key}:`, error);
    return false;
  }
}

export async function closeRedis(): Promise<void> {
  await redisClient.quit();
  logger.info('Redis connection closed');
}

export default redisClient;
