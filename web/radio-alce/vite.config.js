import { defineConfig } from 'vite';
import config from './vercel.json' with { type: 'json' };
// Keep the single upstream address in vercel.json; the browser uses HTTPS /radio/stream.
const upstream = new URL(config.rewrites[0].destination);
const proxy = { '/radio/stream': { target: upstream.origin, changeOrigin: true, rewrite: () => upstream.pathname } };
export default defineConfig({ server: { proxy }, preview: { proxy } });
