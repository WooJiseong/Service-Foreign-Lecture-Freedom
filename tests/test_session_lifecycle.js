const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const nodes=new Map(), timers=new Map(), events=new Map(), memory=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',value:'',disabled:false,hidden:false,checked:true,
  files:[{size:100,lastModified:1}],setAttribute(){},replaceChildren(){},add(){},append(){}});return nodes.get(id);};
const job={id:'lecture-a',mode:'demo',state:'COMPLETED',summary:'요약',history:[],transcript:'전사'};
let jobs=[job], sequence=0, failUpload=true, uploadIds=[], heartbeats=0, ends=0;
const ctx={console,document:{visibilityState:'visible',getElementById:node,createElement:()=>({}),
  addEventListener:(event,fn)=>events.set(event,fn)},
  sessionStorage:{get length(){return memory.size;},key:i=>[...memory.keys()][i],
    getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},
  crypto:{randomUUID:()=>`upload-intent-${++sequence}`},
  setInterval:(fn,ms)=>{timers.set(ms,fn);},Option:function(){},FormData:class{append(){}},confirm:()=>true,
  fetch:async(url,options={})=>{
    let body;
    if(url==='/api/session')body={mode:'demo',maxBytes:100000,maxSeconds:60,heartbeatSeconds:30};
    else if(url==='/api/jobs'&&options.method==='POST'){
      uploadIds.push(options.headers['X-FLF-Upload-ID']);
      if(failUpload){failUpload=false;throw Error('response lost');}
      body=job;
    }else if(url==='/api/jobs')body=jobs;
    else if(url.endsWith('/heartbeat')){heartbeats++;body={active:true};}
    else if(url.endsWith('/end')){ends++;jobs=[];body={ended:true,cleanupPending:false};}
    else body=jobs[0]||job;
    return {ok:true,status:200,json:async()=>body};
  }};
ctx.window=ctx;
vm.createContext(ctx);
for(const file of ['chat_transport.js','app.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'),ctx);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(heartbeats,1,'refresh/init immediately renews active lease');
  assert(!events.has('unload')&&!events.has('pagehide'),'refresh is not destructive');
  ctx.document.visibilityState='hidden';await timers.get(30000)();assert.equal(heartbeats,1);
  ctx.document.visibilityState='visible';events.get('visibilitychange')();
  await new Promise(resolve=>setImmediate(resolve));assert.equal(heartbeats,2);
  await node('upload').onsubmit({preventDefault(){}});
  await node('upload').onsubmit({preventDefault(){}});
  assert.equal(uploadIds[0],uploadIds[1],'lost upload response retries same request/session');
  await node('upload').onsubmit({preventDefault(){}});
  assert.notEqual(uploadIds[1],uploadIds[2],'new upload independent even same file');
  memory.set('flf-pending-chat:lecture-a',JSON.stringify({text:'question',requestId:'q'}));
  await node('delete').onclick();
  assert.equal(ends,1);assert(!memory.has('flf-pending-chat:lecture-a'));
  assert.equal(node('history').textContent,'');
  memory.set('flf-pending-chat:ended-other-tab','private pending question');
  await timers.get(30000)();assert(!memory.has('flf-pending-chat:ended-other-tab'));
  jobs=[{...job,quarantined:true}];const beforeQuarantine=heartbeats;
  await timers.get(30000)();assert.equal(heartbeats,beforeQuarantine,'legacy quarantine cannot be auto-adopted by heartbeat');
  jobs=[{...job,state:'FAILED',legacyReadOnly:true}];node('jobs').value=job.id;
  await node('jobs').onchange();assert.equal(node('ask').disabled,true);assert.equal(node('retry').hidden,true);
  assert.match(node('status').textContent,/구 강의 조회\/종료 전용/);
  console.log('PASS: lease init/visibility/multi-tab cache cleanup, no unload deletion, upload retry identity, independent new upload, explicit end');
})().catch(error=>{console.error(error);process.exitCode=1;});
