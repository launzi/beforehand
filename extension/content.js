(()=>{
 function createContent({doc,location,sendMessage,onMessage,extract=globalThis.BeforehandExtract,card=globalThis.BeforehandCard,setInterval:every=globalThis.setInterval,clearInterval:cancel=globalThis.clearInterval}) {
  let lastURL=null,active=null,generation=0,stopped=false,onQuoteChanged=null;
  const changed=message=>{if(message?.type==='quote_changed')onQuoteChanged?.(message.handle);};
  onMessage?.addListener(changed);
  async function tick() {
   if(stopped || doc.visibilityState!=='visible' || location.href===lastURL) return;
   lastURL=location.href;const run=++generation;active?.destroy();active=null;
   const product=extract.extractFromParts(extract.readPageParts(doc,location.hostname),location.hostname);if(!product)return;
   const input={name:product.name,brand:product.brand},local={price:product.price,currency:product.currency};
   const alive=()=>!stopped && generation===run && location.href===lastURL;
   let status;try {status=await sendMessage({type:'status'});}catch{return;}
   if(!alive() || !status?.onboarded || !status.shopEnabled)return;
   let checking=false,handle=null;
   async function check(manual) {
    if(!alive() || checking)return;checking=true;instance.setState({view:'loading'});
    try {
     const reply=await sendMessage({type:'match',product:input,manual});
     if(alive()) {handle=reply?.handle;instance.setState({...reply,view:['same','alternatives','none','cant_ship','paused'].includes(reply?.kind)?reply.kind:'busy',local,destination:status.destination});}
    }catch {if(alive())instance.setState({view:'busy'});}finally{checking=false;}
   }
   const instance=card.mount(doc,{onCheck:()=>check(true),onBuy:async choice=>{
    if(!alive())return;
    try {const reply=await sendMessage({type:'open_checkout',handle,choice});if(alive())instance.setState({view:reply?.ok?'opened':reply?.error==='changed'?'changed':'busy'});}
    catch {if(alive())instance.setState({view:'busy'});}
   }});
   active=instance;
   onQuoteChanged=changedHandle=>{if(alive() && changedHandle===handle)instance.setState({view:'changed'});};
   if(status.autoCheck)await check(false);else instance.setState({view:'manual'});
  }
  const timer=every(()=>{void tick();},1000);
  return {tick,destroy(){stopped=true;generation++;cancel(timer);onMessage?.removeListener(changed);active?.destroy();active=null;}};
 }
 globalThis.BeforehandContent={createContent};
 if(globalThis.document && globalThis.chrome?.runtime?.sendMessage) {
  const app=createContent({doc:document,location:globalThis.location,sendMessage:message=>chrome.runtime.sendMessage(message),onMessage:chrome.runtime.onMessage});void app.tick();
  globalThis.addEventListener?.('pagehide',()=>app.destroy(),{once:true});
 }
})();
