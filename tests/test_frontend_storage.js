const assert=require('node:assert/strict');
const {harness,lecture,event}=require('./frontend_harness');
async function run(mode,storageFailure){
  const job=lecture('job-test',{mode});let chatPosts=0,uploads=0,submits=0;
  const h=await harness({mode,storageFailure,jobs:[job],handler:(url,options)=>{
    if(url==='/api/jobs'&&options.method==='POST'){uploads++;return lecture('new-upload',{mode,state:'CREATED',summary:''});}
    if(url.endsWith('/submit')){submits++;return lecture('new-upload',{mode,state:'STT_PENDING',summary:''});}
    if(url.endsWith('/chat')){chatPosts++;const q=JSON.parse(options.body);return {requestId:q.requestId,question:q.text,answer:'데모 답변',evidence:[]};}
  }});
  const {node}=h;assert.equal(node('content').textContent,'요약');
  const before=h.calls.length;
  for(let i=0;i<3;i++)node('cycle').onclick();
  assert.equal(h.calls.length,before);assert.equal(node('content').textContent,'요약');
  assert.match(node('storage-notice').textContent,/실제 API 채팅만 비활성화/);
  assert.equal(node('question').disabled,mode==='live');
  node('question').value='에너지';node('question').oninput();assert.equal(node('ask').disabled,mode==='live');
  await node('chat').onsubmit(event());assert.equal(chatPosts,mode==='live'?0:1);
  // Explicit end before a separate upload: storage failure cannot break either operation.
  await node('delete').onclick();h.choose();node('consent').checked=true;node('consent').onchange();
  await node('upload').onsubmit(event());assert.equal(uploads,1);assert.equal(submits,1);assert.equal(node('error').textContent,'');
  console.log(`PASS: ${storageFailure} failure / ${mode}; result cycle, session end and upload work; paid chat disabled only`);
}
(async()=>{for(const mode of ['live','demo'])for(const failure of ['getter','write'])await run(mode,failure);
  const h=await harness({mode:'live',jobs:[lecture('runtime',{mode:'live'})]});
  h.ctx.sessionStorage.setItem=()=>{throw Error('quota exceeded');};
  h.node('question').value='runtime blocked';await h.node('chat').onsubmit(event());
  assert.equal(h.calls.filter(c=>c.url.endsWith('/chat')).length,0);assert.equal(h.node('question').disabled,true);
  console.log('PASS: runtime storage failure blocks live chat before POST');
})().catch(error=>{console.error(error);process.exitCode=1;});
