const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const transport=fs.readFileSync(path.join(__dirname,'../static/chat_transport.js'),'utf8');

async function run(mode,storageFailure){
  const nodes=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',value:'',disabled:false,hidden:false,files:[{}],checked:true,
    setAttribute(){},replaceChildren(){},add(){},append(){},focus(){}});return nodes.get(id);};
  const job={id:'job-test',mode,state:'COMPLETED',summary:'요약',transcript:'origin',translation:'번역',history:[]};
  let chatPosts=0,uploads=0,submits=0,requests=0;
  const ctx={document:{getElementById:node,createElement:()=>({})},console,
    crypto:{randomUUID:()=> 'node-storage-request-001'},setInterval:()=>0,
    Option:function(text,value){this.text=text;this.value=value;},
    FormData:class{append(){}},confirm:()=>true,
    fetch:async(url,options={})=>{
      requests++;
      let body;
      if(url==='/api/session')body={mode,translationLabel:'Transition',maxBytes:1000000,maxSeconds:7200};
      else if(url==='/api/jobs'&&options.method==='POST'){uploads++;body={...job,id:'new-upload',state:'CREATED',summary:''};}
      else if(url==='/api/jobs')body=[job];
      else if(url.endsWith('/submit')){submits++;body={...job,id:'new-upload',state:'CREATED',summary:''};}
      else if(url.endsWith('/chat')){chatPosts++;const q=JSON.parse(options.body);body={requestId:q.requestId,question:q.text,answer:'데모 답변',evidence:[]};}
      else body=job;
      return {ok:true,status:200,json:async()=>body};
    }};
  ctx.window=ctx;
  if(storageFailure==='getter')Object.defineProperty(ctx,'sessionStorage',{get(){throw Error('SecurityError');}});
  else ctx.sessionStorage={setItem(){throw Error('storage disabled');},getItem(){return null;},removeItem(){}};
  vm.createContext(ctx);vm.runInContext(transport,ctx);vm.runInContext(app,ctx);
  await new Promise(resolve=>setImmediate(resolve));
  node('jobs').value=job.id;await node('jobs').onchange();
  assert.equal(node('content').textContent,'요약');
  const beforeTabs=requests;
  for(const id of ['origin','translation','summary'])node(id).onclick();
  assert.equal(requests,beforeTabs);assert.equal(node('content').textContent,'요약');
  assert.match(node('storage-notice').textContent,/실제 API 채팅만 비활성화/);
  assert.equal(node('ask').disabled,mode==='live');
  node('question').value='에너지';await node('chat').onsubmit({preventDefault(){}});
  assert.equal(chatPosts,mode==='live'?0:1);
  // Startup and upload listeners must survive disabled storage in BOTH modes.
  await node('upload').onsubmit({preventDefault(){}});
  assert.equal(uploads,1);assert.equal(submits,1);
  assert.equal(node('error').textContent,'');
  node('origin').onclick();assert.equal(node('content').textContent,'origin');
  console.log(`PASS N1: ${storageFailure} failure / ${mode}; results, tabs and upload work; paid chat disabled only`);
}
(async()=>{for(const mode of ['live','demo'])for(const failure of ['getter','write'])await run(mode,failure);})()
  .catch(error=>{console.error(error);process.exitCode=1;});
