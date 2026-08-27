// Cloudflare Workers entrypoint.
//
// This is a separate, edge-safe entrypoint from src/index.ts (the local
// Express server used for Docker/local development). Express's
// app.listen() model, the raw `pg` driver, Redis, and Winston's file
// transport all depend on Node APIs (TCP sockets, filesystem) that don't
// exist in the Workers runtime, so none of that can run here. This uses
// Hono (a Workers-native router) and talks to the database exclusively
// through the Supabase REST client, which works anywhere `fetch` works.
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { createSupabaseAdmin } from './config/supabase';
import { AuthError, getProfile, loginUser, registerUser } from './services/authService';

type Bindings = {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  JWT_SECRET: string;
};

const app = new Hono<{ Bindings: Bindings }>();

// Auth uses a Bearer token (not cookies), so credentialed CORS isn't
// needed - a wide-open origin is fine, including for the initial
// testing/deployment phase where the exact Pages domain may still change.
app.use('*', cors({ origin: '*' }));

app.get('/health', (c) =>
  c.json({ status: 'OK', timestamp: new Date().toISOString() })
);

// All the actual API routes are defined on this sub-router, relative to
// its own root, then mounted at two different base paths below. This
// makes the Worker tolerant of EXPO_PUBLIC_API_URL being configured
// either as ".../api/v1" or without that suffix - a very easy mismatch
// to introduce via a dashboard text field, and one that otherwise fails
// as a silent-looking 404 with no indication of which side is wrong.
const routes = new Hono<{ Bindings: Bindings }>();

routes.post('/auth/register', async (c) => {
  try {
    const body = await c.req.json();
    const db = createSupabaseAdmin(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY);
    const result = await registerUser(db, c.env.JWT_SECRET, body);
    return c.json(result, 201);
  } catch (error: any) {
    const status = error instanceof AuthError ? error.status : 500;
    if (status === 500) console.error('Register error:', error);
    return c.json({ error: { message: error.message || 'Registration failed', status } }, status);
  }
});

routes.post('/auth/login', async (c) => {
  try {
    const body = await c.req.json();
    const db = createSupabaseAdmin(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY);
    const result = await loginUser(db, c.env.JWT_SECRET, body);
    return c.json(result, 200);
  } catch (error: any) {
    const status = error instanceof AuthError ? error.status : 500;
    if (status === 500) console.error('Login error:', error);
    return c.json({ error: { message: error.message || 'Login failed', status } }, status);
  }
});

routes.post('/auth/refresh', (c) =>
  c.json({ message: 'Token refresh - to be implemented' })
);

routes.post('/auth/logout', (c) => c.json({ message: 'Logged out' }));

routes.get('/users/profile', async (c) => {
  try {
    const db = createSupabaseAdmin(c.env.SUPABASE_URL, c.env.SUPABASE_SERVICE_ROLE_KEY);
    const profile = await getProfile(db, c.env.JWT_SECRET, c.req.header('Authorization'));
    return c.json(profile, 200);
  } catch (error: any) {
    const status = error instanceof AuthError ? error.status : 500;
    if (status === 500) console.error('Get profile error:', error);
    return c.json({ error: { message: error.message || 'Failed to load profile', status } }, status);
  }
});

app.route('/api/v1', routes);
app.route('/', routes);

app.notFound((c) =>
  c.json(
    {
      error: {
        message: `Route not found: ${c.req.method} ${new URL(c.req.url).pathname}`,
        status: 404,
      },
    },
    404
  )
);

app.onError((err, c) => {
  console.error('Unhandled worker error:', err);
  return c.json({ error: { message: 'Internal Server Error', status: 500 } }, 500);
});

export default app;
