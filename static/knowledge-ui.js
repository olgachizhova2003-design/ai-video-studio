'use strict';
const KE={tab:'documents',mode:'',category:'',provider:'',search:'',analysis:null,variant:null};
const keModes={t2v:'Seedance · Text to Video',i2v:'Seedance · Image to Video',r2v:'Seedance · Reference to Video',motion:'Genjutsu · Motion Transfer',swap:'Genjutsu · Object Swap'};
const keLabels={subject:'Главный объект',action:'Действие',environment:'Окружение',timeline:'Временная последовательность',camera:'Камера',lighting:'Освещение',style:'Стиль',audio:'Звук',references:'Роли референсов',preservation:'Сохранение деталей'};
const keButton=(text,action,id='',classes='small ghost')=>`<button type="button" class="btn ${classes}" data-ke-action="${action}" data-id="${esc(id)}">${text}</button>`;
const keMode=p=>['t2v','i2v','r2v','motion','swap'].includes(p.contract)?p.contract:({'text to video':'t2v','image to video':'i2v','reference to video':'r2v','motion transfer':'motion','object swap':'swap'}[String(p.mode).toLowerCase().replaceAll('-',' ')]||p.knowledge_mode||'');
const keCollection=d=>d.collection||(d.category==='User Instructions'?'instructions':d.id==='cinematic-notes'?'cinematography':'documents');
const keBaseApi=api;
api=async function(path,body){
  if(body&&['director','prepare','context','anatomy'].includes(path)){
    body={...body,reference_roles:body.reference_roles||S?.workspace?.reference_roles||{}};
    if(path==='director'&&KE.variant)body={...body,operation:'variation',example_id:KE.variant.id,before_prompt:S.workspace.result?.prompt||'',instruction:'Create a new variation for the current idea while preserving this mode, reference roles and mandatory source motion. Change only the creative emphasis; do not copy the example verbatim.'};
  }
  return keBaseApi(path,body);
};

function keMarkdown(text){
  let code=false,out=[];
  for(const line of String(text).split('\n')){
    if(line.startsWith('```')){out.push(code?'</code></pre>':'<pre class="ke-prompt"><code>');code=!code;continue;}
    if(code){out.push(esc(line)+'\n');continue;}
    const heading=line.match(/^(#{1,6})\s+(.+)/);
    if(heading){const level=Math.min(4,heading[1].length+1);out.push(`<h${level}>${esc(heading[2])}</h${level}>`);}
    else if(line.trim())out.push(`<p>${esc(line)}</p>`);
  }
  if(code)out.push('</code></pre>');return out.join('');
}
function keFilter(item){
  const modes=item.modes||[item.mode].filter(Boolean);
  const text=[item.title,item.category,item.content,item.prompt,item.goal,item.explanation,...(item.tags||[])].join(' ').toLowerCase();
  const providers=item.providers||(item.profiles||[]).map(id=>S.profiles.find(p=>p.id===id)?.provider).filter(Boolean);
  return (!KE.mode||modes.includes(KE.mode)||(!modes.length&&(!(item.profiles||[]).length||(item.profiles||[]).some(id=>keMode(S.profiles.find(p=>p.id===id)||{})===KE.mode))))&&(!KE.category||item.category===KE.category)&&(!KE.provider||!providers.length||providers.includes('*')||providers.includes(KE.provider))&&(!KE.search||text.includes(KE.search.toLowerCase()));
}
function keExampleCard(e){
  const required=e.references||[];
  return `<article class="doc-card ke-example-card"><div class="card-top"><div class="card-icon ${['motion','swap'].includes(e.mode)?'pink':''}">${icon(['motion','swap'].includes(e.mode)?'video':'spark')}</div>${badge('Не проверено генерацией','pink')}</div><div class="category">${esc(e.category)}</div><h2>${esc(e.title)}</h2><p class="help">${esc(keModes[e.mode]||e.mode)} · ${esc(e.duration_seconds?e.duration_seconds+' сек · рекомендация':'Время исходного видео')}${e.enabled?'':' · Отключён в контексте'}</p><p>${esc(e.goal)}</p><details class="ke-details"><summary>Промпт и объяснение</summary><pre class="ke-prompt">${esc(e.prompt||'Пустой prompt: только обязательные видео и изображения.')}</pre><p><strong>Конструкция.</strong> ${esc(e.explanation||'')}</p><p><strong>Почему эти слова.</strong> ${esc(e.wording_reason||'')}</p><p><strong>Возможные ошибки.</strong> ${esc(e.risks||'')}</p><p><strong>Как адаптировать.</strong> ${esc(e.adaptation||'')}</p></details><div class="ke-reference-list">${required.length?required.map(r=>`<span>${esc(r.slot||r.type)} · ${esc(r.purpose||r.role)}</span>`).join(''):'Референсы не требуются'}</div><p class="help">${esc(e.source||'Авторский пример')} · ${esc(e.verification_note||'Не проверено реальной генерацией')}</p><div class="card-actions">${keButton('Использовать в студии','use',e.id,'small')}${keButton('Объяснить через AI','explain',e.id)}${keButton('Создать вариацию','variation',e.id)}${keButton('Редактировать','edit-example',e.id)}</div></article>`;
}
renderKnowledge=function(){
  const tabs=[['documents','Documents'],['examples','Prompt Examples'],['guides','Model Guides'],['cinematography','Cinematography'],['instructions','My Instructions']];
  const base=KE.tab==='examples'?(S.examples||[]):S.documents.filter(d=>keCollection(d)===KE.tab);
  const items=base.filter(keFilter),categories=[...new Set(base.map(d=>d.category))].sort();
  return `${heading('Библиотека знаний','Руководства, примеры и ваши инструкции — с источниками и понятными ролями.',`<div class="inline-actions">${keButton('Резервная копия до v2','backup')}${KE.tab==='examples'?keButton('Свой пример','new-example','','primary'):`${btn('Загрузить .md / .txt','import-doc','upload','ghost')}${KE.tab==='instructions'?keButton('Новая инструкция','new-instruction','','primary'):btn('Новый документ','add-doc','plus','primary')}`}</div>`)}<div class="tabstrip ke-tabs" role="tablist">${tabs.map(([key,label])=>`<button role="tab" aria-selected="${KE.tab===key}" data-ke-action="tab" data-id="${key}" class="${KE.tab===key?'active':''}">${label}</button>`).join('')}</div><div class="toolbar ke-toolbar"><input name="ke-search" placeholder="Поиск по содержимому, цели и приёмам…" value="${esc(KE.search)}"><select name="ke-mode" aria-label="Режим">${option('','Все режимы',!KE.mode)}${Object.entries(keModes).map(([key,label])=>option(key,label,key===KE.mode)).join('')}</select><select name="ke-provider" aria-label="Провайдер">${option('','Все провайдеры',!KE.provider)}${['higgsfield','atlas','nano'].map(id=>option(id,providerName(id),KE.provider===id)).join('')}</select><select name="ke-category" aria-label="Категория">${option('','Все категории',!KE.category)}${categories.map(value=>option(value,value,value===KE.category)).join('')}</select></div><p class="help">${items.length} из ${base.length} · Только активные и совместимые материалы участвуют в контексте. Объяснение и вариации используют ваш Prompt AI и могут тарифицироваться.</p><div class="card-grid ke-cards">${items.map(item=>KE.tab==='examples'?keExampleCard(item):`<article class="doc-card"><div class="card-top"><div class="card-icon ${KE.tab==='instructions'?'pink':''}">${icon('file')}</div><label class="check-group"><input type="checkbox" data-doc-enable="${esc(item.id)}" ${item.enabled?'checked':''}>В контексте</label></div><div class="category">${esc(item.category)}</div><h2>${esc(item.title)}</h2><p>${esc(item.content.replace(/#+/g,'').slice(0,165))}…</p><div class="card-meta"><span>v${item.version}</span><span>${(item.modes||[]).map(mode=>esc(keModes[mode]||mode)).join(' · ')||'По назначенным профилям'}</span></div><div class="card-actions">${keButton('Читать','read-doc',item.id,'small')}${btn('Редактировать','edit-doc','edit','small ghost',`data-id="${esc(item.id)}"`)}${btn('Экспорт','export-doc','download','small ghost',`data-id="${esc(item.id)}"`)}</div></article>`).join('')||'<div class="panel empty">Нет совпадений. Измените фильтры или добавьте собственный материал.</div>'}</div>`;
};

function keReadDoc(id){
  const d=S.documents.find(d=>d.id===id);if(!d)return;
  openModal(esc(d.title),`<article class="ke-reader">${keMarkdown(d.content)}</article>`,btn('Закрыть','close','','ghost')+btn('Редактировать','edit-doc','edit','primary',`data-id="${esc(id)}"`));
}
function keReadExample(id){
  const e=(S.examples||[]).find(e=>e.id===id);if(!e)return;
  openModal(esc(e.title),keExampleCard(e),btn('Закрыть','close','','ghost'));
}
function keEditExample(id){
  const e=(S.examples||[]).find(e=>e.id===id)||{id:'',mode:keMode(profile())||'t2v',title:'',category:'Character Acting',goal:'',prompt:'',explanation:'',wording_reason:'',risks:'',adaptation:'',references:[],duration_seconds:8,enabled:true};
  openModal(e.id?'Ваш пример · редактирование':'Новый пример',`<form id="ke-example-form" data-id="${esc(e.id)}">${field('Название',input('title',e.title,'Название примера','text','required'))}<div class="form-row">${field('Режим',`<select name="mode">${Object.entries(keModes).map(([key,label])=>option(key,label,key===e.mode)).join('')}</select>`)}${field('Категория',input('category',e.category))}</div>${field('Цель',textarea('goal',e.goal,'Что должно произойти в кадре?','required'))}${field('Промпт на английском',textarea('prompt',e.prompt,'Для Genjutsu допустима пустая строка'))}${field('Разбор конструкции',textarea('explanation',e.explanation||''))}${field('Почему выбраны эти слова',textarea('wording_reason',e.wording_reason||''))}${field('Возможные ошибки',textarea('risks',e.risks||''))}${field('Как адаптировать',textarea('adaptation',e.adaptation||''))}${field('Референсы · JSON',textarea('references',JSON.stringify(e.references||[],null,2),'[{"slot":"image1","type":"image","role":"First Frame","purpose":"Начальный кадр"}]','class="code"'))}${field('Рекомендуемые секунды · пусто, если время задаёт исходник',input('duration',e.duration_seconds??'','','number','min="4" max="30"'))}<label class="check-group"><input type="checkbox" name="enabled" ${e.enabled?'checked':''}>Использовать в автоматическом контексте</label><p class="help">Авторский пример сохраняется как не проверенный реальной генерацией. Добавление примера не запускает AI или видео.</p></form>`,btn('Отмена','close','','ghost')+'<button class="btn primary" type="submit" form="ke-example-form">Сохранить пример</button>');
}
function kePickExample(id,operation='use'){
  const e=(S.examples||[]).find(x=>x.id===id);if(!e)return;
  const compatible=S.profiles.filter(p=>keMode(p)===e.mode&&(!e.providers||e.providers.includes('*')||e.providers.includes(p.provider)));
  if(!compatible.length){toast('Добавьте совместимый профиль этого режима');return;}
  const preferred=compatible.find(p=>p.id===profile().id)||compatible.find(p=>p.provider===profile().provider)||compatible[0];
  const slots=e.references||[];
  openModal(operation==='variation'?'Настроим вариацию':'Пример → ваша студия',`<form id="ke-use-form" data-id="${esc(id)}" data-operation="${operation}">${field('Профиль видеомодели',`<select name="profile">${compatible.map(p=>option(p.id,p.name+' · '+p.mode,p.id===preferred.id)).join('')}</select>`)}<p class="help">Свяжите смысловые слоты с вашими файлами. Роли действуют в текущем замысле и не меняют общую библиотеку референсов.</p>${slots.map((slot,index)=>{const available=S.references.filter(r=>r.type===slot.type);const selected=chosen().find(r=>r.type===slot.type&&r.role===slot.role);return field(esc((slot.slot||slot.type)+' · '+(slot.purpose||slot.role)),`<select name="slot-${index}" required>${option('','Выберите файл',!selected)}${available.map(r=>option(r.id,r.id+' · '+r.name,r.id===selected?.id)).join('')}</select>`);}).join('')}${!slots.length?'<p>Референсы не требуются. Text to Video создаст новую сцену из текста.</p>':''}<p class="help">Если нужного файла нет, закройте окно, добавьте его в «Референсы» и вернитесь. Текущий замысел будет сохранён в истории перед применением.</p>${operation==='variation'?field('Какой вариант нужен?',textarea('idea',S.workspace.brief||e.goal,'Уточните желаемое изменение')):''}</form>`,btn('Отмена','close','','ghost')+`<button class="btn primary" type="submit" form="ke-use-form">${operation==='variation'?'Применить и создать вариацию через AI':'Открыть в редакторе промпта'}</button>`);
}
function keAnalysisView(result,canApply=true){
  KE.analysis=result;
  openModal('Prompt Anatomy · Before / After',`<div class="ke-comparison"><section><h3>Исходный запрос</h3><pre class="ke-prompt">${esc(result.before||'Пустой prompt')}</pre></section><section><h3>Вариант с учётом режима</h3><pre class="ke-prompt">${esc(result.after||'Пустой prompt — исходные медиа задают задачу')}</pre></section></div><div class="ke-anatomy">${(result.anatomy||[]).map(part=>`<section><h3>${esc(keLabels[part.key]||part.key)}</h3><p>${esc(part.text||'Не задано')}</p><p class="help">${esc(part.explanation)}</p></section>`).join('')}</div>${(result.changes||[]).map(change=>`<p><strong>${esc(change.what)}</strong><br>${esc(change.why)}</p>`).join('')}<p class="help">${(result.context||[]).length} фрагментов с источниками. AI-разбор не подтверждает качество реальной видеогенерации.</p>`,btn('Закрыть','close','','ghost')+(canApply?keButton('Применить вариант','apply-analysis','','primary'):''));
}
async function keAnalyze(operation='analyze',exampleId){
  let p=profile(),prompt=tab==='idea'?S.workspace.brief:(S.workspace.result?.prompt??S.workspace.brief),refs=S.workspace.reference_ids,roles=S.workspace.reference_roles||{};
  if(exampleId){const e=S.examples.find(x=>x.id===exampleId);p=S.profiles.find(x=>keMode(x)===e.mode&&x.provider===p.provider)||S.profiles.find(x=>keMode(x)===e.mode);prompt=e.prompt;refs=[];roles={};}
  if(!p){toast('Выберите совместимый профиль');return;}
  toast('AI разбирает промпт…');
  const result=await api('anatomy',{profile_id:p.id,prompt,reference_ids:refs,reference_roles:roles,operation,example_id:exampleId});keAnalysisView(result,!exampleId);
}
const keBaseResult=renderResult;
renderResult=function(){const r=S.workspace.result;return keBaseResult()+(!r?'':`<div class="ke-result-tools"><div class="inline-actions">${keButton('Разобрать промпт','analyze')}${keButton('Before / After через AI','improve')}</div>${r.before?`<details class="ke-details"><summary>До / после создания промпта</summary><div class="ke-comparison"><section><h3>Исходный запрос</h3><p>${esc(r.before)}</p></section><section><h3>Готовый промпт</h3><p>${esc(r.prompt||'Пустой prompt')}</p></section></div><p>${esc(r.explanation||'')}</p></details>`:''}${r.context_info?`<p class="help">Контекст ${esc(keModes[r.context_info.mode]||r.context_info.mode)} · ${(r.context_info.examples||[]).length} примера · ${r.context_info.characters} символов с метаданными.</p>`:''}</div>`);};
const keBaseStudio=renderStudio;
renderStudio=function(){return keBaseStudio()+(tab==='idea'?`<div class="ke-idea-tools">${keButton('Разобрать текущий запрос через AI','analyze')}${keButton('Before / After','improve')}<span class="help">Разбор и улучшение используют Prompt AI.</span></div>`:'');};
showContext=async function(){
  const docs=await api('context',{profile_id:profile().id,query:S.workspace.brief,reference_ids:S.workspace.reference_ids});
  openModal('Контекст AI Director',`<p class="help">Выбран только текущий режим и провайдер. Примеры — учебные, не проверенные видеогенерацией.</p>${docs.map(d=>`<section class="ke-context-item"><h3>${esc(d.title)} · ${esc(d.heading)}</h3><p class="help">${esc(d.kind||'document')} · v${d.version} · ${esc(d.source||'Авторский материал')}</p><pre class="ke-prompt">${esc(d.content)}</pre></section>`).join('')||'<p>Совместимых материалов нет. Назначьте документ текущему профилю.</p>'}`,btn('Закрыть','close','','ghost'));
};

document.addEventListener('click',async event=>{
  const oldDoc=event.target.closest('[data-action="read-doc"]');
  if(oldDoc&&(S.examples||[]).some(e=>e.id===oldDoc.dataset.id)){event.stopImmediatePropagation();keReadExample(oldDoc.dataset.id);return;}
  const button=event.target.closest('[data-ke-action]');if(!button)return;
  event.preventDefault();event.stopImmediatePropagation();const {keAction:action,id}=button.dataset;
  try{
    if(action==='tab'){KE.tab=id;KE.category='';render();}
    if(action==='read-doc')keReadDoc(id);
    if(action==='edit-example')keEditExample(id);
    if(action==='new-example')keEditExample();
    if(action==='new-instruction'){showDocEditor();editorDoc.collection='instructions';$('#doc-form').elements.category.value='User Instructions';}
    if(action==='use'||action==='variation')kePickExample(id,action);
    if(action==='explain'){button.disabled=true;await keAnalyze('explain',id);}
    if(action==='analyze'||action==='improve'){button.disabled=true;await keAnalyze(action==='improve'?'improve':'analyze');}
    if(action==='apply-analysis'){
      const r=KE.analysis;if(!r||r.profile_id!==profile().id)throw Error('Выбран другой профиль. Повторите разбор для текущего режима.');
      S.workspace.result={...(S.workspace.result||{}),prompt:r.after,before:r.before,explanation:(r.changes||[]).map(x=>x.what+' — '+x.why).join('\n'),context:r.context,parameters:params(),profile_id:profile().id,warnings:r.warnings||[]};
      await saveWorkspace();closeModal();tab='result';view='studio';render();
    }
    if(action==='backup'){const value=await api('knowledge-backup');download('ai-video-studio-before-knowledge-v2.json',value);toast('Снимок профилей и документов до миграции выгружен. API-ключей в нём нет.');}
  }catch(error){toast(error.message);}finally{button.disabled=false;}
},true);
document.addEventListener('change',event=>{
  const key={'ke-mode':'mode','ke-category':'category','ke-provider':'provider'}[event.target.name];if(key){event.stopImmediatePropagation();KE[key]=event.target.value;render();}
},true);
document.addEventListener('input',event=>{
  if(event.target.name!=='ke-search')return;
  const caret=event.target.selectionStart;KE.search=event.target.value;render();const search=$('[name=ke-search]');search?.focus();search?.setSelectionRange(caret,caret);
},true);
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['ke-example-form','ke-use-form'].includes(form.id))return;
  event.preventDefault();event.stopImmediatePropagation();const submit=event.submitter;submit.disabled=true;
  try{
    const values=new FormData(form);
    if(form.id==='ke-example-form'){
      const previous=(S.examples||[]).find(x=>x.id===form.dataset.id)||{};
      const data={...previous,id:form.dataset.id,title:values.get('title'),mode:values.get('mode'),category:values.get('category'),goal:values.get('goal'),prompt:values.get('prompt'),explanation:values.get('explanation'),wording_reason:values.get('wording_reason'),risks:values.get('risks'),adaptation:values.get('adaptation'),references:JSON.parse(values.get('references')||'[]'),duration_seconds:values.get('duration')?Number(values.get('duration')):null,enabled:values.has('enabled')};
      await api('example',data);await reload();closeModal();render();toast('Пример сохранён и доступен автоматическому подбору');
    }else{
      const e=S.examples.find(x=>x.id===form.dataset.id),p=S.profiles.find(p=>p.id===values.get('profile'));
      const assignments={},slots={},ids=[];
      for(const [index,slot] of (e.references||[]).entries()){
        const refId=values.get('slot-'+index),r=S.references.find(r=>r.id===refId);
        if(!r||r.type!==slot.type)throw Error('Выберите файл для каждого слота');
        if(!p.roles.includes(slot.role))throw Error('Профиль не поддерживает роль '+slot.role);
        if(assignments[refId]&&assignments[refId]!==slot.role)throw Error('Одному файлу назначены несовместимые роли');
        assignments[refId]=slot.role;slots[slot.slot]=refId;if(!ids.includes(refId))ids.push(refId);
      }
      const prompt=e.prompt.replace(/\b(?:image|video|audio)\d+\b/g,slot=>{if(!slots[slot])throw Error('Не назначен слот '+slot);return slots[slot];});
      if(S.workspace.brief?.trim()||S.workspace.result?.prompt?.trim())await saveDraft();
      const parameters=defaults(p);
      if(e.duration_seconds&&p.schema.duration&&(p.schema.duration.enum||[]).includes(e.duration_seconds))parameters.duration=e.duration_seconds;
      S.workspace={id:'main',profile_id:p.id,brief:values.get('idea')||e.goal,reference_ids:ids,reference_roles:assignments,parameters,messages:[],result:{prompt,before:e.goal,parameters,profile_id:p.id,context:[],document_ids:[],explanation:e.explanation,warnings:['Авторский учебный пример. Реальная видеогенерация по нему не проверена.']}};
      await saveWorkspace();closeModal();view='studio';tab='result';render();
      if(form.dataset.operation==='variation'){KE.variant=e;try{await direct();}finally{KE.variant=null;}}
      else toast('Пример открыт в редакторе. Референсы связаны с вашими файлами.');
    }
  }catch(error){toast(error.message);}finally{submit.disabled=false;}
},true);
if(typeof S!=='undefined'&&S)render();
