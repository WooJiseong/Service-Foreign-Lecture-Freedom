if (!crypto.randomUUID) {
  crypto.randomUUID = () => {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  };
}
const $=id=>document.getElementById(id);
let job=null, tab='summary', uploading=false, chatBusy=false, activeJobs=[], heartbeatJobs=[];
let uploadAttempt=null, config=null, selectedFile=null, view='upload', composing=false;
let pollFailures=0, polling=false, retrying=false, ending=false, chatDraft=null;
const fields={summary:'summary',origin:'transcript',translation:'translation'};
const labels={summary:'Summary',origin:'Origin',translation:'Translate'};
const stageNames=['음성 인식','한국어 번역','강의 요약'];
function errorCause(code){
  if(!code)return '';
  if(/AMBIGUOUS|UNCERTAIN|RECONCILE|CONFLICT/.test(code))return '응답/과금 여부가 불명확하여 관리자 대조가 필요합니다.';
  if(/PROVIDER_HTTP_429|CHAT_REQUEST_CAP|JOB_CALL_CAP/.test(code))return 'AI 서비스 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.';
  if(/PROVIDER_HTTP_(400|401|403|404|422)|STUDIO_REJECTED|INVALID_PROVIDER_JSON|RESPONSE_ENCODING_REJECTED/.test(code))return 'AI 서비스 인증 또는 요청 설정을 확인해야 합니다.';
  if(/PROVIDER_HTTP_5|SPEECH_CALLBACK_TIMEOUT|SPEECH_POLL_FAILED|POLL_TRANSPORT|AMBIGUOUS_TRANSPORT/.test(code))return 'AI 서비스 응답이 지연되거나 일시적으로 실패했습니다.';
  if(/EMPTY_TRANSCRIPT|EMPTY_PROVIDER_OUTPUT/.test(code))return '인식된 음성이 없습니다. 음성이 포함된 파일인지 확인하세요.';
  if(/TRANSCRIPT_CAP|RESPONSE_TOO_LARGE/.test(code))return '음성 인식 또는 응답 결과가 너무 큽니다. 더 짧은 강의로 나누세요.';
  if(/SUMMARY_|STUDIO_TRUNCATED/.test(code))return '요약 결과 검증에 실패했습니다.';
  if(/TRANSLATION_SOURCE_CHANGED/.test(code))return '번역 입력이 변경되어 다시 확인해야 합니다.';
  if(/CALLBACK_/.test(code))return '음성 인식 결과 수신에 문제가 있습니다. 관리자 확인이 필요할 수 있습니다.';
  return '처리 중 오류가 발생했습니다.';
}
function retryAppropriate(){
  if(!job||job.state!=='FAILED')return true;
  const code=job.error||'';
  if(/PROVIDER_HTTP_(400|401|403|404|422)|EMPTY_TRANSCRIPT|TRANSCRIPT_CAP/.test(code))return false;
  return job.retryAllowed===true;
}
async function api(path, options={}) {
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),25000);
  try {
    const response=await fetch(path,{...options,signal:controller.signal,headers:{'X-FLF-Request':'1',...options.headers}});
    const body=await response.json();
    if(!response.ok){const error=Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));error.status=response.status;throw error;}
    return body;
  } catch(error){if(error.name==='AbortError')throw Error('응답 확인 시간이 초과되었습니다. 같은 요청으로 재확인하세요.');throw error;}
  finally{clearTimeout(timer);}
}
let chatStorage, chatStorageAvailable=true;
const memory=new Map();
try {
  chatStorage=window.sessionStorage;
  chatStorage.setItem('flf-storage-probe','1');
  if(chatStorage.getItem('flf-storage-probe')!=='1')throw Error('storage unavailable');
  chatStorage.removeItem('flf-storage-probe');
} catch(error) {
  chatStorageAvailable=false;
  chatStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
}
// Non-chat metadata may degrade to memory. Paid chat must remain fail-closed.
function saved(key,value){try{if(value===undefined)return chatStorage.getItem(key)||memory.get(key)||null;if(value===null){chatStorage.removeItem(key);memory.delete(key);}else{memory.set(key,value);chatStorage.setItem(key,value);}}catch(error){chatStorageAvailable=false;if(value===undefined)return memory.get(key)||null;if(value===null)memory.delete(key);else memory.set(key,value);}return null;}
const chatTransport=new FLFChatTransport(api,chatStorage,()=>crypto.randomUUID());
function pendingChat(id){try{return chatTransport.pending(id);}catch(error){chatStorageAvailable=false;return null;}}
function forgetChat(id){saved(chatTransport.key(id),null);}
function report(error){$('error').textContent=error.message;}
function showView(next){const changed=view!==next;view=next;for(const name of ['upload','processing','result']){$(name+'-view').hidden=name!==next;$('nav-'+name).setAttribute('aria-current',name===next?'step':'false');}if(changed)$(next+'-heading').focus();}
function selectTab(id){tab=id;render();}
$('cycle').onclick=()=>{const ids=Object.keys(fields);selectTab(ids[(ids.indexOf(tab)+1)%ids.length]);};
function validate(){
  let reason='';
  if(!config)reason='서버 한도를 확인할 수 없습니다. 새로고침 후 다시 시도하세요.';
  else if(!selectedFile)reason='오디오 파일 1개를 선택하세요.';
  else if(!/\.(mp3|aac|ac3|ogg|flac|wav|m4a)$/i.test(selectedFile.name))reason='지원하지 않는 형식입니다. MP3, AAC, AC3, OGG, FLAC, WAV, M4A를 선택하세요.';
  else if(!selectedFile.size)reason='빈 파일은 제출할 수 없습니다.';
  else if(selectedFile.size>config.maxBytes)reason='서버의 최대 파일 크기를 초과했습니다.';
  $('validation').textContent=reason;
  $('submit').disabled=!!reason||!$('consent').checked||uploading||!!job;
  return !reason;
}
function choose(files){if(uploading||job)return;if(!files.length){selectedFile=null;$('audio').value='';$('file-info').textContent='선택한 파일 없음';validate();return;}
  if(files.length!==1){selectedFile=null;$('audio').value='';$('file-info').textContent='선택한 파일 없음';validate();$('validation').textContent='파일은 한 번에 1개만 선택하세요.';return;}
  selectedFile=files[0];$('file-info').textContent=`${selectedFile.name} · ${selectedFile.size.toLocaleString()} bytes`;validate();}
$('audio').onchange=()=>choose($('audio').files);
$('consent').onchange=validate;
for(const type of ['dragenter','dragover'])$('dropzone')['on'+type]=event=>{event.preventDefault();$('dropzone').classList.add('dragging');};
$('dropzone').ondragleave=()=>$('dropzone').classList.remove('dragging');
$('dropzone').ondrop=event=>{event.preventDefault();$('dropzone').classList.remove('dragging');choose(event.dataTransfer.files);};
function stageIndex(state){return state==='TRANSLATING'?1:state==='SUMMARIZING'?2:0;}
function renderHistory(){
  const history=$('history'), previousScroll=history.scrollTop;
  const nearBottom=history.dataset.job!==(job?.id||'')||history.scrollHeight-history.scrollTop-history.clientHeight<80;
  const signature=JSON.stringify([job?.id,job?.history,chatDraft]);
  if(history.dataset.signature===signature)return;
  history.dataset.signature=signature;history.dataset.job=job?.id||'';history.replaceChildren();
  function bubble(role,text,extra=''){const node=document.createElement('div');node.className='bubble '+role+' '+extra;const name=document.createElement('strong');name.textContent=role==='user'?'나':(job?.mode==='demo'?'FLF AI · DEMO 예시':'FLF AI');const body=document.createElement('div');body.textContent=text;node.append(name,body);history.append(node);return node;}
  for(const turn of job?.history||[]){bubble('user',turn.question);const answer=bubble('ai',turn.answer);if(turn.evidence?.length){const evidence=document.createElement('p');evidence.className='evidence';evidence.textContent='근거: '+turn.evidence.map(r=>'['+r.source+'] '+r.text).join('\n');answer.append(evidence);}}
  if(chatDraft&&chatDraft.id===job?.id){bubble('user',chatDraft.text);bubble('ai',chatDraft.error||'답변 확인 중…',chatDraft.error?'error':'pending');}
  history.scrollTop=nearBottom?history.scrollHeight:previousScroll;
}
function render(){
  showView(job?(job.state==='COMPLETED'?'result':'processing'):'upload');
  $('content').textContent=job?.[fields[tab]]||'저장된 결과가 없습니다.';$('result-demo').hidden=!(job&&job.mode==='demo'&&view==='result');if(!$('result-demo').hidden)$('result-demo').textContent='DEMO 고정 예시입니다. 실제 음성 인식·번역·요약 결과가 아닙니다.';const readOnly=job&&(job.legacyReadOnly||job.quarantined)&&view==='result';$('result-legacy').hidden=!readOnly;if(readOnly)$('result-legacy').textContent=job.legacyReadOnly?'구 강의 조회/종료 전용입니다. 저장된 결과만 표시하며 처리 재개·새 질문은 지원하지 않습니다.':'처리 재개가 종료된 보관 결과입니다. 저장된 결과 조회와 종료만 지원합니다.';
  $('cycle').textContent=labels[tab];$('result-label').textContent=labels[tab]+' · '+({summary:'핵심 요약',origin:'영문 원문',translation:'한국어 번역'}[tab]);$('result-label').dataset.type=tab;
  $('attribution').hidden=tab!=='translation';
  const stage=stageIndex(job?.failedStep||job?.state);
  const done=job?.state==='COMPLETED';
  const active=job&&!job.quarantined&&!job.legacyReadOnly&&['STT_PENDING','STT_RUNNING','TRANSLATING','SUMMARIZING'].includes(job.state)?stage:-1;
  const failed=job?.state==='FAILED'?stage:-1;
  for(const [i,id] of ['speech','translation','summary'].entries()){
    const node=$('stage-'+id);
    let stateText='대기';
    if(done||i<stage)stateText='완료';
    else if(failed===i)stateText='실패';
    else if(active===i)stateText=job.state==='STT_PENDING'?'대기':'진행 중';
    node.textContent=stageNames[i]+' · '+stateText;
    node.setAttribute('aria-current',job&&!job.quarantined&&!job.legacyReadOnly&&!done&&i===stage?'step':'false');
  }
  const ambiguous=/AMBIGUOUS|UNCERTAIN|RECONCILE|CONFLICT/.test(job?.error||'');
  let statusText='';
  if(job){
    if(job.legacyReadOnly)statusText='구 강의 조회/종료 전용 · 보존된 상태이며 처리 재개/새 질문은 지원하지 않습니다.';
    else if(job.quarantined)statusText=job.state==='COMPLETED'?'보관된 완료 결과 · 새 질문과 처리 재개는 지원하지 않습니다.':'처리 재개가 종료된 보관 작업입니다. 결과 조회와 종료만 지원합니다.';
    else if(job.state==='FAILED')statusText=stageNames[stage]+' 실패';
    else if(job.state==='CREATED')statusText='업로드 완료 · 처리 제출 대기';
    else if(job.state==='COMPLETED')statusText='모든 단계 완료';
    else if(job.state==='STT_PENDING')statusText='음성 인식 대기 중';
    else statusText=stageNames[stage]+' 진행 중';
    if(job.error&&!ambiguous)statusText+=' · 원인: '+errorCause(job.error)+' (코드: '+job.error+')';
    else if(job.state==='FAILED'&&!job.error)statusText+=' · 원인 정보가 없습니다. 다시 시도하거나 새 강의로 시작하세요.';
    if(ambiguous)statusText+=' · 응답/과금 여부가 불명확하여 재시도를 차단했습니다. 관리자 대조가 필요합니다.';
  }
  $('status').textContent=(job&&job.mode==='demo'?'[고정 예시 데모] ':'')+statusText;
  $('retry').hidden=!job||!['FAILED','CREATED'].includes(job.state)||job.legacyReadOnly||job.quarantined||ambiguous||(job.state==='FAILED'&&!retryAppropriate());
  $('retry').textContent=job?.state==='CREATED'?'처리 제출 재확인':stageNames[stage]+' 단계 재시도';$('retry').disabled=retrying||ending;
  $('check-status').hidden=pollFailures<3;
  $('question').disabled=!job?.summary||job?.state!=='COMPLETED'||job?.quarantined||job?.legacyReadOnly||chatBusy||ending||(!chatStorageAvailable&&job.mode==='live');
  $('ask').disabled=$('question').disabled||!$('question').value.trim();
  $('storage-notice').textContent=chatStorageAvailable?'':'브라우저 세션 저장소를 사용할 수 없어 실제 API 채팅만 비활성화했습니다. 업로드·결과 조회는 계속 사용할 수 있으며, 데모 채팅은 이 페이지의 임시 메모리만 사용합니다.';
  $('audio').disabled=$('consent').disabled=uploading; $('delete').disabled=$('back').disabled=ending||uploading||retrying;
  renderHistory();validate();
}
async function list(){const jobs=await api('/api/jobs');const ids=jobs.map(j=>j.id);for(const id of activeJobs)if(!ids.includes(id))forgetChat(id);activeJobs=ids;
  try{for(let i=chatStorage.length-1;i>=0;i--){const key=chatStorage.key(i);if(key?.startsWith('flf-pending-chat:')&&!ids.includes(key.slice(17)))chatStorage.removeItem(key);}}catch(error){chatStorageAvailable=false;}
  heartbeatJobs=job&&!job.quarantined&&ids.includes(job.id)?[job.id]:[];return jobs;}
function setJob(next){const changed=job?.id!==next?.id;job=next;if(changed){tab='summary';chatDraft=null;chatBusy=false;pollFailures=0;$('question').value=next?(pendingChat(next.id)?.text||''):'';const pending=next&&pendingChat(next.id);if(pending)chatDraft={id:next.id,text:pending.text,error:'응답 미확인 · 같은 질문으로 다시 확인하세요.'};$('history').scrollTop=0;}if(!next){uploadAttempt=null;saved('flf-upload-attempt',null);}saved('flf-active-job',next?.id||null);heartbeatJobs=next&&!next.quarantined?[next.id]:[];render();}
$('upload').onsubmit=async event=>{event.preventDefault();if(uploading||job||!validate()||!$('consent').checked)return;uploading=true;$('error').textContent='';render();
  try{const file=selectedFile,fingerprint=JSON.stringify([file.name,file.size,file.lastModified]);
    const previous=saved('flf-upload-attempt');if(previous)uploadAttempt=JSON.parse(previous);
    if(!uploadAttempt||uploadAttempt.fingerprint!==fingerprint)uploadAttempt={fingerprint,id:crypto.randomUUID()};
    saved('flf-upload-attempt',JSON.stringify(uploadAttempt));
    const form=new FormData();form.append('audio',file);form.append('consent',$('consent').checked);
    const uploaded=await api('/api/jobs',{method:'POST',headers:{'X-FLF-Upload-ID':uploadAttempt.id},body:form});
    setJob(uploaded);
    const submitted=await api(`/api/jobs/${uploaded.id}/submit`,{method:'POST'});if(job?.id===uploaded.id)setJob(submitted);
    uploadAttempt=null;saved('flf-upload-attempt',null);
  }catch(error){report(error);}finally{uploading=false;render();}};
$('retry').onclick=async()=>{if(!job||retrying||ending||$('retry').hidden)return;retrying=true;const id=job.id;render();try{const next=await api(`/api/jobs/${id}/${job.state==='CREATED'?'submit':'retry'}`,{method:'POST'});if(job?.id===id){job=next;pollFailures=0;$('error').textContent='';}}catch(error){report(error);}finally{retrying=false;render();}};
async function endSession(){if(!job||ending||!confirm('현재 강의 세션을 종료하고 음성·결과·대화 및 앱 관리 외부 객체를 삭제할까요? 다른 탭도 종료됩니다. 새로고침은 종료가 아닙니다.'))return;
  const id=job.id;ending=true;render();try{const result=await api('/api/jobs/'+id+'/end',{method:'POST'});if(job?.id!==id)return;forgetChat(id);saved('flf-upload-attempt',null);uploadAttempt=null;selectedFile=null;$('audio').value='';$('consent').checked=false;$('file-info').textContent='선택한 파일 없음';setJob(null);$('error').textContent='';$('session-status').textContent=result.cleanupPending?'세션 종료됨 · 진행 중 호출 종료/외부 삭제 재시도 대기':'세션 종료됨 · 새 강의를 선택하세요.';}catch(error){report(error);}finally{ending=false;render();}}
$('delete').onclick=$('back').onclick=endSession;
$('question').oninput=()=>{$('ask').disabled=$('question').disabled||!$('question').value.trim();};
$('question').oncompositionstart=()=>{composing=true;};$('question').oncompositionend=()=>{composing=false;};
$('question').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&!composing&&event.keyCode!==229){event.preventDefault();$('chat').onsubmit(event);}};
$('chat').onsubmit=async event=>{event.preventDefault();const text=$('question').value.trim();if(!text||!job?.summary||job.state!=='COMPLETED'||job.quarantined||job.legacyReadOnly||chatBusy||ending||(!chatStorageAvailable&&job.mode==='live'))return;
  // Storage can become blocked after startup too. Never issue a live POST in that case.
  if(job.mode==='live'){try{chatStorage.setItem('flf-storage-probe','1');if(chatStorage.getItem('flf-storage-probe')!=='1')throw Error('storage unavailable');chatStorage.removeItem('flf-storage-probe');}catch(error){chatStorageAvailable=false;render();return;}}
  const id=job.id;chatBusy=true;chatDraft={id,text};render();try{const turn=await chatTransport.send(id,text);if(job?.id===id){if(!job.history.some(t=>t.requestId===turn.requestId))job.history.push(turn);$('question').value='';chatDraft=null;$('error').textContent='';}}catch(error){if(job?.id===id){chatDraft={id,text,error:error.message};const pending=pendingChat(id);if(pending)$('question').value=pending.text;}}finally{if(job?.id===id){chatBusy=false;render();}}};
$('demo').onclick=()=>{const n=16000,b=new ArrayBuffer(44+n*2),v=new DataView(b);const s=(o,t)=>[...t].forEach((c,i)=>v.setUint8(o+i,c.charCodeAt()));s(0,'RIFF');v.setUint32(4,36+n*2,true);s(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);s(36,'data');v.setUint32(40,n*2,true);for(let i=0;i<n;i++)v.setInt16(44+i*2,Math.sin(i*2*Math.PI*440/16000)*2000,true);choose([new File([b],'demo-tone.wav',{type:'audio/wav'})]);};
async function heartbeat(){if(ending||document.visibilityState==='hidden')return;const jobs=await list();if(job&&!jobs.some(j=>j.id===job.id)){const id=job.id;forgetChat(id);setJob(null);report(Error('강의 세션이 종료되었거나 만료되었습니다.'));}for(const id of heartbeatJobs)await api(`/api/jobs/${id}/heartbeat`,{method:'POST'});}
async function poll(){if(!job||polling||ending||pollFailures>=3||job.quarantined||job.legacyReadOnly||job.state==='COMPLETED')return;polling=true;const id=job.id;try{const previous=job.state,next=await api('/api/jobs/'+id);if(job?.id!==id)return;job=next;pollFailures=0;if(next.state==='COMPLETED'&&previous!=='COMPLETED')selectTab('summary');else render();}catch(error){if(job?.id!==id)return;if(error.status===404||error.status===410){forgetChat(id);setJob(null);report(Error('강의 세션이 종료되었거나 만료되었습니다.'));}else{pollFailures++;if(pollFailures>=3)report(Error('상태 조회가 3회 실패했습니다. 연결을 확인하고 상태 다시 확인을 눌러주세요. 원인: '+error.message));}render();}finally{polling=false;}}
$('check-status').onclick=()=>{pollFailures=0;$('error').textContent='';return poll();};
async function init(){config=await api('/api/session');$('mode').textContent=config.mode==='demo'?'DEMO · 고정 예시 · 실제 음성 인식/번역 아님 · 외부 AI API 호출 없음':'LIVE · NAVER Cloud 외부 AI 전송 · 유료 API';$('limits').textContent=`최대 ${config.maxBytes.toLocaleString()} bytes (${(config.maxBytes/1024/1024).toFixed(2)} MiB), ${config.maxSeconds}초 · 실제 형식·크기·길이는 서버가 최종 검증합니다.`;$('demo').hidden=config.mode!=='demo';
  try{const jobs=await list(),id=saved('flf-active-job');const restored=jobs.find(j=>j.id===id&&!j.quarantined)||(!id?jobs.find(j=>!j.quarantined):null);if(restored)setJob(restored);else{uploadAttempt=null;saved('flf-active-job',null);saved('flf-upload-attempt',null);render();}}catch(error){report(error);render();}
  const immediate=[...heartbeatJobs];try{for(const id of immediate)await api(`/api/jobs/${id}/heartbeat`,{method:'POST'});}catch(error){report(error);}
  setInterval(()=>heartbeat().catch(report),(config.heartbeatSeconds||30)*1000);}
document.addEventListener?.('visibilitychange',()=>{if(document.visibilityState==='visible')heartbeat().catch(report);});
init().catch(error=>{report(error);render();});
setInterval(poll,1500);
