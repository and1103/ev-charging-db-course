import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const here=path.dirname(fileURLToPath(import.meta.url));
const rows=JSON.parse(await fs.readFile(path.join(here,'render_manifest.json'),'utf8'));
const projectRoot=path.resolve(here,'..','..');
for(const row of rows){
 row.png=path.resolve(projectRoot,row.png);
 const relative=path.relative(projectRoot,row.png);
 if(relative.startsWith('..') || path.isAbsolute(relative) || !row.png.endsWith('.png'))throw new Error('PNG outside second-edition project');
 await fs.access(row.png);
}
if(process.argv.includes('--check')){console.log(JSON.stringify({passed:true,images:rows.length,mode:'read-only image-path check'}));process.exit(0);}
const sharp=require('sharp');
const target=path.resolve(projectRoot,'过程文件','本次整合','图件QA');await fs.mkdir(target,{recursive:true});
for(const kind of [...new Set(rows.map(r=>r.kind))]){
 const entries=rows.filter(r=>r.kind===kind);const width=1200,height=1600;
 const parts=[];
 for(let i=0;i<entries.length;i++){
  const img=await sharp(entries[i].png,{limitInputPixels:false}).resize(width-24,height-24,{fit:'inside',background:'white'}).extend({top:12,bottom:12,left:12,right:12,background:'white'}).png().toBuffer();
  parts.push({input:img,left:(i%3)*width,top:Math.floor(i/3)*height});
 }
 await sharp({create:{width:width*Math.min(3,entries.length),height:height*Math.ceil(entries.length/3),channels:3,background:'white'}}).composite(parts).png().toFile(path.join(target,kind+'.png'));
}
console.log('QA contact sheets generated');
