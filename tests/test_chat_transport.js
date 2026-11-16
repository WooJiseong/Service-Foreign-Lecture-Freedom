const assert=require('node:assert/strict');
const ChatTransport=require('../static/chat_transport.js');
const storage=()=>{const m=new Map();return {getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};};
const absent=()=>Object.assign(Error('not found'),{status:404});

async function main(){
  // Simulate a paid provider reply committed on server, lost before browser receipt.
  const s=storage(),records=new Map();let post=0,paid=0,history=[],lost=true,ids=0;
  const api=async(path,options)=>{
    if(!options){const id=path.split('/').at(-1);if(!records.has(id))throw absent();return records.get(id);}
    post++;const q=JSON.parse(options.body);
    if(!records.has(q.requestId)){
      paid++;const turn={requestId:q.requestId,question:q.text,answer:'근거 답변',evidence:[]};
      history.push(turn);records.set(q.requestId,{question:q.text,state:'done',turn});
    }
    if(lost){lost=false;throw TypeError('response lost after commit');}
    return records.get(q.requestId).turn;
  };
  let t=new ChatTransport(api,s,()=>`stable-request-${++ids}`);
  await assert.rejects(t.send('job-a','에너지'),/response lost/);
  assert.equal(t.pending('job-a').text,'에너지');
  await assert.rejects(t.send('job-a','다른 질문'),/이전 질문/);
  // Reload of the transport retains the intent, reconciles GET, no second POST.
  t=new ChatTransport(api,s,()=>`stable-request-${++ids}`);
  const replay=await t.send('job-a','에너지');
  assert.equal(replay.requestId,'stable-request-1');
  assert.equal(post,1);assert.equal(paid,1);assert.equal(history.length,1);assert.equal(ids,1);
  assert.equal(t.pending('job-a'),null);assert.equal(t.pending('job-b'),null);
  console.log('PASS F6: response lost after completion; reload/reconcile; one POST, one paid call, one history turn');

  // Loss before server receipt: GET 404 permits replay with the original id/text.
  const s2=storage();let first=true,seen=[];
  const api2=async(path,options)=>{if(!options)throw absent();const q=JSON.parse(options.body);seen.push(q);
    if(first){first=false;throw TypeError('request lost');}return {requestId:q.requestId,question:q.text};};
  const t2=new ChatTransport(api2,s2,()=>`second-stable-${++ids}`);
  await assert.rejects(t2.send('job-c','질문'));
  await t2.send('job-c','질문');
  assert.deepEqual(seen[0],seen[1]);
  console.log('PASS F6: request lost before receipt; same id/question replay');

  s2.setItem(t2.key('job-c'),JSON.stringify({text:'질문',requestId:'uncertain-request'}));
  t2.api=async()=>({state:'uncertain',question:'질문'});
  await assert.rejects(t2.send('job-c','질문'),/관리자/);
  assert.equal(t2.pending('job-c').requestId,'uncertain-request');
  console.log('PASS F6: uncertain request remains blocked and retained');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
