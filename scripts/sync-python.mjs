import {mkdir,copyFile} from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const dest = new URL('../public/python/', import.meta.url);
await mkdir(dest,{recursive:true});
try{await copyFile(new URL('../python/workbench.py',import.meta.url), new URL('workbench.py',dest));}catch(e){if(e.code!=='ENOENT')throw e;}

