import {mkdir,copyFile,readFile,readdir,writeFile,lstat} from 'node:fs/promises';
import {zipSync} from 'fflate';
const dest = new URL('../public/python/', import.meta.url);
await mkdir(dest,{recursive:true});
for (const name of ['workbench.py', 'experiment.py', 'paper.py']) {
  await copyFile(new URL('../python/'+name,import.meta.url), new URL(name,dest));
}
const packageRoot = new URL('../python/aquap2py/',import.meta.url);
const files = {};
async function collect(directory, prefix) {
  for (const name of (await readdir(directory)).sort()) {
    if (name === '__pycache__' || name.startsWith('.')) continue;
    const url = new URL(name,directory), stat = await lstat(url);
    if (stat.isSymbolicLink()) throw new Error('Package source must not contain links');
    if (stat.isDirectory()) await collect(new URL(name+'/',directory),prefix+name+'/');
    else if (/\.(py|json|md)$/.test(name) || name === 'LICENSE') files[prefix+name] = new Uint8Array(await readFile(url));
  }
}
await collect(packageRoot,'aquap2py/');
for (const name of ['__init__.py','coverage.json','LICENSE','NOTICE.md']) if (!files['aquap2py/'+name]) throw new Error('Missing aquap2py source: '+name);
await writeFile(new URL('aquap2py.zip',dest),zipSync(files,{level:9,mtime:new Date('2026-01-01T00:00:00Z')}));

