#!/usr/bin/env node
'use strict';
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert');
const {compose,fit,apply,pose,polygon,loadSharp}=require('./compose.cjs');
async function main(){
  const sharp=require(process.argv[2]??'sharp'),root=fs.mkdtempSync(path.join(os.tmpdir(),'slip-join-verify-'));
  const t={x:7,y:-9,scale:1.25,rotation:12};const ps=[[0,0],[10,0],[4,7],[11,8]];
  const f=fit(ps.map(p=>({point:p,target:apply(t,p)})),pose(),true);
  for(const k of Object.keys(t))assert(Math.abs(f.transform[k]-t[k])<1e-8,`fit ${k}`);
  assert(f.rms<1e-8);
  const locked=fit(ps.map(p=>({point:p,target:apply(t,p)})),pose(),false,1.25);assert(locked.rms<1e-8);
  assert.throws(()=>pose({scaleX:1}),/Unsupported/);assert.throws(()=>pose({scale:-1}),/positive/);
  assert.throws(()=>polygon([[0,0],[10,10],[0,10],[10,0]],10,10),/non-collinear|intersecting/);
  const w=16,h=20,a=Buffer.alloc(w*h*4),b=Buffer.alloc(w*h*4);
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){const z=(y*w+x)*4;a[z]=x*9;a[z+1]=y*9;a[z+2]=51;a[z+3]=255;b[z]=150;b[z+1]=x*4;b[z+2]=y*5;b[z+3]=255;}
  const A=path.join(root,'upper.png'),B=path.join(root,'lower.png');await sharp(a,{raw:{width:w,height:h,channels:4}}).png().toFile(A);await sharp(b,{raw:{width:w,height:h,channels:4}}).png().toFile(B);
  const originalA=fs.readFileSync(A),originalB=fs.readFileSync(B);
  const cfg={name:'test',margin:0,pixelsPerUnit:1,pieces:[{id:'A',image:A},{id:'B',image:B,transform:{y:h}}],detail:{x:0,y:17,width:16,height:6,pixelsPerUnit:2}};
  const file=path.join(root,'job.json');fs.writeFileSync(file,JSON.stringify(cfg));const result=await compose(file,path.join(root,'out'),sharp);
  const raw=await sharp(path.join(root,'out','test-transparent.png')).ensureAlpha().raw().toBuffer({resolveWithObject:true});assert.equal(raw.info.width,w);assert.equal(raw.info.height,h*2);assert.deepEqual(raw.data,Buffer.concat([a,b]),'Integer-placed source pixels changed');
  assert.deepEqual(fs.readFileSync(A),originalA);assert.deepEqual(fs.readFileSync(B),originalB);
  const svg=fs.readFileSync(path.join(root,'out','test.svg'),'utf8');const embeds=[...svg.matchAll(/base64,([^" ]+)/g)].map(m=>Buffer.from(m[1],'base64'));assert.deepEqual(embeds,[originalA,originalB],'SVG embedding changed original bytes');
  const detail=await sharp(path.join(root,'out','test-detail.png')).metadata();assert.equal(detail.width,32);assert.equal(detail.height,12);assert.equal(result.overlaps.length,0);
  // A copied job must not depend on the original device's absolute paths.
  const bundle=path.join(root,'project original'),moved=path.join(root,'新設備 moved');fs.mkdirSync(bundle);
  fs.writeFileSync(path.join(bundle,'upper.png'),originalA);fs.writeFileSync(path.join(bundle,'lower.png'),originalB);
  const portable=JSON.parse(JSON.stringify(cfg));portable.pieces[0].image='upper.png';portable.pieces[1].image='lower.png';
  portable.pieces[0].provenance='upper.source.json';
  fs.writeFileSync(path.join(bundle,'upper.source.json'),JSON.stringify({image:'upper.png',imageSha256:require('crypto').createHash('sha256').update(originalA).digest('hex')}));
  fs.writeFileSync(path.join(bundle,'job.json'),JSON.stringify(portable));fs.renameSync(bundle,moved);
  await compose(path.join(moved,'job.json'),path.join(moved,'out'),sharp);
  assert.deepEqual(await sharp(path.join(moved,'out','test-transparent.png')).raw().toBuffer(),raw.data,'Moved relative-path job differs');
  // Resolve a workspace-local module when the skill itself lives elsewhere.
  const moduleDir=path.join(moved,'node_modules','sharp');fs.mkdirSync(moduleDir,{recursive:true});
  fs.writeFileSync(path.join(moduleDir,'index.js'),'module.exports={fixture:true};');
  assert.equal(loadSharp(undefined,path.join(moved,'job.json')).fixture,true);
  cfg.pieces[1].transform.y=15;fs.writeFileSync(file,JSON.stringify(cfg));const overlapped=await compose(file,path.join(root,'overlap'),sharp);assert(overlapped.overlaps[0].estimatedAreaInCanvasUnits>0);assert(fs.existsSync(path.join(root,'overlap','test-reverse-layer-check.png')));
  assert.notDeepEqual(await sharp(path.join(root,'overlap','test.png')).raw().toBuffer(),await sharp(path.join(root,'overlap','test-reverse-layer-check.png')).raw().toBuffer());
  cfg.pieces[0].polygon=[[2,2],[14,2],[8,18]];cfg.pieces=cfg.pieces.slice(0,1);delete cfg.detail;fs.writeFileSync(file,JSON.stringify(cfg));await compose(file,path.join(root,'mask'),sharp);
  const masked=await sharp(path.join(root,'mask','test-transparent.png')).ensureAlpha().raw().toBuffer({resolveWithObject:true});const alpha=(x,y)=>masked.data[(y*masked.info.width+x)*4+3];assert.equal(alpha(0,14),0,'Outside mask should be transparent');assert.equal(alpha(6,4),255,'Inside mask should remain opaque');
  console.log('PASS: similarity and locked-scale fits; invalid transform/mask rejection; unchanged source hashes and SVG bytes; exact integer pixel composition; moved relative-path job and provenance; workspace module resolution; detail geometry; overlap detection and layer diagnostics; alpha clipping.');
  fs.rmSync(root,{recursive:true,force:true});
}
main().catch(e=>{console.error(e);process.exitCode=1;});
