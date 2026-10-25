import {createRequire} from 'node:module';
import {existsSync} from 'node:fs';
import path from 'node:path';
try {
  const require=createRequire(process.argv[2]);
  const {chromium}=require('playwright');
  const version=require('playwright/package.json').version;
  const executable=chromium.executablePath();
  const cli=path.join(path.dirname(require.resolve('playwright/package.json')),'cli.js');
  process.stdout.write(JSON.stringify({ready:true,version,cli,chromium_executable:executable,chromium_installed:existsSync(executable)}));
} catch {
  process.stdout.write(JSON.stringify({ready:false}));
}
