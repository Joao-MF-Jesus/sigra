import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

// Public photos are a separate, bounded asset plane. They are not required by
// Python's exact application-file manifest or allowed into its Function.
export function verifyVehiclePhotos(frontend, source) {
  const manifest = JSON.parse(fs.readFileSync(path.join(frontend, 'src/features/vehicle-images/vehiclePhotos.json'), 'utf8'));
  if (manifest.schema !== 'sigra-static-vehicle-photos-v1') throw new Error('PHOTO_MANIFEST_SCHEMA_DIFFERS');
  const expected = new Map();
  for (const photo of Object.values(manifest.photos)) for (const image of photo.variants) {
    const prefix = '/assets/vehicle-photos/', name = image.src.slice(prefix.length);
    if (!image.src.startsWith(prefix) || !/^[a-z0-9-]+-[a-f0-9]{12}\.webp$/.test(name)
        || expected.has(name) || image.bytes < 1 || image.bytes > 300000) throw new Error('PHOTO_PATH_OR_SIZE_DIFFERS');
    const file = path.join(source, name), stat = fs.lstatSync(file), bytes = fs.readFileSync(file);
    if (stat.isSymbolicLink() || !stat.isFile() || stat.size !== image.bytes
        || createHash('sha256').update(bytes).digest('hex') !== image.sha256
        || bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WEBP') throw new Error('PHOTO_BYTES_DIFFER');
    expected.set(name, image.sha256);
  }
  if (fs.lstatSync(source).isSymbolicLink() || fs.readdirSync(source).sort().join('\n') !== [...expected.keys()].sort().join('\n')) {
    throw new Error('PHOTO_FILE_SET_DIFFERS');
  }
  return expected;
}
