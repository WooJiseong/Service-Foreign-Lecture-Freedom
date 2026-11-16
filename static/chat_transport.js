/* Stable, per-job chat intent. Never replace an unresolved id/question after loss. */
(function(root) {
  class ChatTransport {
    constructor(api, storage, uuid) { this.api=api; this.storage=storage; this.uuid=uuid; }
    key(id) { return 'flf-pending-chat:'+id; }
    pending(id) { const raw=this.storage.getItem(this.key(id)); return raw?JSON.parse(raw):null; }
    async send(id, question) {
      let intent=this.pending(id);
      if(intent && intent.text!==question) throw Error('이전 질문의 응답이 확인되지 않았습니다. 이전 질문으로 재확인하세요.');
      const url='/api/jobs/'+encodeURIComponent(id)+'/chat';
      if(intent) {
        try {
          const record=await this.api(url+'/requests/'+intent.requestId);
          if(record.question!==intent.text) throw Error('요청 기록이 일치하지 않습니다.');
          if(record.state==='done') { this.storage.removeItem(this.key(id)); return record.turn; }
          if(record.state==='uncertain') throw Error('제공자 응답이 불명확합니다. 관리자 대조가 필요합니다. 새 질문을 전송하지 마세요.');
        } catch(error) { if(error.status!==404) throw error; }
      } else {
        intent={text:question,requestId:this.uuid()};
        // If storage is unavailable, abort BEFORE issuing a paid request.
        this.storage.setItem(this.key(id),JSON.stringify(intent));
      }
      const turn=await this.api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(intent)});
      this.storage.removeItem(this.key(id));
      return turn;
    }
  }
  root.FLFChatTransport=ChatTransport;
  if(typeof module!=='undefined') module.exports=ChatTransport;
})(typeof window!=='undefined'?window:globalThis);
