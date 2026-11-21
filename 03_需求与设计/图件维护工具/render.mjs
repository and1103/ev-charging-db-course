/** Offline PNG-only Graphviz renderer; layout and intermediate SVG stay in memory. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const sourceDir=path.dirname(fileURLToPath(import.meta.url));
const projectRoot=path.resolve(sourceDir,'..','..');
const manifest=JSON.parse(await fs.readFile(path.join(sourceDir,'render_manifest.json'),'utf8'));
for (const item of manifest) {
  item.png=path.resolve(projectRoot,item.png);
  const target=item.png;
  const relative=path.relative(projectRoot,target);
  if(relative.startsWith('..') || path.isAbsolute(relative) || !target.endsWith('.png'))throw new Error('Image target is outside the second-edition project');
  if(createHash('sha256').update(item.source).digest('hex')!==item.source_sha256)throw new Error('Embedded layout hash mismatch');
  if(process.argv.includes('--check'))await fs.access(target);
}
if(process.argv.includes('--check')){
  console.log(JSON.stringify({passed:true,jobs:manifest.length,mode:'paths and source hashes only; no dependency loading or image writing'}));
  process.exit(0);
}
const {instance}=require('@viz-js/viz');
const sharp=require('sharp');
const viz=await instance();

function icons(svg){
  return svg.replace(/<g id="([^"]+)" class="node">([\s\S]*?)<\/g>/g,(all,id,body)=>{
    const title=body.match(/<title>([^<]+)<\/title>/)?.[1];
    if(!title || !/^(actor_|boundary_|control_|entity_)/.test(title))return all;
    const polygon=body.match(/<polygon[^>]*points="([^"]+)"[^>]*\/>/);
    if(!polygon)return all;
    const pts=polygon[1].trim().split(/\s+/).map(p=>p.split(',').map(Number));
    const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
    const minY=Math.min(...ys),maxY=Math.max(...ys),cx=(Math.min(...xs)+Math.max(...xs))/2;
    const cy=minY+24,stroke='#253343';
    let icon='';
    if(title.startsWith('actor_')){
      icon=`<g fill="none" stroke="${stroke}" stroke-width="1.8"><circle cx="${cx}" cy="${cy-8}" r="8"/><path d="M ${cx} ${cy} v 24 M ${cx-15} ${cy+7} h 30 M ${cx} ${cy+24} l -12 16 M ${cx} ${cy+24} l 12 16"/></g>`;
    }else{
      const r=18; icon=`<circle cx="${cx}" cy="${cy}" r="${r}" fill="white" stroke="${stroke}" stroke-width="1.6"/>`;
      if(title.startsWith('boundary_'))icon+=`<path d="M ${cx-25} ${cy-18} v 36 M ${cx-25} ${cy} h 7" fill="none" stroke="${stroke}" stroke-width="1.6"/>`;
      if(title.startsWith('control_'))icon+=`<path d="M ${cx+9} ${cy-16} l -8 -5 l 1 9" fill="white" stroke="${stroke}" stroke-width="1.6"/>`;
      if(title.startsWith('entity_'))icon+=`<path d="M ${cx-20} ${cy+20} h 40" fill="none" stroke="${stroke}" stroke-width="1.6"/>`;
    }
    body=body.replace(polygon[0],icon);
    // Place the original node name below its UML symbol, without changing edge geometry.
    body=body.replace(/(<text\b[^>]*\by=")[^"]+("[^>]*>)/g,`$1${maxY-4}$2`);
    return `<g id="${id}" class="node">${body}</g>`;
  });
}

const results=[];
for(const item of manifest){
  await fs.mkdir(path.dirname(item.png),{recursive:true});
  const input=item.source;
  if(typeof input!=='string' || !item.png.endsWith('.png'))throw new Error('PNG render job requires embedded layout source');
  const result=viz.render(input,{format:'svg',engine:item.engine || 'dot'});
  if(result.status!=='success')throw new Error(JSON.stringify({file:item.png,errors:result.errors}));
  const svg=icons(result.output);
  const metadata=await sharp(Buffer.from(svg)).metadata();
  const maxDimension=14000;
  const scale=Math.min(1.6,maxDimension/Math.max(metadata.width,metadata.height));
  await sharp(Buffer.from(svg),{density:Math.round(72*scale),limitInputPixels:false})
    .resize({width:8000,height:8000,fit:'inside',withoutEnlargement:true}).png().toFile(item.png);
  results.push({file:item.png,source_sha256:createHash('sha256').update(input).digest('hex'),width:metadata.width,height:metadata.height,warnings:result.errors});
  process.stdout.write(`${item.kind}: ${path.basename(path.dirname(item.png))} ${metadata.width}x${metadata.height}\n`);
}
await fs.writeFile(path.join(sourceDir,'渲染结果.json'),JSON.stringify(results,null,2));
