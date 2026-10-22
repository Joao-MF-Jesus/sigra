// Public build constants only. Runtime credentials never enter VITE_*.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const cwd=fileURLToPath(new URL('../frontend/',import.meta.url));
const result=spawnSync(process.platform==='win32'?'npm.cmd':'npm',['run','build'],{
  cwd,stdio:'inherit',shell:process.platform==='win32',env:{...process.env,
    VITE_API_URL:'/sigra-api',VITE_PUBLIC_DEMO_MODE:'false',VITE_ACADEMIC_TEST_MODE:'false'}
});
if(result.error) throw new Error('FRONTEND_BUILD_PROCESS_FAILED');
process.exitCode=result.status===0?0:1;
