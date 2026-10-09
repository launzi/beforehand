import {writeFile,mkdir,cp,rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {matchPatterns} from '../core/shops.js';
const root=new URL('../',import.meta.url);
export function manifestFor(target) {
 if(target!=='store') throw new Error('Unknown target');
 return {manifest_version:3,name:'beforehand',version:'1.4.2',minimum_chrome_version:'116',
 description:"See what the product you're viewing costs from Korea, delivered. Sends only the product name, brand and your country.",
 permissions:['storage'],host_permissions:[...matchPatterns(),'https://concierge.youngji.kim/*'],
 background:{service_worker:'background.js',type:'module'},
 content_scripts:[{matches:matchPatterns(),js:['core/extract.js','core/card.js','content.js'],run_at:'document_idle'}],
 action:{default_popup:'popup.html',default_title:'beforehand',default_icon:{16:'icons/16.png',32:'icons/32.png'}},
 icons:{16:'icons/16.png',32:'icons/32.png',48:'icons/48.png',128:'icons/128.png'},options_page:'options.html',
 content_security_policy:{extension_pages:"script-src 'self'; object-src 'none'; connect-src https://concierge.youngji.kim"}};
}
const SHIP=['background.js','content.js','checkout.html','checkout.js','welcome.html','welcome.js','popup.html','popup.js','options.html','options.js','style.css','core','icons','LICENSE','NOTICE','PRIVACY.md'];
export async function build(target='store') {
 const manifest=manifestFor(target);
 execFileSync('zip',['-v'],{stdio:'ignore'});
 const out=new URL('dist/store/',root);
 await rm(out,{recursive:true,force:true}); await mkdir(out,{recursive:true});
 for(const file of SHIP) await cp(new URL(file,root),new URL(file,out),{recursive:true,filter:src=>!src.endsWith('.md') || src.endsWith('/PRIVACY.md')});
 await writeFile(new URL('manifest.json',out),JSON.stringify(manifest,null,2)+'\n');
 const stamp=new Date().toISOString().replace(/[-:]/g,'').replace('T','-').slice(0,15);
 const zip=new URL(`dist/beforehand-store-${stamp}.zip`,root);
 execFileSync('zip',['-r','-X',fileURLToPath(zip),'.'],{cwd:fileURLToPath(out),stdio:'ignore'});
 return {directory:fileURLToPath(out),zip:fileURLToPath(zip)};
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
 console.log(await build(process.argv[2] ?? 'store'));
}
