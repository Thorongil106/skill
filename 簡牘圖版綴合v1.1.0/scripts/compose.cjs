#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const assert = require('assert');

function fail(message) { throw new Error(message); }
function finite(v, label) { if (typeof v !== 'number' || !Number.isFinite(v)) fail(`${label}: expected finite number`); return v; }
function positive(v, label) { finite(v, label); if (v <= 0) fail(`${label}: must be positive`); return v; }
function point(v, label) { if (!Array.isArray(v) || v.length !== 2) fail(`${label}: expected [x,y]`); return v.map((n, i) => finite(n, `${label}[${i}]`)); }
function escapeXML(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c])); }
function area(points) { return Math.abs(points.reduce((s, p, i) => { const q = points[(i + 1) % points.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0)) / 2; }
function cross(a,b,c) { return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]); }
function onSegment(a,b,p) { return Math.abs(cross(a,b,p)) < 1e-9 && p[0] >= Math.min(a[0],b[0])-1e-9 && p[0] <= Math.max(a[0],b[0])+1e-9 && p[1] >= Math.min(a[1],b[1])-1e-9 && p[1] <= Math.max(a[1],b[1])+1e-9; }
function intersects(a,b,c,d) {
  const x1=cross(a,b,c),x2=cross(a,b,d),x3=cross(c,d,a),x4=cross(c,d,b);
  return (x1*x2<0 && x3*x4<0) || onSegment(a,b,c) || onSegment(a,b,d) || onSegment(c,d,a) || onSegment(c,d,b);
}
function polygon(p, width, height) {
  let a = p ? p.map((q,i)=>point(q,`polygon ${i}`)) : [[0,0],[width,0],[width,height],[0,height]];
  if (a.length > 1 && a[0][0] === a.at(-1)[0] && a[0][1] === a.at(-1)[1]) a.pop();
  if (a.length < 3 || area(a)<1e-6) fail('Polygon needs at least 3 non-collinear points');
  for (const [x,y] of a) if(x<0 || y<0 || x>width || y>height) fail('Polygon exceeds image bounds');
  for(let i=0;i<a.length;i++) for(let j=i+1;j<a.length;j++) {
    if(j===i+1 || (i===0 && j===a.length-1)) continue;
    if(intersects(a[i],a[(i+1)%a.length],a[j],a[(j+1)%a.length])) fail('Self-intersecting polygon');
  }
  return a;
}
function pose(t={}) {
  for(const k of Object.keys(t)) if(!['x','y','scale','rotation'].includes(k)) fail(`Unsupported transform key: ${k}`);
  return {x:finite(t.x??0,'x'),y:finite(t.y??0,'y'),scale:positive(t.scale??1,'scale'),rotation:finite(t.rotation??0,'rotation')};
}
function matrix(t) { const a=t.rotation*Math.PI/180; return [t.scale*Math.cos(a),t.scale*Math.sin(a),-t.scale*Math.sin(a),t.scale*Math.cos(a),t.x,t.y]; }
function apply(t,p) { const [a,b,c,d,x,y]=matrix(t); return [a*p[0]+c*p[1]+x,b*p[0]+d*p[1]+y]; }
function fit(pairs, reference, fitScale, lockedScale=1) {
  if (!Array.isArray(pairs) || pairs.length<2) fail('Alignment requires at least two landmark pairs');
  const src=pairs.map((p,i)=>point(p.point,`pair ${i} point`));
  const dst=pairs.map((p,i)=>apply(reference,point(p.target,`pair ${i} target`)));
  const mean=a=>a.reduce((s,p)=>[s[0]+p[0]/a.length,s[1]+p[1]/a.length],[0,0]);
  const u=mean(src),v=mean(dst); let dot=0,det=0,den=0;
  for(let i=0;i<src.length;i++){const x=src[i][0]-u[0],y=src[i][1]-u[1],X=dst[i][0]-v[0],Y=dst[i][1]-v[1];dot+=x*X+y*Y;det+=x*Y-y*X;den+=x*x+y*y;}
  if(den<1e-9 || Math.hypot(dot,det)<1e-9) fail('Degenerate alignment landmarks');
  const theta=Math.atan2(det,dot),s=fitScale?Math.hypot(dot,det)/den:positive(lockedScale,'locked alignment scale');
  const t={scale:s,rotation:theta*180/Math.PI,x:v[0]-s*(Math.cos(theta)*u[0]-Math.sin(theta)*u[1]),y:v[1]-s*(Math.sin(theta)*u[0]+Math.cos(theta)*u[1])};
  const errors=src.map((p,i)=>{const q=apply(t,p);return Math.hypot(q[0]-dst[i][0],q[1]-dst[i][1]);});
  return {transform:t,landmarkCount:pairs.length,residuals:errors,rms:Math.sqrt(errors.reduce((s,e)=>s+e*e,0)/errors.length),note:pairs.length===2?'Two pairs determine a fit; zero residual is not independent evidence.':'Residuals quantify chosen landmarks only, not physical join validity.'};
}
function pointString(p) { return p.map(q=>q.join(',')).join(' '); }
function bbox(points) { const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]); return {x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)}; }
function fragmentSVG(p,i) { return `<g transform="matrix(${matrix(p.transform).join(' ')})"><defs><clipPath id="clip${i}" clipPathUnits="userSpaceOnUse"><polygon points="${pointString(p.polygon)}"/></clipPath></defs><image x="0" y="0" width="${p.width}" height="${p.height}" href="${p.uri}" clip-path="url(#clip${i})"/></g>`; }
function svgDocument(pieces,view,ppu,background=null) {
  const width=Math.max(1,Math.ceil(view.width*ppu)),height=Math.max(1,Math.ceil(view.height*ppu));
  if(width*height>40000000) fail('Output exceeds 40 megapixels; reduce pixelsPerUnit or detail crop');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${view.x} ${view.y} ${view.width} ${view.height}">${background?`<rect x="${view.x}" y="${view.y}" width="${view.width}" height="${view.height}" fill="${escapeXML(background)}"/>`:''}${pieces.map(fragmentSVG).join('')}</svg>`;
}
async function compose(configPath,outDir,sharp,{overwrite=false}={}) {
  const config=JSON.parse(fs.readFileSync(configPath,'utf8')),root=path.dirname(path.resolve(configPath));
  if(!Array.isArray(config.pieces)||config.pieces.length<1) fail('pieces must be a nonempty array');
  const name=config.name??'join'; if(!/^[\p{L}\p{N}_.-]+$/u.test(name)||name==='.'||name==='..') fail('Invalid output name');
  const ppu=positive(config.pixelsPerUnit??3,'pixelsPerUnit'),margin=finite(config.margin??12,'margin');if(margin<0) fail('margin must be nonnegative');
  const pieces=[],seen=new Set();
  for(const raw of config.pieces) {
    if(!raw.id || seen.has(raw.id)) fail('Every piece needs a unique id');seen.add(raw.id);
    const file=path.resolve(root,raw.image),data=fs.readFileSync(file),m=await sharp(data).metadata();
    if(!m.width||!m.height) fail(`Cannot read image dimensions: ${file}`);
    if(m.pages && m.pages>1) fail('Extract a single page before composing multipage images');
    if(m.orientation && m.orientation!==1) fail('EXIF-oriented image: make an explicit oriented working copy first');
    let embedded=data,mime=m.format==='jpeg'?'image/jpeg':'image/png',transcoded=false;
    if(!['jpeg','png'].includes(m.format)){embedded=await sharp(data).png().toBuffer();transcoded=true;}
    const p={id:raw.id,label:raw.label??raw.id,image:file,width:m.width,height:m.height,sha256:crypto.createHash('sha256').update(data).digest('hex'),transcodedToPng:transcoded,polygon:polygon(raw.polygon,m.width,m.height),uri:`data:${mime};base64,${embedded.toString('base64')}`};
    if(raw.provenance){
      const provenanceFile=path.resolve(root,raw.provenance),source=JSON.parse(fs.readFileSync(provenanceFile,'utf8'));
      if(source.imageSha256!==p.sha256)fail('PDF crop provenance hash does not match image');
      if(path.resolve(path.dirname(provenanceFile),source.image)!==file)fail('PDF crop provenance references a different image');
      p.provenance={...source,recordPath:provenanceFile};
    }
    if(raw.align && raw.transform) fail('Use either align or transform, not both');
    if(raw.align){const ref=pieces.find(p=>p.id===raw.align.to);if(!ref) fail('Alignment reference must precede this piece');
      for(const pair of raw.align.pairs??[]){const a=point(pair.point,'point'),b=point(pair.target,'target');if(a[0]<0||a[1]<0||a[0]>p.width||a[1]>p.height||b[0]<0||b[1]<0||b[0]>ref.width||b[1]>ref.height) fail('Landmark outside source image');}
      if(raw.align.fitScale!==undefined && typeof raw.align.fitScale!=='boolean') fail('fitScale must be boolean');
      p.alignment=fit(raw.align.pairs,ref.transform,raw.align.fitScale??false,raw.align.scale??1);p.transform=p.alignment.transform;
    } else p.transform=pose(raw.transform);
    pieces.push(p);
  }
  const b=bbox(pieces.flatMap(p=>p.polygon.map(q=>apply(p.transform,q))));
  const view={x:b.x-margin,y:b.y-margin,width:b.width+2*margin,height:b.height+2*margin};
  const targets=['.svg','.png','-transparent.png','-source-check.png','-manifest.json','-parameters.json','-reverse-layer-check.png'];if(config.detail)targets.push('-detail.png');
  for(const suffix of targets){const dest=path.resolve(outDir,name+suffix);if(pieces.some(p=>dest===p.image))fail('Output would overwrite a source image');if(fs.existsSync(dest)&&!overwrite)fail(`Output exists: ${dest}; choose a new name or --overwrite for your own outputs`);}
  fs.mkdirSync(outDir,{recursive:true});const output=suffix=>path.join(outDir,name+suffix);
  const svg=svgDocument(pieces,view,ppu),bg=config.background??'#ffffff';
  fs.writeFileSync(output('.svg'),svg);
  await sharp(Buffer.from(svg)).png().toFile(output('-transparent.png'));
  await sharp(Buffer.from(svgDocument(pieces,view,ppu,bg))).png().toFile(output('.png'));
  if(config.detail){const d=config.detail;const v={x:finite(d.x,'detail.x'),y:finite(d.y,'detail.y'),width:positive(d.width,'detail.width'),height:positive(d.height,'detail.height')};await sharp(Buffer.from(svgDocument(pieces,v,positive(d.pixelsPerUnit??ppu*2,'detail.pixelsPerUnit'),bg))).png().toFile(output('-detail.png'));}
  // A source sheet shows the complete uncut originals with independent mask outlines.
  let cx=12;const groups=[];for(const p of pieces){groups.push(`<g transform="translate(${cx} 36)"><text x="0" y="-14" font-size="9" font-family="sans-serif">${escapeXML(p.label)}</text><image width="${p.width}" height="${p.height}" href="${p.uri}"/><polygon points="${pointString(p.polygon)}" fill="none" stroke="#d52222" stroke-width="0.6"/></g>`);cx+=p.width+18;}
  const sh=Math.max(...pieces.map(p=>p.height))+50;const sourceSvg=`<svg xmlns="http://www.w3.org/2000/svg" width="${Math.ceil(cx*2)}" height="${Math.ceil(sh*2)}" viewBox="0 0 ${cx} ${sh}"><rect width="100%" height="100%" fill="white"/>${groups.join('')}</svg>`;
  await sharp(Buffer.from(sourceSvg)).png().toFile(output('-source-check.png'));
  // Raster sampling measures only transformed mask overlap, including original alpha.
  const samplePPU=Math.min(1,2048/Math.max(view.width,view.height));const maskBuffers=[];let maskWidth=0,maskHeight=0;
  for(const p of pieces){const {data,info}=await sharp(Buffer.from(svgDocument([p],view,samplePPU))).ensureAlpha().raw().toBuffer({resolveWithObject:true});maskBuffers.push(data);maskWidth=info.width;maskHeight=info.height;}
  const overlaps=[];for(let i=0;i<pieces.length;i++)for(let j=i+1;j<pieces.length;j++){let n=0;for(let z=3;z<maskBuffers[i].length;z+=4)if(maskBuffers[i][z]>127&&maskBuffers[j][z]>127)n++;if(n)overlaps.push({pieces:[pieces[i].id,pieces[j].id],estimatedAreaInCanvasUnits:n/(samplePPU*samplePPU)});}
  if(overlaps.length)await sharp(Buffer.from(svgDocument([...pieces].reverse(),view,ppu,bg))).png().toFile(output('-reverse-layer-check.png'));
  else if(overwrite&&fs.existsSync(output('-reverse-layer-check.png')))fs.unlinkSync(output('-reverse-layer-check.png'));
  const manifest={schema:1,title:config.title??name,createdAt:new Date().toISOString(),method:'Source-image embedding; independent polygon clipping; orientation-preserving uniform similarity transforms. No generative editing, inpainting, local deformation, or stroke reconstruction.',resampling:'PNG rendering may resample transformed images; embedded original PNG/JPEG bytes remain unchanged.',view,pixelsPerUnit:ppu,pieces:pieces.map(({uri,...p})=>p),overlapSampling:{pixelsPerUnit:samplePPU,width:maskWidth,height:maskHeight,overlaps},notes:config.notes??[]};
  fs.writeFileSync(output('-manifest.json'),JSON.stringify(manifest,null,2));
  fs.writeFileSync(output('-parameters.json'),JSON.stringify({...config,pieces:config.pieces.map((p,i)=>({...p,image:pieces[i].image,...(pieces[i].provenance?{provenance:pieces[i].provenance.recordPath}:{})}))},null,2));
  for(const p of pieces)assert.strictEqual(crypto.createHash('sha256').update(fs.readFileSync(p.image)).digest('hex'),p.sha256,'Source changed during operation');
  return {name,view,overlaps,outputs:targets.filter(s=>fs.existsSync(output(s))).map(s=>path.resolve(output(s)))};
}
function loadSharp(explicit,configPath){
  if(explicit)return require(path.isAbsolute(explicit)?explicit:path.resolve(explicit));
  const roots=[configPath?path.dirname(path.resolve(configPath)):process.cwd(),process.cwd(),__dirname];
  try{return require(require.resolve('sharp',{paths:roots}));}
  catch(error){throw new Error('Cannot load sharp. Use an existing installation via --sharp-module, or install the skill package dependencies with npm install. '+error.message);}
}
function cli(){const args={};for(let i=2;i<process.argv.length;i++){const key=process.argv[i];if(key==='--overwrite')args.overwrite=true;else if(['--config','--out-dir','--sharp-module'].includes(key)){if(!process.argv[i+1])fail(`Missing value for ${key}`);args[key]=process.argv[++i];}else fail(`Unknown option: ${key}`);}if(!args['--config']||!args['--out-dir'])fail('Usage: node compose.cjs --config job.json --out-dir output [--sharp-module path] [--overwrite]');const sharp=loadSharp(args['--sharp-module'],args['--config']);return compose(args['--config'],args['--out-dir'],sharp,args);}
module.exports={compose,pose,apply,fit,polygon,loadSharp};
if(require.main===module)cli().then(r=>console.log(JSON.stringify(r,null,2))).catch(e=>{console.error(e.message);process.exitCode=1;});
