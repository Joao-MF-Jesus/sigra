// Public build constants only. Runtime credentials never enter VITE_*.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import { verifyVehiclePhotos } from './vehicle_photo_assets.mjs';
const cwd=fileURLToPath(new URL('../frontend/',import.meta.url));
const localPhotos=path.join(cwd,'public/assets/vehicle-photos');
const photos=fs.existsSync(localPhotos)?localPhotos:path.resolve(cwd,'../../public-assets/vehicle-photos');
verifyVehiclePhotos(cwd, photos);
const result=spawnSync(process.platform==='win32'?'npm.cmd':'npm',['run','build'],{
  cwd,stdio:'inherit',shell:process.platform==='win32',env:{...process.env,
    VITE_API_URL:'/sigra-api',VITE_PUBLIC_DEMO_MODE:'false',VITE_ACADEMIC_TEST_MODE:'false'}
});
if(result.error) throw new Error('FRONTEND_BUILD_PROCESS_FAILED');
process.exitCode=result.status===0?0:1;
if (result.status===0) {
  const destination=path.join(cwd,'dist/assets/vehicle-photos');
  fs.mkdirSync(destination,{recursive:true});
  for (const name of fs.readdirSync(photos)) fs.copyFileSync(path.join(photos,name),path.join(destination,name));
  verifyVehiclePhotos(cwd,destination);
}
