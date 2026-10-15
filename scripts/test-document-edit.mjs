import { spawn } from 'node:child_process';
import net from 'node:net';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const directory = await mkdtemp(path.join(tmpdir(), 'reidom-document-test-'));
const port = 47129;
const engine = spawn(path.join(root, 'build/engine-ninja/reidom-engine_artefacts/Release/reidom-engine.exe'), ['--port',String(port)], {
  env: {...process.env, REIDOM_DOCUMENT_DIR: directory}, windowsHide: true,
});
const call = (request) => new Promise((resolve,reject) => {
  const socket = net.createConnection({host:'127.0.0.1',port}, () => socket.end(JSON.stringify(request)+'\n'));
  let text=''; socket.setTimeout(10000,()=>socket.destroy(new Error('timeout')));
  socket.on('data',chunk=>text+=chunk); socket.on('error',reject);
  socket.on('end',()=>{try {resolve(JSON.parse(text));} catch(error) {reject(error);}});
});
const doc = async()=> (await call({method:'document.get'})).result;
const edit = async (d, changes) => call({method:'document.edit',project_id:d.project_id,expected_revision:d.revision,
  edit_epoch:d.edit_epoch,request_id:randomUUID(),reason:'Integration verification',changes});
const user = async(type,payload) => {const d=await doc(); return call({method:'command.apply',command:{schema:'reidom-command/v2',project_id:d.project_id,
  base_revision:d.revision,command_id:randomUUID(),idempotency_key:randomUUID(),source:'user',type,payload}});};
try {
  await new Promise((resolve,reject)=>{engine.stdout.on('data',chunk=>{if(String(chunk).includes('ready'))resolve();}); engine.once('exit',code=>reject(new Error('engine exited '+code)));});
  const initial=await doc(); assert.equal(initial.mode,'ai');
  const snapshot = (await call({method:'snapshot.get'})).result;
  assert.equal(Object.hasOwn(snapshot, 'ai_snapshot'), false);
  assert.ok(Object.hasOwn(snapshot, 'ui_snapshot'));
  assert.deepEqual(initial.selection.note_ids, []);
  assert.equal((await user('tracks.add',{name:'blocked'})).ok,false);
  const added=await edit(initial,[
    {op:'upsert',target:'tracks',items:[{id:'guitar',name:'Interlude',instrument:'guitar'}]},
    {op:'upsert',target:'clips',items:[{id:'phrase',track_id:'guitar',name:'Phrase',start_beats:16,duration_beats:8,
      notes:[{id:'note',pitch:64,start_beats:16,duration_beats:1,velocity:90}]}]},
  ]);
  assert.equal(added.ok,true,JSON.stringify(added));
  let d=await doc(); assert.equal(d.song.tracks.length,1); assert.equal(d.song.clips[0].notes.length,1);
  const selected = await user('selection.set',{clip_ids:['phrase'],note_ids:['note']});
  assert.equal(selected.ok,true);
  d=await doc();
  assert.deepEqual(d.selection.clip_ids,['phrase']);
  assert.deepEqual(d.selection.note_ids,['note']);
  const invalid=await edit(d,[{op:'merge',target:'song',fields:{name:'must rollback'}},{op:'upsert',target:'notes',clip_id:'phrase',items:[{id:'note',pitch:128}]}]);
  assert.equal(invalid.ok,false); assert.deepEqual(await doc(),d);
  const changed=await edit(d,[{op:'upsert',target:'notes',clip_id:'phrase',items:[{id:'note',pitch:67}]}]);
  assert.equal(changed.ok,true); d=await doc(); assert.equal(d.song.clips[0].notes[0].pitch,67);
  const originalNotes=structuredClone(d.song.clips[0].notes);
  assert.equal((await edit(d,[{op:'upsert',target:'clips',items:[{id:'phrase',duration_beats:16}]}])).ok,true);
  d=await doc(); assert.equal(d.song.clips[0].duration_beats,16);
  assert.deepEqual(d.song.clips[0].notes,originalNotes);
  assert.equal((await edit(d,[{op:'upsert',target:'notes',clip_id:'phrase',items:[
    {id:'continuation',pitch:69,start_beats:24,duration_beats:0.5,velocity:86},
  ]}])).ok,true);
  d=await doc(); assert.equal(d.song.clips[0].notes.length,2);
  assert.deepEqual(d.song.clips[0].notes.find(note=>note.id==='note'),originalNotes[0]);
  assert.equal((await call({method:'edit.mode',source:'user',mode:'manual'})).ok,true);
  assert.equal((await edit(await doc(),[{op:'merge',target:'song',fields:{name:'blocked'}}])).ok,false);
  const beforeResize=await doc();
  assert.equal((await user('clips.resize',{clip_ids:['phrase'],delta_beats:4})).ok,true);
  d=await doc(); assert.equal(d.song.clips[0].duration_beats,20);
  assert.deepEqual(d.song.clips[0].notes,beforeResize.song.clips[0].notes);
  assert.equal((await user('tracks.rename',{track_id:'guitar',name:'Manual name'})).ok,true);
  const stale=await doc();
  await call({method:'edit.mode',source:'user',mode:'ai'});
  assert.equal((await edit(stale,[{op:'merge',target:'song',fields:{name:'stale'}}])).ok,false);
  assert.equal((await user('transport.set_state',{playing:true})).ok,true);
  assert.equal((await user('transport.set_state',{playing:false})).ok,true);
  await call({method:'edit.mode',source:'user',mode:'manual'});
  const beforeUndo=await doc();
  assert.equal((await call({method:'history.undo'})).ok,true);
  const afterUndo=await doc(); assert.ok(afterUndo.revision>beforeUndo.revision);
  assert.equal(afterUndo.song.tracks[0].name,'Interlude');
  assert.equal((await call({method:'history.redo'})).ok,true);
  assert.equal((await doc()).song.tracks[0].name,'Manual name');
  const published=JSON.parse(await readFile(path.join(directory,'current.json'),'utf8'));
  assert.deepEqual(published,await doc());
  console.log('PASS: atomic JSON creation/update/rollback; extension/continuation/manual resize preserve original notes; manual/AI exclusion; stale epoch rejection; read-only playback; undo/redo; published document');
} finally { await call({method:'engine.shutdown'}).catch(()=>{}); engine.kill(); }
