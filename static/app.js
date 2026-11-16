const $=id=>document.getElementById(id);
let job=null, tab='origin', uploading=false, chatBusy=false;
const fields={origin:'transcript',translation:'translation',summary:'summary'};
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{'X-FLF-Request':'1',...options.headers}});
  const body=await response.json();
  if(!response.ok) { const error=Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));error.status=response.status;throw error; }
  return body;
}
let chatStorage, chatStorageAvailable=true;
try {
  chatStorage=window.sessionStorage;
  const probe='flf-storage-probe';
  chatStorage.setItem(probe,'1');
  if(chatStorage.getItem(probe)!=='1')throw Error('storage unavailable');
  chatStorage.removeItem(probe);
} catch(error) {
  chatStorageAvailable=false;
  // Demo remains useful; never use this volatile fallback for paid chat.
  const memory=new Map();
  chatStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
}
const chatTransport=new FLFChatTransport(api,chatStorage,()=>crypto.randomUUID());
function pendingChat(id){try{return chatTransport.pending(id);}catch(error){chatStorageAvailable=false;return null;}}
function forgetChat(id){try{chatStorage.removeItem(chatTransport.key(id));}catch(error){chatStorageAvailable=false;}}
function report(e){$('error').textContent=e.message;}
function selectTab(id){tab=id;for(const key of Object.keys(fields))$(key).setAttribute('aria-selected',String(key===tab));render();}
for(const id of Object.keys(fields)){
  $(id).onclick=()=>selectTab(id);
  $(id).onkeydown=e=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){
    e.preventDefault();const ids=Object.keys(fields), i=ids.indexOf(id);
    const next=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3;
    selectTab(ids[next]);$(ids[next]).focus();
  }};
}
function render(){
  $('content').textContent=job?.[fields[tab]]||'아직 결과가 없습니다.';
  $('status').textContent=job?`${job.mode==='demo'?'[고정 예시 데모] ':''}${job.state}${job.failedStep?' · 실패 단계: '+job.failedStep:''}${job.error?' · '+job.error:''}`:'작업을 선택하세요.';
  $('retry').hidden=job?.state!=='FAILED';$('delete').hidden=!job;
  $('question').disabled=$('ask').disabled=!job?.summary||chatBusy||(!chatStorageAvailable&&job.mode==='live');
  $('storage-notice').textContent=chatStorageAvailable?'':'브라우저 세션 저장소를 사용할 수 없어 실제 API 채팅만 비활성화했습니다. 업로드·결과 조회는 계속 사용할 수 있으며, 데모 채팅은 이 페이지의 임시 메모리만 사용합니다.';
  $('history').replaceChildren();
  for(const turn of job?.history||[]){const p=document.createElement('p');p.textContent=`질문: ${turn.question}\n답변: ${turn.answer}\n근거: ${turn.evidence.map(r=>'['+r.source+'] '+r.text).join('\n')}`;$('history').append(p);}
}
async function list(){const jobs=await api('/api/jobs');$('jobs').replaceChildren(new Option('작업 선택',''));for(const j of jobs)$('jobs').add(new Option(j.id.slice(0,8)+' · '+j.state,j.id));if(job)$('jobs').value=job.id;}
$('jobs').onchange=async()=>{try{job=$('jobs').value?await api('/api/jobs/'+$('jobs').value):null;$('question').value=job?(pendingChat(job.id)?.text||''):'';selectTab(job?.summary?'summary':'origin');}catch(e){report(e);}};
$('refresh').onclick=()=>list().catch(report);
$('upload').onsubmit=async e=>{e.preventDefault();if(uploading)return;uploading=true;$('submit').disabled=true;$('error').textContent='';
  try{const form=new FormData();form.append('audio',$('audio').files[0]);form.append('consent',$('consent').checked);
    job=await api('/api/jobs',{method:'POST',body:form});job=await api(`/api/jobs/${job.id}/submit`,{method:'POST'});selectTab('origin');await list();
  }catch(e){report(e);}finally{uploading=false;$('submit').disabled=false;}};
$('retry').onclick=async()=>{try{job=await api(`/api/jobs/${job.id}/retry`,{method:'POST'});render();}catch(e){report(e);}};
$('delete').onclick=async()=>{if(!confirm('이 작업의 로컬 음성/결과/대화를 삭제할까요?'))return;try{const id=job.id;await api('/api/jobs/'+id,{method:'DELETE'});forgetChat(id);job=null;render();await list();}catch(e){report(e);}};
$('chat').onsubmit=async e=>{e.preventDefault();if(!job?.summary||chatBusy||(!chatStorageAvailable&&job.mode==='live'))return;chatBusy=true;$('ask').disabled=true;const id=job.id;
  try{const turn=await chatTransport.send(id,$('question').value);if(job?.id===id){if(!job.history.some(t=>t.requestId===turn.requestId))job.history.push(turn);$('question').value='';$('error').textContent='';render();}}catch(e){report(e);const pending=pendingChat(id);if(pending&&job?.id===id)$('question').value=pending.text;}finally{chatBusy=false;render();}};
$('demo').onclick=()=>{const n=16000,b=new ArrayBuffer(44+n*2),v=new DataView(b);const s=(o,t)=>[...t].forEach((c,i)=>v.setUint8(o+i,c.charCodeAt()));s(0,'RIFF');v.setUint32(4,36+n*2,true);s(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);s(36,'data');v.setUint32(40,n*2,true);for(let i=0;i<n;i++)v.setInt16(44+i*2,Math.sin(i*2*Math.PI*440/16000)*2000,true);const dt=new DataTransfer();dt.items.add(new File([b],'demo-tone.wav',{type:'audio/wav'}));$('audio').files=dt.files;};
async function init(){const config=await api('/api/session');$('mode').textContent=config.mode==='demo'?'DEMO · 실제 음성 인식/번역 아님 · API 호출 없음':'LIVE · 유료 NAVER Cloud API';$('translation').textContent=config.translationLabel;$('limits').textContent=`최대 ${Math.floor(config.maxBytes/1024/1024)} MiB, ${config.maxSeconds/60}분`;if(config.mode!=='demo')$('demo').hidden=true;await list();render();}
init().catch(report);
setInterval(async()=>{if(!job)return;try{const id=job.id,previous=job.state,next=await api('/api/jobs/'+id);if(job?.id!==id)return;job=next;if(next.state==='COMPLETED'&&previous!=='COMPLETED')selectTab('summary');else render();}catch(e){report(e);}},1500);
