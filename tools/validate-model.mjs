import {readFile,writeFile} from 'node:fs/promises';
import {NodeIO} from '@gltf-transform/core';import {ALL_EXTENSIONS} from '@gltf-transform/extensions';import draco3d from 'draco3dgltf';import validator from 'gltf-validator';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const p=path.resolve(process.argv[2] || fileURLToPath(new URL('../',import.meta.url)))+path.sep;
const bytes=await readFile(p+'roadster-body.glb'),manifest=JSON.parse(await readFile(p+'roadster-body.parts.json','utf8'));
if(manifest.bytes!==bytes.length||manifest.parts!==1)throw Error('Manifest mismatch');
if(!Buffer.from(await readFile(p+'roadster-body.part0.txt','utf8'),'base64').equals(bytes))throw Error('Text model differs from GLB');
const io=new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'draco3d.decoder':await draco3d.createDecoderModule()});const doc=await io.readBinary(bytes);
const root=doc.getRoot(),nodes=root.listNodes();let triangles=0,vertices=0;
for(const name of ['Anchors','Body','Door0','Door1','Wheel_Aero','Wheel_Turbine','Caliper','Seat'])if(!nodes.some(n=>n.getName()===name))throw Error('Missing '+name);
const anchor=nodes.find(n=>n.getName()==='Anchors').getExtras();for(const k of ['axleX','deckY','tailX','plateX','wheelR'])if(anchor[k]===undefined)throw Error('Missing '+k);
for(const n of nodes.filter(n=>n.getName().startsWith('Door'))){const e=n.getExtras();if(!Number.isFinite(e.openAngle)||e.hingeAxis.length!==3)throw Error('Door rig lost');}
for(const m of root.listMeshes())for(const p of m.listPrimitives()){
 const pos=p.getAttribute('POSITION');vertices+=pos.getCount();triangles+=p.getIndices().getCount()/3;
 for(const v of pos.getArray())if(!Number.isFinite(v))throw Error('Invalid vertex');
 for(const v of p.getAttribute('NORMAL').getArray())if(!Number.isFinite(v))throw Error('Invalid normal');
 for(const i of p.getIndices().getArray())if(i>=pos.getCount())throw Error('Index out of range');
}
// Validate the decoded asset, because the Khronos validator doesn't decode Draco itself.
root.listExtensionsUsed().find(x=>x.extensionName==='KHR_draco_mesh_compression').dispose();
const report=await validator.validateBytes(await io.writeBinary(doc),{maxIssues:30});
const summary={bytes:bytes.length,triangles,vertices,manifestMatches:true,anchorsPreserved:true,doorsPreserved:true,validator:report.issues};
await writeFile(p+'model-validation.json',JSON.stringify(summary,null,2));console.log(JSON.stringify(summary,null,2));if(report.issues.numErrors)process.exit(1);
