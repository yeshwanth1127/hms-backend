import { isAbsolute } from 'node:path';
import { existsSync, realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const bundledDemoImage = fileURLToPath(new URL('./welcome.png', import.meta.url));

export function assertProductionConfig(env) {
  if (env.WA_ENV !== 'production' && env.NODE_ENV !== 'production') return;
  const fail = (reason) => { throw new Error(`Unsafe production WhatsApp configuration: ${reason}`); };
  if (env.WA_MODE !== 'backend') fail('WA_MODE must be backend');
  if (env.WA_CLINIC_READY !== 'true') fail('WA_CLINIC_READY must be true after clinic data approval');
  if (env.WA_LIVE_NUMBER_CONFIRMED !== 'true') fail('WA_LIVE_NUMBER_CONFIRMED must be true after checking the registered phone');
  if (!/^https:\/\/[^/]+/.test(env.BACKEND_URL ?? '')) fail('BACKEND_URL must use HTTPS');
  for (const name of ['WA_VERIFY_TOKEN', 'WA_APP_SECRET', 'WA_ACCESS_TOKEN', 'BACKEND_WHATSAPP_SERVICE_KEY']) {
    const value = env[name] ?? '';
    if (value.length < 32 || /^(replace|dev-|test-|changeme)/i.test(value)) fail(`${name} must be a production secret`);
  }
  if (!/^\d+$/.test(env.WA_PHONE_NUMBER_ID ?? '')) fail('WA_PHONE_NUMBER_ID must be numeric');
  if (!/^v\d+\.\d+$/.test(env.WA_GRAPH_VERSION ?? '')) fail('WA_GRAPH_VERSION is required');
  const image = env.WA_WELCOME_IMAGE_PATH;
  if (!image || !isAbsolute(image) || !existsSync(image) || realpathSync(image) === bundledDemoImage) {
    fail('WA_WELCOME_IMAGE_PATH must be an existing, approved absolute path');
  }
  if (env.WA_BIND_HOST && !['127.0.0.1', '0.0.0.0', '::1', '::'].includes(env.WA_BIND_HOST)) {
    fail('WA_BIND_HOST must be a local or container bind address');
  }
}
