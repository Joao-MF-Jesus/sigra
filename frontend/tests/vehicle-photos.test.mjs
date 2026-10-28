import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';
import manifest from '../src/features/vehicle-images/vehiclePhotos.json' with { type: 'json' };
import admitted20 from '../../docs/vehicle-photos/ADMITTED20.json' with { type: 'json' };
import { resolveVehiclePhoto } from '../src/features/vehicle-images/vehiclePhotoModel.js';
import { verifyVehiclePhotos } from '../../deploy/vehicle_photo_assets.mjs';

const vehicle = (row) => ({ identity_namespace: 'academic_v6', catalog_id: row.catalogId,
  label: row.label, year_code: row.yearCode, canonical_identity_key: row.canonicalIdentityKey });
const example = manifest.vehicles.find(row => row.imageGroup === 'prisma');
const frontend = new URL('../', import.meta.url);
test('the first twenty admitted photographs and their exact metadata remain unchanged',()=>{
  const preserved=fs.readFileSync(new URL('../../docs/vehicle-photos/ADMITTED20.json',import.meta.url));
  assert.equal(createHash('sha256').update(preserved).digest('hex'),'b9279f6f29c07dd6eb110fae5bcf8bc8470cea0e12f14ac1678e12c127231b93');
  assert.equal(Object.keys(admitted20.photos).length,20);
  for(const [group,photo] of Object.entries(admitted20.photos)) assert.deepEqual(manifest.photos[group],photo,group);
});
test('60 IDs, labels, years, canonical keys and fingerprints exactly match approved plan', () => {
  const raw = gunzipSync(fs.readFileSync(new URL('../../build_inputs/revision6/plan.json.gz', import.meta.url)));
  assert.equal(createHash('sha256').update(raw).digest('hex'), manifest.catalogPlanSha256);
  const rows = JSON.parse(raw).proposal.transport_vehicles;
  assert.equal(rows.length, 60);
  assert.equal(manifest.vehicles.length, 60);
  assert.equal(new Set(manifest.vehicles.map(row => row.catalogId)).size, 60);
  for (const original of rows) {
    const row = manifest.vehicles.find(v => v.catalogId === original.catalog_id);
    assert.deepEqual([row.label,row.yearCode,row.canonicalIdentityKey,row.payloadFingerprint],
      [original.label,original.year_code,original.canonical_identity_key,original.payload_fingerprint]);
  }
});
test('all assets are bounded, complete and pinned; licenses and source are attributable', () => {
  const photos = verifyVehiclePhotos(fileURLToPath(frontend),
    fileURLToPath(new URL('../public/assets/vehicle-photos/', import.meta.url)));
  assert.equal(photos.size, Object.keys(manifest.photos).length * 2);
  for (const photo of Object.values(manifest.photos)) {
    assert.ok(photo.artist && photo.originalSha1 && photo.generation && photo.body);
    assert.ok(photo.sourceRevision.revid);
    assert.match(photo.licenseUrl, /^https:\/\/creativecommons.org\//);
    assert.match(photo.sourcePage, /^https:\/\/commons.wikimedia.org\/wiki\/File:/);
    assert.equal(photo.illustrative, true);
  }
});
test('mapping fails closed for swapped model/year/key/namespace, unknown ID and string IDs', () => {
  const source = vehicle(example);
  assert.equal(resolveVehiclePhoto(source).imageGroup, 'prisma');
  for (const mutation of [{catalog_id:3}, {catalog_id:'2'}, {label:'Chevrolet Cobalt LTZ 2018'},
    {year_code:'2019-5'}, {canonical_identity_key:'different'}, {payload_fingerprint:'different'}, {identity_namespace:'operational_v1'}, {catalog_id:999}]) {
    assert.equal(resolveVehiclePhoto({...source,...mutation}), null);
  }
  assert.equal(resolveVehiclePhoto(null), null);
  assert.equal(resolveVehiclePhoto({brand:'Chevrolet',model:'Anything',year:2018,image_url:'https://untrusted.example/car.jpg'}), null);
});
test('operational ID collision does not select an academic photograph', () => {
  assert.equal(resolveVehiclePhoto({id:2,brand:'Honda',model:'Other',year:2018}), null);
  assert.equal(resolveVehiclePhoto({id:999,brand:'Chevrolet',model:'Prisma LT',year:2018}).imageGroup,'prisma');
  assert.equal(resolveVehiclePhoto({id:2,brand:'Chevrolet',model:'Prisma LT',year:2020}),null);
});
test('all sixty records have photographs and compatible trims share only their reviewed model group', () => {
  assert.equal(Object.keys(manifest.photos).length,53);
  assert.deepEqual(new Set(Object.keys(manifest.photos)),new Set(manifest.vehicles.map(row=>row.imageGroup)));
  for(const row of manifest.vehicles) assert.ok(resolveVehiclePhoto(vehicle(row)),row.label);
  for (const group of ['kicks','wr-v','rio','city','arrizo-5']) {
    const photos=manifest.vehicles.filter(row=>row.imageGroup===group).map(row=>resolveVehiclePhoto(vehicle(row)).variants[0].src);
    assert.ok(photos.length>=2);
    assert.equal(new Set(photos).size,1);
  }
  assert.match(resolveVehiclePhoto(vehicle(manifest.vehicles.find(row=>row.catalogId===10))).body,/hatch/);
  assert.equal(resolveVehiclePhoto({identity_namespace:'academic_v6',catalog_id:69,label:'Grand C4 Picasso'}),null);
  assert.equal(resolveVehiclePhoto({identity_namespace:'academic_v6',catalog_id:80,label:'Focus hatchback'}),null);
  assert.equal(resolveVehiclePhoto({identity_namespace:'academic_v6',catalog_id:94,label:'Tiggo 2 Pro'}),null);
});
