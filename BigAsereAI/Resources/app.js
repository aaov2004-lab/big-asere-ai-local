'use strict';
const $ = id => document.getElementById(id);
const app = { chatId:null, chats:[], files:[], selectedFiles:new Set(), generating:false, controller:null, status:null, project:null, section:'chat', tab:'general', mode:'general', previewPath:'' };
async function api(path, options={}) {
  const resp=await fetch(path,{credentials:'same-origin',...options,headers:{'X-BigAsere-Request':'1','Content-Type':'application/json',...(options.headers||{})}});
  const data=await resp.json().catch(()=>({error:'El servicio devolvió una respuesta inesperada.'}));
  if(!resp.ok)throw new Error(data.error||'Error de conexión local.');
  return data;
}
let toastTimer;
function toast(message){const node=$('toast');node.textContent=message;node.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.classList.remove('show'),4200)}
function txt(tag,cls,value){const e=document.createElement(tag);if(cls)e.className=cls;e.textContent=value;return e}
async function copyText(value){
  try{await navigator.clipboard.writeText(value);toast('Copiado al portapapeles.');return}
  catch(e){const t=document.createElement('textarea');t.value=value;t.style.cssText='position:fixed;top:0;left:0;opacity:0';document.body.append(t);t.select();const ok=document.execCommand('copy');t.remove();toast(ok?'Copiado al portapapeles.':'No se pudo copiar automáticamente. Selecciona el texto manualmente.')}
}
function showSection(section){
  app.section=section;
  for(const s of ['chat','project','git','files','settings'])$(s==='chat'?'chatView':s+'View').hidden=(s!==section);
  $('pageTitle').textContent=({chat:'Asistente local',project:'Panel del proyecto',git:'Git / Código',files:'Documentos',settings:'Ajustes y ayuda'})[section];
  for(const [s,id] of Object.entries({chat:'navChats',project:'navProject',git:'navGit',files:'navFiles',settings:'navSettings'}))$(id).classList.toggle('active',s===section);
  $('sidebar').classList.remove('open');
  if(['project','git','files'].includes(section))refreshProject();
  if(section==='settings'&&app.status)$('systemPrompt').value=app.status.settings.system_prompt;
  if(section==='settings'&&app.tab==='diagnostic')runDiagnosis();
}
function settingsTab(tab){
  app.tab=tab;showSection('settings');
  for(const t of ['general','guide','safety','diagnostic']){
    $('settings'+t.charAt(0).toUpperCase()+t.slice(1)).hidden=(tab!==t);
    const btn=document.querySelector('[data-tab="'+t+'"]');btn.classList.toggle('active',tab===t);btn.setAttribute('aria-selected',String(tab===t));
  }
  if(tab==='diagnostic')runDiagnosis();
}
function chooseMode(mode){
  app.mode=mode;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));
}
async function loadStatus(){
  try{
    const status=await api('/api/status');app.status=status;
    const on=status.ollama.online;
    $('sideDot').className='indicator '+(on?'online':'offline');
    $('sideStatus').textContent=on?'Ollama conectado':'Ollama desconectado';
    $('sideModel').textContent=status.settings.model;
    $('headerStatus').textContent='';const dot=txt('i','indicator '+(on?'online':'offline'),'');$('headerStatus').append(dot,txt('span','',on?'Ollama conectado':'Desconectado'));
    $('dashOllama').textContent=on?'Conectado':'Desconectado';$('dashModel').textContent=status.settings.model;
    const select=$('modelSelect');select.textContent='';const list=[...status.ollama.models];
    if(!list.includes(status.settings.model))list.unshift(status.settings.model);
    list.forEach(name=>{const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option)});
    select.value=status.settings.model;
    $('prompt').placeholder=on?'Pregúntale algo a tu IA local…':'Abre Ollama y verifica la conexión para conversar…';
    return status;
  }catch(e){toast(e.message);return null}
}
async function refreshChats(){
  try{app.chats=(await api('/api/chats')).chats;renderChatList();$('dashChats').textContent=String(app.chats.length)}catch(e){toast(e.message)}
}
function renderChatList(){
  $('chatCount').textContent=String(app.chats.length);const wrap=$('chatList');wrap.textContent='';
  const filter=$('historySearch').value.trim().toLocaleLowerCase('es');const items=app.chats.filter(c=>c.title.toLocaleLowerCase('es').includes(filter));
  if(!items.length){wrap.append(txt('div','empty-side',filter?'Ninguna conversación coincide.':'Todavía no hay conversaciones.'));return}
  for(const c of items){
    const row=txt('div','history-row'+(app.chatId===c.id?' current':''),'');
    const open=txt('button','history-open','');open.title=c.title;open.append(txt('span','history-icon','◷'),txt('span','history-name',c.title));open.onclick=()=>openChat(c.id);
    const rename=txt('button','history-control','✎');rename.title='Renombrar chat';rename.setAttribute('aria-label','Renombrar chat');rename.onclick=async()=>{const title=prompt('Nuevo nombre de la conversación:',c.title);if(title===null)return;try{await api('/api/chats/'+c.id+'/rename',{method:'POST',body:JSON.stringify({title:title.trim()})});await refreshChats()}catch(e){toast(e.message)}};
    const del=txt('button','history-control danger','×');del.title='Eliminar chat';del.setAttribute('aria-label','Eliminar chat');del.onclick=async()=>{if(!confirm('¿Eliminar esta conversación guardada en tu Mac? Esta acción no se puede deshacer.'))return;try{await api('/api/chats/'+c.id,{method:'DELETE'});if(app.chatId===c.id){app.chatId=null;renderMessages([])}await refreshChats()}catch(e){toast(e.message)}};
    row.append(open,rename,del);wrap.append(row);
  }
}
function appendMessage(role,content,options={}){
  const msg=txt('div','msg '+role,'');if(role==='assistant')msg.append(txt('div','msg-avatar','BA'));
  const block=txt('div','msg-content','');
  if(role==='assistant'){const head=txt('div','msg-role','');head.append(txt('span','','Big Asere AI'));const cp=txt('button','msg-copy','⧉ Copiar');cp.title='Copiar esta respuesta';cp.onclick=()=>copyText(textNode.textContent);head.append(cp);block.append(head)}
  const textNode=txt('div','msg-text',content);block.append(textNode);
  if(role==='user' && options.files?.length)block.append(txt('div','msg-meta','Archivos: '+options.files.join(' · ')));
  if(role==='user' && options.git)block.append(txt('div','msg-meta','Estado Git incluido'));
  if(role==='user' && options.mode)block.append(txt('div','msg-meta','Modo: '+({general:'General',codigo:'Código',auditoria:'Auditoría',plan:'Planificación'}[options.mode]||'General')));
  msg.append(block);$('messages').append(msg);scrollBottom();return textNode;
}
function scrollBottom(){const el=$('chatScroll');requestAnimationFrame(()=>el.scrollTop=el.scrollHeight)}
function renderMessages(list){$('messages').textContent='';$('welcome').hidden=list.length>0;for(const m of list)appendMessage(m.role,m.content,{files:m.files,git:m.git,mode:m.mode})}
async function openChat(id){if(app.generating)return toast('Detén primero la respuesta actual.');try{const x=await api('/api/chats/'+id);app.chatId=id;renderMessages(x.chat.messages);showSection('chat');renderChatList()}catch(e){toast(e.message)}}
async function newChat(){if(app.generating)return toast('Detén primero la respuesta actual.');try{const x=await api('/api/chats',{method:'POST',body:'{}'});app.chatId=x.chat.id;renderMessages([]);showSection('chat');await refreshChats();$('prompt').focus()}catch(e){toast(e.message)}}
async function requireChat(){if(!app.chatId){const x=await api('/api/chats',{method:'POST',body:'{}'});app.chatId=x.chat.id}return app.chatId}
function setGenerating(busy){app.generating=busy;$('sendButton').hidden=busy;$('stopButton').hidden=!busy;$('prompt').disabled=busy;$('gitToggle').disabled=busy;document.querySelectorAll('[data-mode]').forEach(b=>b.disabled=busy)}
async function sendMessage(){
  const content=$('prompt').value.trim();if(!content||app.generating)return;
  if(app.status&&!app.status.ollama.online)return toast('Primero abre Ollama desde Ajustes y verifica la conexión.');
  let id;try{id=await requireChat()}catch(e){toast(e.message);return}
  const files=[...app.selectedFiles],git=$('gitToggle').checked,mode=app.mode;
  $('prompt').value='';$('welcome').hidden=true;appendMessage('user',content,{files,git,mode});
  const textNode=appendMessage('assistant','');const loader=txt('span','loading','');loader.innerHTML='<i></i><i></i><i></i>';textNode.append(loader);
  setGenerating(true);const controller=new AbortController();app.controller=controller;let answer='',done=false;
  try{
    const resp=await fetch('/api/chats/'+id+'/message',{method:'POST',credentials:'same-origin',signal:controller.signal,headers:{'X-BigAsere-Request':'1','Content-Type':'application/json'},body:JSON.stringify({content,files,include_git:git,mode})});
    if(!resp.ok){const err=await resp.json().catch(()=>({error:'Error de comunicación'}));throw new Error(err.error||'Error local')}
    const reader=resp.body.getReader(),decoder=new TextDecoder();let pending='';
    while(true){const packet=await reader.read();if(packet.done)break;pending+=decoder.decode(packet.value,{stream:true});let n;
      while((n=pending.indexOf('\n'))>=0){const line=pending.slice(0,n);pending=pending.slice(n+1);if(!line)continue;let item;try{item=JSON.parse(line)}catch(e){continue}
        if(item.type==='delta'){answer+=item.text;textNode.textContent=answer;scrollBottom()}
        if(item.type==='done'){done=true;if(item.error)toast('Ollama: '+item.error)}
      }
    }
    if(!answer)textNode.textContent=done?'(Ollama no devolvió texto.)':'(La respuesta se interrumpió.)';
  }catch(e){if(e.name==='AbortError'){textNode.textContent=answer?answer+'\n\n[Respuesta detenida]':'(Respuesta detenida.)'}else{textNode.textContent=answer||'Error: '+e.message;toast(e.message)}}
  finally{setGenerating(false);app.controller=null;app.selectedFiles.clear();renderContextTags();await refreshChats();$('prompt').focus()}
}
async function copyConversation(){
  if(!app.chatId)return toast('Abre o crea primero una conversación.');
  try{const {chat}=await api('/api/chats/'+app.chatId);const out='# '+chat.title+'\n\n'+chat.messages.map(m=>'## '+(m.role==='user'?'Tú':'Big Asere AI')+'\n\n'+m.content).join('\n\n---\n\n');await copyText(out)}catch(e){toast(e.message)}
}
function renderContextTags(){
  const strip=$('contextStrip');strip.textContent='';strip.hidden=!app.selectedFiles.size;
  for(const file of app.selectedFiles){const tag=txt('span','context-tag','');tag.append(txt('span','',file));const btn=txt('button','','×');btn.title='Quitar archivo';btn.onclick=()=>{app.selectedFiles.delete(file);renderContextTags();renderFileList()};tag.append(btn);strip.append(tag)}
  $('attachCount').textContent=app.selectedFiles.size+' de 4 seleccionados';
}
async function refreshProject(){
  try{
    const p=await api('/api/project');app.project=p;app.files=p.files||[];
    $('projectPath').textContent=p.configured?p.path:'Ninguna carpeta seleccionada';
    $('dashProject').textContent=p.configured?(p.path.split('/').filter(Boolean).pop()||'Carpeta conectada'):'Sin seleccionar';
    $('dashFiles').textContent=String(app.files.length);$('fileTotal').textContent=String(app.files.length);
    $('projectGitSummary').textContent=p.git?'Rama: '+(p.branch||'sin nombre')+' · '+(p.status?p.status.split('\n').length-1:0)+' entradas de estado':'No hay repositorio Git conectado.';
    $('gitBranch').textContent=p.git?(p.branch||'(HEAD separado)'):'Sin repositorio';
    $('gitPreview').textContent=p.git?(p.status||'Sin cambios locales.'):'No se detecta un repositorio Git en la carpeta.';
    $('gitLog').textContent=p.git?(p.log||'No hay commits.'):'Sin información Git.';
    $('gitDiff').textContent=p.git?(p.diffstat||'Sin cambios de trabajo en archivos rastreados.'):'Sin cambios visibles.';
    for(const file of [...app.selectedFiles])if(!app.files.includes(file))app.selectedFiles.delete(file);
    renderContextTags();renderFileList();
    if(app.previewPath&&!app.files.includes(app.previewPath)){$('previewPath').textContent='Selecciona un archivo para ver su contenido.';$('fileContent').textContent='';app.previewPath=''}
  }catch(e){toast(e.message)}
}
function renderFileList(){
  const list=$('fileList');list.textContent='';const filter=$('fileSearch').value.trim().toLocaleLowerCase('es');
  const shown=app.files.filter(f=>f.toLocaleLowerCase('es').includes(filter));
  if(!shown.length){list.append(txt('div','empty-side',filter?'No hay coincidencias.':'No hay archivos visibles. Selecciona una carpeta en el Panel del proyecto.'));return}
  for(const file of shown){
    const row=txt('div','file-item','');const ck=document.createElement('input');ck.type='checkbox';ck.checked=app.selectedFiles.has(file);ck.setAttribute('aria-label','Adjuntar '+file);
    ck.onchange=()=>{if(ck.checked){if(app.selectedFiles.size>=4){ck.checked=false;toast('Máximo 4 archivos por mensaje.');return}app.selectedFiles.add(file)}else app.selectedFiles.delete(file);renderContextTags()};
    const name=txt('span','file-filename',file);const view=txt('button','view-file','Ver');view.title='Previsualizar sin adjuntar';view.onclick=()=>previewFile(file);
    row.append(ck,name,view);list.append(row);
  }
}
async function previewFile(file){
  $('previewPath').textContent=file;$('fileContent').textContent='Leyendo archivo…';
  try{const data=await api('/api/project/file?path='+encodeURIComponent(file));app.previewPath=file;$('fileContent').textContent=data.content||'(Archivo vacío)'}catch(e){$('fileContent').textContent='No se pudo abrir: '+e.message}
}
async function selectFolder(){
  try{toast('Se abrirá Finder para seleccionar una carpeta.');await api('/api/project/select',{method:'POST',body:'{}'});await refreshProject();toast('Proyecto conectado en solo lectura.')}
  catch(e){toast(e.message)}
}
async function startOllama(){
  try{await api('/api/ollama/start',{method:'POST',body:'{}'});toast('Se solicitó abrir Ollama.');setTimeout(loadStatus,2800)}catch(e){toast(e.message)}
}
async function saveSettings(){
  try{await api('/api/settings',{method:'POST',body:JSON.stringify({system_prompt:$('systemPrompt').value,model:$('modelSelect').value})});await loadStatus();toast('Instrucciones guardadas en tu Mac.')}
  catch(e){toast(e.message)}
}
function diagnosticsEntry(name,value){const row=txt('div','diagnostic-row','');row.append(txt('span','',name),txt('strong','',String(value)));return row}
async function runDiagnosis(){
  const list=$('diagnosticList');list.textContent='Consultando…';
  try{
    const d=await api('/api/diagnostics'),s=await loadStatus();list.textContent='';
    const entries=[['Versión de la app',d.version],['Ollama',s?.ollama.online?'Conectado':'Desconectado'],['Modelo elegido',s?.settings.model||'Desconocido'],['Python local',d.python],['Git instalado',d.git_available?'Sí':'No'],['Carpeta conectada',d.project_path||'No conectada'],['Chats guardados',d.conversations],['Datos de la app',d.data_path],['asistente.py en la raíz',d.existing_scripts['asistente.py']?'Encontrado, no integrado':'No detectado'],['puente_big_asere.py en la raíz',d.existing_scripts['puente_big_asere.py']?'Encontrado, no integrado':'No detectado']];
    for(const e of entries)list.append(diagnosticsEntry(...e));
  }catch(e){list.textContent=e.message;toast(e.message)}
}
function bind(){
  $('newChat').onclick=newChat;
  for(const [id,section] of Object.entries({navChats:'chat',navProject:'project',navGit:'git',navFiles:'files',navSettings:'settings'}))$(id).onclick=()=>showSection(section);
  $('openSidebar').onclick=()=>$('sidebar').classList.add('open');$('closeSidebar').onclick=()=>$('sidebar').classList.remove('open');
  $('historySearch').oninput=renderChatList;
  $('sendButton').onclick=sendMessage;$('stopButton').onclick=()=>app.controller?.abort();$('copyChat').onclick=copyConversation;
  $('prompt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendMessage()}};
  $('prompt').oninput=()=>{$('charCounter').textContent=$('prompt').value.length+' / 16000 · ↵ enviar'};
  document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>chooseMode(b.dataset.mode));
  document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{showSection('chat');chooseMode(b.dataset.modePrompt||'general');$('prompt').value=b.dataset.prompt;$('prompt').focus()});
  $('modelSelect').onchange=async()=>{try{await api('/api/settings',{method:'POST',body:JSON.stringify({model:$('modelSelect').value})});await loadStatus();toast('Modelo actualizado.')}catch(e){toast(e.message)}};
  $('refreshStatus').onclick=async()=>{const result=await loadStatus();if(result)toast(result.ollama.online?'Ollama está conectado.':'Ollama no está disponible. Abre Ollama y vuelve a verificar.')};
  $('startOllama').onclick=startOllama;$('dashOpenOllama').onclick=startOllama;
  $('attachButton').onclick=()=>showSection('files');$('pickFolder').onclick=selectFolder;$('dashSelectFolder').onclick=selectFolder;
  $('clearFolder').onclick=async()=>{if(!confirm('¿Desvincular el proyecto? No se borrará ningún archivo.'))return;try{await api('/api/project/clear',{method:'POST',body:'{}'});app.selectedFiles.clear();await refreshProject()}catch(e){toast(e.message)}};
  $('projectGoGit').onclick=()=>showSection('git');$('projectGoFiles').onclick=()=>showSection('files');
  $('dashStartChat').onclick=()=>showSection('chat');$('dashOpenGuide').onclick=()=>settingsTab('guide');
  $('refreshGit').onclick=refreshProject;$('refreshFiles').onclick=refreshProject;$('fileSearch').oninput=renderFileList;$('goToChat').onclick=()=>showSection('chat');
  $('attachGitToChat').onclick=()=>{$('gitToggle').checked=true;showSection('chat');toast('Git se incluirá en el próximo mensaje.')} ;
  $('saveSettings').onclick=saveSettings;$('runDiagnosis').onclick=runDiagnosis;
  $('copyDataPath').onclick=async()=>{try{const d=await api('/api/diagnostics');await copyText(d.data_path)}catch(e){toast(e.message)}};
  $('quickHelp').onclick=()=>settingsTab('guide');$('welcomeHelp').onclick=()=>settingsTab('guide');$('privacyShortcut').onclick=()=>settingsTab('safety');
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>settingsTab(b.dataset.tab));
  document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();newChat()}});
}
(async()=>{bind();await Promise.all([loadStatus(),refreshChats()]);await refreshProject();showSection('chat')})();
