'use strict';
let shareFiles={},currentShare=null,savedShareUI=null;
async function shareRequest(path,data){
 const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 if(!res.ok){const err=await res.json().catch(()=>({}));throw Error(err.error||'Speichern fehlgeschlagen');}
 return res;
}
function bytes64(text){return Uint8Array.from(atob(text),c=>c.charCodeAt(0));}
function applyShareUI(ui){kind=Math.min(ui.kind,state.materials.length-1);$('view').value=ui.view;$('radius').value=ui.radius;$('temperature').value=ui.temperature;$('gravity').value=state.gravity??9.81;}
async function openShared(){
 const res=await fetch('/api/shares/'+sharedId);
 if(!res.ok)throw Error('Diese Freigabe wurde nicht gefunden.');
 const saved=await res.json();savedShareUI=saved.ui;accept(decode(bytes64(saved.frame).buffer));applyShareUI(saved.ui);readout(true);
 document.body.classList.add('shared');$('sharedNotice').hidden=false;
 $('status').textContent='GESPEICHERTE MOMENTAUFNAHME';$('toolLabel').textContent='GETEILTE KREATION';document.querySelector('.toolbar h2').textContent='Gespeicherter Moment';
 $('saveShare').textContent='Diese Kreation teilen';
}
function card(source,width,height,url){
 const c=document.createElement('canvas');c.width=width;c.height=height;const ctx=c.getContext('2d');
 ctx.fillStyle='#0a141e';ctx.fillRect(0,0,width,height);
 const pad=width*.06;ctx.fillStyle='#69e8bc';ctx.font=`bold ${Math.round(width*.045)}px sans-serif`;ctx.fillText('fluidpy / Meine Kreation',pad,height===630?65:height*.12);
 const availableH=height-(height===630?150:height*.36), availableW=width-2*pad;
 const scale=Math.min(availableW/source.width,availableH/source.height),w=source.width*scale,h=source.height*scale;
 ctx.drawImage(source,(width-w)/2,(height-h)/2,w,h);
 ctx.fillStyle='#b9d0d8';ctx.font=`${Math.round(width*.023)}px sans-serif`;
 const short=url.replace(/^https?:\/\//,'');
 ctx.fillText(short,pad,height-(height===630?27:height*.12),width-pad*2);
 return c;
}
async function png64(c){const blob=await new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(Error('Screenshot fehlgeschlagen')),'image/png'));const bytes=new Uint8Array(await blob.arrayBuffer());let str='';for(let i=0;i<bytes.length;i+=8192)str+=String.fromCharCode(...bytes.subarray(i,i+8192));return{blob,data:btoa(str)};}
async function prepareShare(sid,url){
 currentShare={id:sid,url};$('shareUrl').value=url;$('sharePreview').src='/s/'+sid+'/preview.png';
 const entries=await Promise.all(['post','story'].map(async format=>{const response=await fetch('/s/'+sid+'/'+format+'.png');if(!response.ok)throw Error('Bild nicht verfügbar');return[format,new File([await response.blob()],`fluidpy-${format}-${sid}.png`,{type:'image/png'})];}));
 shareFiles=Object.fromEntries(entries);$('facebookShare').href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(url);
 $('nativeShare').hidden=!navigator.share;$('shareReady').hidden=false;$('shareStatus').textContent='Gespeichert. Link und Bilder sind bereit.';updateShareFormat();
}
function updateShareFormat(){if(!currentShare)return;const format=$('shareFormat').value;$('downloadShare').href='/s/'+currentShare.id+'/'+format+'.png';$('downloadShare').download=`fluidpy-${format}.png`;$('imageShare').hidden=!navigator.canShare?.({files:[shareFiles[format]]});}
$('shareFormat').onchange=updateShareFormat;
$('closeShare').onclick=()=>$('shareDialog').close();
$('copyShare').onclick=async()=>{try{await navigator.clipboard.writeText(currentShare.url);$('shareStatus').textContent='Link kopiert.';}catch{$('shareUrl').select();$('shareStatus').textContent='Link markieren und kopieren.';}};
$('nativeShare').onclick=async()=>{try{await navigator.share({title:'Meine FluidPy-Kreation',url:currentShare.url});}catch(e){if(e.name!=='AbortError')$('shareStatus').textContent='Bitte den Link kopieren.';}};
$('imageShare').onclick=async()=>{try{await navigator.share({files:[shareFiles[$('shareFormat').value]],title:'Meine FluidPy-Kreation'});}catch(e){if(e.name!=='AbortError')$('shareStatus').textContent='Bitte das Bild herunterladen.';}};
$('restoreShare').onclick=async()=>{const b=$('restoreShare');b.disabled=true;try{await shareRequest('/api/restore',{id:sharedId});try{sessionStorage.setItem('fluidpy-restore-ui',JSON.stringify(savedShareUI));}catch{}location.href='/';}catch(e){b.disabled=false;$('status').textContent=e.message;}};
$('saveShare').onclick=async()=>{
 if(saving||!state)return;
 const button=$('saveShare');button.disabled=true;pointer=null;last=null;
 $('shareReady').hidden=true;$('sharePreview').removeAttribute('src');$('shareStatus').textContent='Aktuellen Moment und Screenshot speichern …';$('shareDialog').showModal();
 try{
  if(sharedId){await prepareShare(sharedId,location.origin+'/s/'+sharedId);return;}
  saving=true;
  // Finish a request already in flight, then flush clicks made before Save.
  const deadline=performance.now()+12000;
  while(inputBusy){if(performance.now()>deadline)throw Error('Server antwortet nicht. Bitte erneut versuchen.');await new Promise(r=>setTimeout(r,25));}
  while(commands.length){const cmd=commands.shift();const body={...cmd,gravity:+$('gravity').value};if(body.action===null)delete body.action;await shareRequest('/api/step',body);}
  const shot=await (await shareRequest('/api/capture',{ui:{view:$('view').value,kind,radius:+$('radius').value,temperature:+$('temperature').value}})).json();
  const frame=decode(bytes64(shot.frame).buffer);
  const c=document.createElement('canvas');c.style.cssText='position:fixed;left:-2000px;top:0;width:1200px;height:733.333px';document.body.append(c);
  let raw;
  try{
   const capture=new FluidRenderer(c);capture.assets=renderer.assets;capture.resize(1);capture.upload(frame.bytes,frame.meta.count,1);capture.draw(frame.meta,$('view').value,null,0);
   // Read back synchronously before releasing the off-screen GL context.
   // drawImage can defer GPU copies and become blank when that context is lost.
   const pixels=new Uint8Array(c.width*c.height*4);capture.gl.readPixels(0,0,c.width,c.height,capture.gl.RGBA,capture.gl.UNSIGNED_BYTE,pixels);
   if(capture.gl.getError()!==capture.gl.NO_ERROR)throw Error('WebGL-Screenshot fehlgeschlagen');
   raw=document.createElement('canvas');raw.width=c.width;raw.height=c.height;
   const ctx=raw.getContext('2d'),data=ctx.createImageData(c.width,c.height),row=c.width*4;
   for(let y=0;y<c.height;y++)data.data.set(pixels.subarray((c.height-y-1)*row,(c.height-y)*row),y*row);
   ctx.putImageData(data,0,0);
   capture.gl.getExtension('WEBGL_lose_context')?.loseContext();
  }finally{c.remove();}
  const url=shot.url;
  const [preview,post,story]=await Promise.all([[1200,630],[1080,1080],[1080,1920]].map(([w,h])=>png64(card(raw,w,h,url))));
  const saved=await (await shareRequest('/api/shares',{token:shot.token,preview:preview.data,post:post.data,story:story.data})).json();
  await prepareShare(saved.id,saved.url);
 }catch(error){$('shareStatus').textContent=error.message;}
 finally{saving=false;button.disabled=false;}
};
