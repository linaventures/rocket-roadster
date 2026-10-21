// Visually informed by the public Sketchfab viewer. No third-party mesh or textures.
// node reference-pass.mjs <studio-pass.glb> <output-directory>
import {NodeIO} from '@gltf-transform/core';
import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
import {prune, draco} from '@gltf-transform/functions';
import draco3d from 'draco3dgltf';
import {writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
const [input,out]=process.argv.slice(2);
if(!input||!out)throw Error('Expected input.glb output-directory');
const io=new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
 'draco3d.decoder':await draco3d.createDecoderModule(),'draco3d.encoder':await draco3d.createEncoderModule()
});
const doc=await io.read(input),root=doc.getRoot(),buffer=root.listBuffers()[0];
const mats=new Map(root.listMaterials().map(m=>[m.getName(),m]));
for(const name of ['Fascia','SideGlass'])mats.set(name,doc.createMaterial(name));
mats.get('Fascia').setBaseColorFactor([.025,.032,.044,1]).setRoughnessFactor(.42).setMetallicFactor(.3);
mats.get('SideGlass').setBaseColorFactor([.025,.03,.04,.97]).setRoughnessFactor(.2).setMetallicFactor(.2);
const normalize=n=>{const l=Math.hypot(...n)||1;return n.map(v=>v/l);};
const cross=(a,b,c)=>{const u=b.map((v,i)=>v-a[i]),v=c.map((v,i)=>v-a[i]);return normalize([u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]);};
function clip(poly,field,positive=true){
 const result=[];
 for(let i=0;i<poly.length;i++){
  const a=poly[i],b=poly[(i+1)%poly.length],fa=field(a.p),fb=field(b.p);
  const ia=positive?fa>=0:fa<=0,ib=positive?fb>=0:fb<=0;
  if(ia)result.push(a);
  if(ia!==ib){let lo=0,hi=1;for(let k=0;k<22;k++){const t=(lo+hi)/2;const p=a.p.map((v,j)=>v+(b.p[j]-v)*t);if((field(p)>=0)===(fa>=0))lo=t;else hi=t;}
   const t=(lo+hi)/2;result.push({p:a.p.map((v,j)=>v+(b.p[j]-v)*t),n:normalize(a.n.map((v,j)=>v+(b.n[j]-v)*t))});
  }
 }return result;
}
const nodes=root.listNodes().filter(n=>/^(Body|Door[01])$/.test(n.getName()));
const original=[];
for(const node of nodes){const offset=node.getTranslation();
 for(const prim of node.getMesh().listPrimitives()){
  const pos=prim.getAttribute('POSITION'),norm=prim.getAttribute('NORMAL'),ix=prim.getIndices().getArray();
  for(let i=0;i<ix.length;i+=3)original.push({node,mat:prim.getMaterial().getName(),v:[0,1,2].map(k=>({p:pos.getElement(ix[i+k],[]).map((v,j)=>v+offset[j]),n:norm.getElement(ix[i+k],[])}))});
 }
}
function topHit(x,z){let hit=-Infinity;
 for(const {node,v} of original){if(node.getName()!=='Body')continue;const [a,b,c]=v.map(v=>v.p);
  if(x<Math.min(a[0],b[0],c[0])||x>Math.max(a[0],b[0],c[0])||z<Math.min(a[2],b[2],c[2])||z>Math.max(a[2],b[2],c[2]))continue;
  const den=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2]);if(Math.abs(den)<1e-10)continue;
  const u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/den,vv=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/den;
  if(u<0||vv<0||u+vv>1)continue;hit=Math.max(hit,u*a[1]+vv*b[1]+(1-u-vv)*c[1]);
 }return hit;
}
// Half-width of the original body at (x, y): the widest side hit. Used to fit the rear beam to the retopo body.
function sideHit(x,y){let hit=0;
 for(const {node,v} of original){if(node.getName()!=='Body')continue;const [a,b,c]=v.map(v=>v.p);
  if(x<Math.min(a[0],b[0],c[0])||x>Math.max(a[0],b[0],c[0])||y<Math.min(a[1],b[1],c[1])||y>Math.max(a[1],b[1],c[1]))continue;
  const den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(den)<1e-10)continue;
  const u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den,vv=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den;
  if(u<0||vv<0||u+vv>1)continue;hit=Math.max(hit,Math.abs(u*a[2]+vv*b[2]+(1-u-vv)*c[2]));
 }return hit;
}
const backX=-1.70,width=.895;
const backLine=[];
const fasciaTop=[];
for(let i=0;i<=64;i++){
 const z=(i/64*2-1)*width,y=topHit(backX,z);
 if(!Number.isFinite(y))throw Error('No hood surface at '+z);
 const corner=Math.max(0,(Math.abs(z)-.64)/(width-.64));
 backLine.push([backX,y,z]);
 fasciaTop.push([-2.315+corner*.615,.44+corner*(y-.44),z]);
}
const railKeys=[[-1.25,.845],[-1.0,.76],[-.65,.665],[-.25,.618],[.35,.609],[.85,.59],[1.25,.52],[1.5,.43]];
function rail(x){for(let i=1;i<railKeys.length;i++)if(x<=railKeys[i][0]){const [a,b]=[railKeys[i-1],railKeys[i]];return a[1]+(b[1]-a[1])*Math.max(0,(x-a[0])/(b[0]-a[0]));}return railKeys.at(-1)[1];}
// Wheel arches and the sill band's ends, from the model's own anchors.
const anchorExtras=root.listNodes().find(n=>n.getName()==='Anchors').getExtras();
const archAxles=anchorExtras.axleX,archY=anchorExtras.wheelR||.345,archR=anchorExtras.archR||.395;
// The retopo body (finish_roadster.py --prealigned) records archR: its arches are exact, so the lip fix is skipped.
const exactArches=anchorExtras.archR!==undefined,fasciaArchR=anchorExtras.archR||.378;
const sillX0=archAxles[0]+archR-.02,sillX1=archAxles[1]-archR+.02;
const groups=new Map(nodes.map(n=>[n,new Map()]));
let removed=0;
function emit(node,mat,poly){
 if(poly.length<3)return;
 const map=groups.get(node);if(!map.has(mat))map.set(mat,[]);
 for(let i=1;i<poly.length-1;i++)map.get(mat).push(poly[0],poly[i],poly[i+1]);
}
for(const {node,mat,v} of original){
 let poly=v;
 const center=v[0].p.map((_,j)=>v.reduce((s,p)=>s+p.p[j],0)/3);
 if(node.getName()==='Body'&&poly.some(v=>v.p[0]<backX)){
  // Rebuild the nose as a broad, straight leading edge and two swept corners.
  emit(node,mat,clip(poly,p=>p[0]-backX,true));removed++;
  continue;
 }
 if(node.getName()==='Body'&&poly.some(v=>v.p[0]>1.98)){
  emit(node,mat,clip(poly,p=>p[0]-1.98,false));
  emit(node,mat,clip(clip(poly,p=>p[0]-1.98,true),p=>p[1]-.875,true));
  continue;
 }
 // (The painted "rail" that split roof and side glass was removed on 19 Oct: it followed a width
 // contour that cut through the side windows and left slivers. The glass stays one clean canopy.)
 // Arch lips: leftover dark faces fringe the arch edges. Outside the arch circle, on the outer
 // body side, trim becomes paint, clipped exactly along the circle so the lip edge is clean.
 if(!exactArches&&node.getName()==='Body'&&mat==='Trim'&&Math.abs(center[2])>.7&&center[1]>.16&&(center[0]<sillX0||center[0]>sillX1||center[1]>.56)){
  const near=archAxles.find(ax=>Math.hypot(center[0]-ax,center[1]-archY)<archR+.18);
  if(near!==undefined){
   const outside=p=>Math.hypot(p[0]-near,p[1]-archY)-archR;
   emit(node,'Paint',clip(poly,outside,true));emit(node,'Trim',clip(poly,outside,false));continue;
  }
 }
 // The rising graphite sill band between the arches. Every triangle touching the band's x range is
 // clipped exactly at both ends and along the rising top line, so no edge is decided per triangle.
 if((mat==='Paint'||mat==='Trim')&&Math.abs(center[2])>.75&&center[1]<.56&&poly.some(v=>v.p[0]>sillX0&&v.p[0]<sillX1)){
  const lower=p=>p[1]-(.215+.17*Math.max(0,Math.min(1,(p[0]-sillX0)/(sillX1-sillX0))));
  const inRange=clip(clip(poly,p=>p[0]-sillX0,true),p=>p[0]-sillX1,false);
  emit(node,mat,clip(poly,p=>p[0]-sillX0,false));
  emit(node,mat,clip(poly,p=>p[0]-sillX1,true));
  emit(node,'Fascia',clip(inRange,lower,false));emit(node,mat,clip(inRange,lower,true));continue;
 }
 emit(node,mat,poly);
}
function primitive(name,vertices,offset=[0,0,0]){
 const positions=[],normals=[],ix=[],map=new Map();
 for(let i=0;i<vertices.length;i+=3){
  const triangle=vertices.slice(i,i+3),[a,b,c]=triangle.map(v=>v.p),u=b.map((v,j)=>v-a[j]),v=c.map((v,j)=>v-a[j]);
  if(Math.hypot(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])<1e-12)continue;
  for(const {p,n} of triangle){const norm=normalize(n),key=[...p,...norm].map(v=>Math.round(v*1e6)).join(',');
   if(!map.has(key)){map.set(key,map.size);positions.push(...p.map((v,j)=>v-offset[j]));normals.push(...norm);}ix.push(map.get(key));
  }
 }
 return doc.createPrimitive().setMaterial(mats.get(name))
  .setAttribute('POSITION',doc.createAccessor().setType('VEC3').setArray(new Float32Array(positions)).setBuffer(buffer))
  .setAttribute('NORMAL',doc.createAccessor().setType('VEC3').setArray(new Float32Array(normals)).setBuffer(buffer))
  .setIndices(doc.createAccessor().setType('SCALAR').setArray(new Uint32Array(ix)).setBuffer(buffer));
}
for(const node of nodes){const mesh=node.getMesh();for(const p of mesh.listPrimitives()){mesh.removePrimitive(p);p.dispose();}
 for(const [mat,vertices] of groups.get(node))if(vertices.length)mesh.addPrimitive(primitive(mat,vertices,node.getTranslation()));
}
const details=new Map();
function tri(mat,a,b,c){if(!details.has(mat))details.set(mat,[]);const n=cross(a,b,c);details.get(mat).push(...[a,b,c].map(p=>({p,n})));}
function quad(mat,a,b,c,d){tri(mat,a,b,c);tri(mat,a,c,d);}
// A new hood leading panel joins the original upper surface at x=-1.70.
// Shared normals keep the wide planes clean while retaining the corner crease.
const patch=[],patchNormals=[],patchIndices=[];
for(let j=0;j<=12;j++)for(let i=0;i<=64;i++){
 const t=j/12,a=fasciaTop[i],b=backLine[i];
 patch.push(a.map((v,k)=>v+(b[k]-v)*t));patchNormals.push([0,0,0]);
}
for(let j=0;j<12;j++)for(let i=0;i<64;i++){
 const a=j*65+i,b=a+65,c=b+1,d=a+1;
 for(const ix of [[a,d,c],[a,c,b]]){
  const n=cross(...ix.map(i=>patch[i]));for(const id of ix)for(let k=0;k<3;k++)patchNormals[id][k]+=n[k];patchIndices.push(...ix);
 }
}
details.set('Paint',patchIndices.map(i=>({p:patch[i],n:normalize(patchNormals[i])})));
// Flat, deliberate bumper facets and a thin splitter follow the old body at
// the top. A separate central recess gives the nose depth without scan noise.
for(let i=0;i<fasciaTop.length-1;i++){
 const a=fasciaTop[i],b=fasciaTop[i+1];
 const archX=y=>archAxles[0]-Math.sqrt(Math.max(0,fasciaArchR**2-(y-archY)**2));
 const mid=p=>[Math.min(p[0]+.012,archX(.30)),.30,p[2]],low=p=>[Math.min(p[0]-.012,archX(.165)),.165,p[2]],lip=p=>[Math.min(p[0]-.042,archX(.145)),.145,p[2]*1.009];
 quad('Fascia',a,mid(a),mid(b),b);
 quad('Trim',mid(a),low(a),low(b),mid(b));
 quad('Carbon',low(a),lip(a),lip(b),low(b));
 const a2=lip(a),b2=lip(b);quad('Carbon',a2,[a2[0]+.04,.127,a2[2]],[b2[0]+.04,.127,b2[2]],b2);
}
// Close the two ends into the existing front wheel-well region.
// With exact arches the old end panel at x=-1.70 would stand inside the wheel opening, so instead a liner
// continues the arch's own cylinder forward of the cut (the body's liner stops at x=-1.70).
if(!exactArches)for(const s of [-1,1]){const a=fasciaTop[s<0?0:fasciaTop.length-1],b=[-1.70,a[1],a[2]],c=[-1.70,.16,a[2]],d=[a[0]-.025,.165,a[2]];
 if(s>0)quad('Fascia',a,b,c,d);else quad('Fascia',a,d,c,b);
}
else{
 const ax=archAxles[0],R=archR,t0=Math.PI-Math.acos(Math.min(1,(ax-backX)/R)),t1=Math.PI+Math.asin((archY-.13)/R);
 for(let i=0;i<24;i++){
  const ta=t0+(t1-t0)*i/24,tb=t0+(t1-t0)*(i+1)/24,pa=[ax+R*Math.cos(ta),archY+R*Math.sin(ta)],pb=[ax+R*Math.cos(tb),archY+R*Math.sin(tb)];
  for(const s of [-1,1]){const P=(p,z)=>[p[0],p[1],s*z];
   if(s>0)quad('Trim',P(pa,.60),P(pb,.60),P(pb,.91),P(pa,.91));else quad('Trim',P(pa,.60),P(pa,.91),P(pb,.91),P(pb,.60));
  }
 }
}
// Recessed lower intake: two planes and fine vertical dividers.
for(const z of [-.40,0,.40]){
 const x=-2.312;
 quad('Fascia',[x,.19,z-.008],[x,.286,z-.008],[x-.008,.286,z+.008],[x-.008,.19,z+.008]);
}
// A continuous rear beam and clean diffuser replace the noisy lower scan.
// For the retopo body the beam's half-width follows the body's own section at x=1.98 at every height, so its
// sides meet the cut body exactly (the fixed .92 left a notch at the top and a flare beyond the body below).
const beamW=exactArches?(()=>{const ys=[],ws=[];for(let y=.15;y<=.8751;y+=.005){const w=sideHit(1.975,y);if(w>.3){ys.push(y);ws.push(w);}}
 return y=>{if(y<=ys[0])return ws[0];for(let i=1;i<ys.length;i++)if(y<=ys[i]){const t=(y-ys[i-1])/(ys[i]-ys[i-1]);return ws[i-1]+(ws[i]-ws[i-1])*t;}return ws.at(-1);};})():()=>.92;
const tailX=z=>2.30-.32*(Math.abs(z)/.92)**4;
const tailPoint=(z,y)=>exactArches?[2.30-.32*Math.abs(z/.92)**4,y,z/.92*beamW(y)]:[tailX(z),y,z];
for(let i=0;i<64;i++){
 const z0=(i/64*2-1)*.92,z1=((i+1)/64*2-1)*.92;
 for(const [mat,top,bottom,ot,ob] of [['Trim',.875,.822,0,0],['Paint',.822,.665,0,0],['Fascia',.665,.49,0,-.095],['Fascia',.49,.30,-.095,.015]]){
  const points=[tailPoint(z0,top),tailPoint(z1,top),tailPoint(z1,bottom),tailPoint(z0,bottom)];
  points.forEach((p,j)=>p[0]+=j<2?ot:ob);
  const slope=(ot-ob)/(top-bottom);
  const ns=points.map(p=>{const W=exactArches?beamW(p[1]):.92;return normalize([1,-slope,1.28*p[2]**3/W**4]);});
  if(!details.has(mat))details.set(mat,[]);
  for(const j of [0,1,2,0,2,3])details.get(mat).push({p:points[j],n:ns[j]});
 }
 const wTop=exactArches?beamW(.875)/.92:1,wLow=exactArches?beamW(.15)/.92:1;
 quad('Paint',[1.98,.875,z0*wTop],tailPoint(z0,.875),tailPoint(z1,.875),[1.98,.875,z1*wTop]);
 quad('Carbon',tailPoint(z0,.30),tailPoint(z1,.30),[2.02,.15,z1*wLow],[2.02,.15,z0*wLow]);
 // Close the body's open section under the beam (the cut at x=1.98 leaves a slot above the floor).
 if(exactArches)quad('Carbon',[1.985,.12,z0*wLow],[1.985,.12,z1*wLow],[2.02,.15,z1*wLow],[2.02,.15,z0*wLow]);
}
// Five physical vanes: their shadows make the diffuser legible from the rear.
for(const z of [-.60,-.30,0,.30,.60]){
 const z0=z-.009,z1=z+.009;
 const a=[2.01,.15,z0],b=[2.34,.16,z0],c=[2.31,.28,z0],d=[2.01,.20,z0];
 quad('Fascia',a,b,c,d);quad('Fascia',a.map((v,i)=>i===2?z1:v),d.map((v,i)=>i===2?z1:v),c.map((v,i)=>i===2?z1:v),b.map((v,i)=>i===2?z1:v));
 quad('Carbon',b,b.map((v,i)=>i===2?z1:v),c.map((v,i)=>i===2?z1:v),c);
}
const mesh=doc.createMesh('ReferenceDetails');for(const [mat,vertices] of details)mesh.addPrimitive(primitive(mat,vertices));
root.listScenes()[0].addChild(doc.createNode('ReferenceDetails').setMesh(mesh));
const anchorNode=root.listNodes().find(n=>n.getName()==='Anchors'),anchors=anchorNode.getExtras();
anchors.frontLightPath=fasciaTop.filter(p=>Math.abs(p[2])<.68).map(p=>[p[0]-.006,p[1]-.009,p[2]]);
anchors.tailLightPath=Array.from({length:65},(_,i)=>{const z=(i/64*2-1)*.85;return [tailX(z)+.006,.846,z];});
anchors.tailX=2.30;anchors.plateX=2.30;
anchors.referenceRefinement={source:'Visual study of Sketchfab model 486e7f9dc0e547188b12c46d8b159c59',meshImported:false};
anchorNode.setExtras(anchors);
await doc.transform(prune({keepLeaves:true}),draco({method:'edgebreaker',quantizePosition:16,quantizeNormal:12}));
await mkdir(out,{recursive:true});const bytes=await io.writeBinary(doc);
await writeFile(path.join(out,'roadster-body.glb'),bytes);
await writeFile(path.join(out,'roadster-body.part0.txt'),Buffer.from(bytes).toString('base64'));
await writeFile(path.join(out,'roadster-body.parts.json'),JSON.stringify({parts:1,bytes:bytes.length,draco:true}));
console.log(JSON.stringify({bytes:bytes.length,frontTrianglesReworked:removed,fasciaExtents:[fasciaTop[0],fasciaTop[32],fasciaTop.at(-1)]}));
