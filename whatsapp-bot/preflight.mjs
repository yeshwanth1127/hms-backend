import { pathToFileURL } from 'node:url';
import { readFile, stat } from 'node:fs/promises';
import { extname } from 'node:path';
import { assertProductionConfig } from './production-config.mjs';

async function getJson(url, headers, fetchImpl) {
  const response = await fetchImpl(url, { headers, signal: AbortSignal.timeout(10000), redirect: 'error' });
  if (!response.ok) throw new Error(`${new URL(url).host} returned HTTP ${response.status}`);
  return response.json();
}

export async function runPreflight(env, fetchImpl = fetch) {
  if (env.WA_ENV !== 'production' && env.NODE_ENV !== 'production') {
    throw new Error('Preflight requires WA_ENV=production');
  }
  assertProductionConfig(env);
  const imageStat = await stat(env.WA_WELCOME_IMAGE_PATH);
  if (!imageStat.isFile() || imageStat.size < 1 || imageStat.size > 5 * 1024 * 1024) {
    throw new Error('Approved welcome artwork must be a file under 5 MB');
  }
  const image = await readFile(env.WA_WELCOME_IMAGE_PATH);
  const ext = extname(env.WA_WELCOME_IMAGE_PATH).toLowerCase();
  const png = ext === '.png' && image.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'));
  const jpeg = ['.jpg', '.jpeg'].includes(ext) && image.subarray(0, 3).equals(Buffer.from('ffd8ff', 'hex'));
  if (!(png || jpeg)) {
    throw new Error('Approved welcome artwork must be a PNG or JPEG under 5 MB');
  }
  const root = env.BACKEND_URL.replace(/\/$/, '');
  const auth = { 'X-Service-Key': env.BACKEND_WHATSAPP_SERVICE_KEY };
  const base = `${root}/api/v1/integrations/whatsapp`;
  const ready = await getJson(`${base}/inbound/ready`, auth, fetchImpl);
  if (ready.ready !== true) throw new Error('Backend inbound queue is not ready');
  const catalogue = await getJson(`${base}/catalogue`, auth, fetchImpl);
  const branches = catalogue.branches?.filter((item) => !item.is_virtual) ?? [];
  if (!branches.length || !catalogue.departments?.length) throw new Error('Active clinic branches and specialties are required');
  for (const department of catalogue.departments) {
    if (!department.guide_asset_id) throw new Error(`Specialty ${department.slug} has no approved PDF`);
    const doctors = await getJson(`${base}/doctors?department=${encodeURIComponent(department.slug)}`, auth, fetchImpl);
    if (!doctors.length) throw new Error(`Specialty ${department.slug} has no active doctor`);
    if (doctors.some((doctor) => !doctor.photo_asset_id)) throw new Error(`Specialty ${department.slug} has a doctor without a portrait`);
    if (!doctors.some((doctor) => doctor.branches?.some((branch) => branches.some((active) => active.id === branch.id)))) {
      throw new Error(`Specialty ${department.slug} has no doctor at an active clinic branch`);
    }
  }
  const number = await getJson(
    `https://graph.facebook.com/${env.WA_GRAPH_VERSION}/${env.WA_PHONE_NUMBER_ID}?fields=display_phone_number`,
    { authorization: `Bearer ${env.WA_ACCESS_TOKEN}` }, fetchImpl,
  );
  if (!number.display_phone_number) throw new Error('Meta did not return a registered phone number');
  if (/^\+1[\s()-]*555\b/.test(number.display_phone_number)) {
    throw new Error('Meta test number cannot be used for production');
  }
  return { branches: branches.length, specialties: catalogue.departments.length,
    phoneEnding: number.display_phone_number.replace(/\D/g, '').slice(-4) };
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  runPreflight(process.env).then((result) => {
    console.log(`Production preflight passed: ${result.branches} branches, ${result.specialties} specialties, Meta number ending ${result.phoneEnding}.`);
  }).catch((error) => {
    console.error(`Production preflight failed: ${error.message}`);
    process.exitCode = 1;
  });
}
