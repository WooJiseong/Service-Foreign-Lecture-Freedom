const assert=require('node:assert/strict');
const {harness,lecture,event}=require('./frontend_harness');
(async()=>{
  const job=lecture(),jobs=[job];let failUpload=true,uploadIds=[],ends=0;
  const h=await harness({jobs,handler:(url,options)=>{
    if(url==='/api/jobs'&&options.method==='POST'){uploadIds.push(options.headers['X-FLF-Upload-ID']);if(failUpload){failUpload=false;return Error('response lost');}jobs.push(lecture('lecture-b',{state:'CREATED',summary:''}));return jobs.at(-1);}
    if(url.endsWith('/end'))ends++;
  }});
  const {node,ctx,timers,events,storage}=h;
  const heartbeatCount=()=>h.calls.filter(c=>c.url.endsWith('/heartbeat')).length;
  assert.equal(heartbeatCount(),1,'refresh/init immediately renews selected owned lease');
  assert(!events.has('unload')&&!events.has('pagehide'),'refresh is not destructive');
  assert.equal(node('result-view').hidden,false,'refresh recovers active owned job');
  ctx.document.visibilityState='hidden';await timers.get(30000)();assert.equal(heartbeatCount(),1);
  ctx.document.visibilityState='visible';events.get('visibilitychange')();await h.flush();assert.equal(heartbeatCount(),2);
  storage.set('flf-pending-chat:lecture-a',JSON.stringify({text:'question',requestId:'q'}));
  ctx.confirm=()=>false;await node('delete').onclick();assert.equal(ends,0,'cancel preserves session');
  ctx.confirm=()=>true;await node('delete').onclick();assert.equal(ends,1);assert(!storage.has('flf-pending-chat:lecture-a'));assert.equal(node('history').children.length,0);assert.equal(node('error').textContent,'');assert.match(node('session-status').textContent,/세션 종료됨/);
  const afterEnd=heartbeatCount();await timers.get(30000)();assert.equal(heartbeatCount(),afterEnd,'ended job is no longer kept alive');
  h.choose();node('consent').checked=true;
  await node('upload').onsubmit(event());await node('upload').onsubmit(event());
  assert.equal(uploadIds[0],uploadIds[1],'lost upload response retries same request/session');
  await node('upload').onsubmit(event());assert.equal(uploadIds.length,2,'active session blocks hidden upload handler');
  await node('back').onclick();h.choose();node('consent').checked=true;await node('upload').onsubmit(event());
  assert.notEqual(uploadIds[1],uploadIds[2],'new lecture independent even same file');
  storage.set('flf-pending-chat:ended-other-tab','private pending question');await timers.get(30000)();assert(!storage.has('flf-pending-chat:ended-other-tab'));
  jobs.splice(0,jobs.length,lecture('legacy',{quarantined:true}));const before=heartbeatCount();await timers.get(30000)();assert.equal(heartbeatCount(),before,'legacy quarantine cannot be auto-adopted');
  h.run("setJob({id:'legacy',mode:'demo',state:'FAILED',summary:'요약',history:[],legacyReadOnly:true})");
  assert.equal(node('ask').disabled,true);assert.equal(node('retry').hidden,true);assert.match(node('status').textContent,/구 강의 조회\/종료 전용/);
  h.run("setJob({id:'quarantined',mode:'demo',state:'STT_RUNNING',summary:'',history:[],quarantined:true})");
  const quarantinedCalls=h.calls.length;assert.equal(node('retry').hidden,true);assert.match(node('status').textContent,/보관 작업/);await timers.get(1500)();assert.equal(h.calls.length,quarantinedCalls,'quarantined jobs are not polled or revived');
  h.run("setJob({id:'legacy-done',mode:'demo',state:'COMPLETED',summary:'요약',history:[],legacyReadOnly:true})");assert.equal(node('result-view').hidden,false);assert.equal(node('result-legacy').hidden,false);
  const restored=await harness({jobs:[lecture('chosen'),lecture('other')],storage:new Map([['flf-active-job','chosen']])});
  assert.equal(restored.calls.filter(c=>c.url.endsWith('/heartbeat')).length,1);assert(restored.calls.some(c=>c.url==='/api/jobs/chosen/heartbeat'));
  const expired=await harness({jobs:[lecture('unrelated')],storage:new Map([['flf-active-job','expired']])});assert.equal(expired.node('upload-view').hidden,false,'expired explicit selection cannot silently switch context');
  const stale=await harness({jobs:[lecture('gone')],storage:new Map([['flf-active-job','gone'],['flf-upload-attempt','{"id":"expired-intent"}']])});
  stale.jobs.splice(0);await stale.timers.get(30000)();assert.equal(stale.node('upload-view').hidden,false);assert(!stale.storage.has('flf-active-job'));assert(!stale.storage.has('flf-upload-attempt'),'expired job cannot leave a stale upload ID that blocks the same file');
  console.log('PASS: refresh recovery, visible-only selected lease, cancel/end, cache cleanup, upload retry identity, independent new lecture, legacy fences, expiry clears stale upload intent');
})().catch(error=>{console.error(error);process.exitCode=1;});
