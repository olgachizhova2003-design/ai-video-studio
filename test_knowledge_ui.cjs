const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=__dirname,listeners={},nodes={};
function node(id){return nodes[id]??={innerHTML:'',textContent:'',open:false,value:'',classList:{add(){},remove(){},toggle(){}},showModal(){this.open=true;},close(){this.open=false;},focus(){},setSelectionRange(){}};}
const document={querySelector:s=>node(s),querySelectorAll:()=>[],addEventListener(type,fn,capture=false){(listeners[type]??=[]).push({fn,capture});},createElement(){return {click(){}};}};
const pack=JSON.parse(fs.readFileSync(path.join(root,'knowledge-pack.json'),'utf8'));
const profiles=JSON.parse(fs.readFileSync(path.join(root,'seed-data.json'),'utf8')).profiles;
const textProfile=structuredClone(profiles.find(p=>p.id==='hf-seedance-i2v'));Object.assign(textProfile,{id:'hf-seedance-t2v',mode:'Text to Video',contract:'t2v',roles:[]});profiles.push(textProfile);
function mode(p){return p.contract;}
const fixture={profiles,documents:pack.documents.map(d=>({...d,profiles:profiles.filter(p=>!d.modes.length||d.modes.includes(mode(p))).map(p=>p.id)})),examples:structuredClone(pack.examples),workspace:{id:'main',profile_id:textProfile.id,brief:'',parameters:{},reference_ids:[],messages:[],result:null},history:[],jobs:[],references:[],categories:['Official Documentation','Prompting Guide','Best Practices','User Instructions','Examples'],settings:{prompt:{url:'https://mock.example/v1',model:'mock-no-paid-requests'},video:{}},user:{email:'alice@example.com',name:'Alice'}};
const calls=[];let holdWorkspace=false,releaseWorkspace;
async function mockApi(route,body){calls.push({route,body:structuredClone(body)});if(route==='workspace'){if(holdWorkspace)return new Promise(resolve=>{releaseWorkspace=()=>resolve(body);});return body;}if(route==='state')return fixture;if(route==='history')return {...body,id:'test-history',kind:'draft'};if(route==='example'){fixture.examples.push({...body,id:body.id||'new-user-example',generation_verified:false});return fixture.examples.at(-1);}if(route==='anatomy')return {before:body.prompt,after:body.prompt,profile_id:body.profile_id,anatomy:[{key:'subject',text:'Person',explanation:'Observed subject'}],changes:[],context:[]};if(route==='director')return {id:'mock-ai-result',result:{prompt:'A new restrained variation.',parameters:body.parameters,explanation:'Mock variation',profile_id:body.profile_id,warnings:[],context:[]}};if(route==='knowledge-backup')return {documents:[],profiles:[]};throw Error('Unexpected API call: '+route);}
class TestFormData{constructor(form){this.values=new Map(Object.entries(form.values||{}));}get(key){return this.values.get(key)??null;}has(key){return this.values.has(key);}getAll(key){return [].concat(this.get(key)||[]);}}
const sandbox={document,window:{addEventListener(){},location:{assign(){}}},navigator:{clipboard:{writeText:async()=>{}}},URL:{createObjectURL:()=>'',revokeObjectURL(){}},Blob,structuredClone,FormData:TestFormData,setTimeout:()=>0,clearTimeout(){},mockApi,fixture};
vm.createContext(sandbox);
let app=fs.readFileSync(path.join(root,'static/app.js'),'utf8');app=app.slice(0,app.lastIndexOf('(async()=>{try{S=await api('));
vm.runInContext(app,sandbox);vm.runInContext('api=mockApi;S=fixture;',sandbox);vm.runInContext(fs.readFileSync(path.join(root,'static/knowledge-ui.js'),'utf8'),sandbox);
const run=code=>vm.runInContext(code,sandbox);
const clickHandler=listeners.click.find(x=>x.capture).fn,submitHandler=listeners.submit.find(x=>x.capture).fn;
async function click(action,id=''){const button={dataset:{keAction:action,id},disabled:false};await clickHandler({target:{closest:selector=>selector==='[data-ke-action]'?button:null},preventDefault(){},stopImmediatePropagation(){}});}
async function submit(id,dataset,values){await submitHandler({target:{id,dataset,values},submitter:{disabled:false},preventDefault(){},stopImmediatePropagation(){}});}
(async()=>{
  const navigation=listeners.click.find(x=>!x.capture).fn;
  run('savedWorkspace=queuedWorkspace=JSON.stringify(S.workspace);');
  const navEvent=v=>({target:{closest:selector=>selector==='[data-view]'?{dataset:{view:v}}:null}});
  await navigation(navEvent('references'));assert.equal(calls.filter(x=>x.route==='workspace').length,0);
  holdWorkspace=true;run("S.workspace.brief='A draft that must survive slow storage';");
  await navigation(navEvent('profiles'));assert.equal(run('view'),'profiles');assert.ok(releaseWorkspace,'Save runs in the background');
  await navigation(navEvent('references'));assert.equal(run('view'),'references');assert.equal(calls.filter(x=>x.route==='workspace').length,1);
  releaseWorkspace();await run('saveQueue');holdWorkspace=false;
  fixture.references=[{id:'image9',name:'Portrait',type:'image',file:'a'.repeat(32)+'.png',role:'First Frame',description:''},{id:'video8',name:'Motion',type:'video',file:'b'.repeat(32)+'.mp4',frames:['c'.repeat(32)+'.jpg'],role:'Motion Reference',description:''}];
  const media=run('renderReferences()');assert.ok(media.includes('?preview=1')&&media.includes('loading="lazy"'));assert.ok(!media.includes('<video'),'Gallery does not start downloading original videos');
  run("showRefEditor();");assert.ok(node('#modal').innerHTML.includes('<span>Изображение, видео или аудио</span>'));assert.ok(!node('#modal').innerHTML.includes('<div class="upload-progress"'));
  fixture.references=[];fixture.workspace.brief='';run('savedWorkspace=queuedWorkspace=JSON.stringify(S.workspace);');
  run("view='knowledge';KE.tab='examples';");let html=run('renderKnowledge()');
  assert.equal((html.match(/ke-example-card/g)||[]).length,40);for(const label of ['Documents','Prompt Examples','Model Guides','Cinematography','My Instructions'])assert.ok(html.includes(label));
  assert.ok(html.includes('Использовать в студии')&&html.includes('Объяснить через AI')&&html.includes('Создать вариацию'));
  run("KE.mode='motion';");assert.equal((run('renderKnowledge()').match(/ke-example-card/g)||[]).length,8);
  run("KE.mode='';KE.tab='guides';");assert.equal((run('renderKnowledge()').match(/class=\"doc-card\"/g)||[]).length,5);
  const unsafe=structuredClone(pack.examples[0]);unsafe.title='<img src=x onerror=alert(1)>';sandbox.unsafe=unsafe;assert.ok(!run('keExampleCard(unsafe)').includes('<img src=x'));
  await click('use','ke-example-t2v-01');assert.ok(node('#modal').innerHTML.includes('ke-use-form'));
  await submit('ke-use-form',{id:'ke-example-t2v-01',operation:'use'},{profile:textProfile.id});
  assert.equal(fixture.workspace.profile_id,textProfile.id);assert.equal(fixture.workspace.parameters.duration,10);assert.ok(fixture.workspace.result.prompt.includes('letter'));assert.equal(run('tab'),'result');
  fixture.references=[{id:'image7',type:'image',role:'First Frame',name:'Hero'},{id:'image21',type:'image',role:'Style Reference',name:'Room'},{id:'video4',type:'video',role:'Motion Reference',name:'Motion'}];
  await submit('ke-use-form',{id:'ke-example-r2v-01',operation:'use'},{profile:'hf-seedance-r2v','slot-0':'image7','slot-1':'image21','slot-2':'video4'});
  assert.ok(fixture.workspace.result.prompt.includes('image7 defines'));assert.ok(fixture.workspace.result.prompt.includes('image21 defines'));assert.equal(fixture.workspace.reference_roles.image7,'Main Character');assert.equal(fixture.references[0].role,'First Frame');
  await click('explain','ke-example-motion-01');let explanation=calls.filter(x=>x.route==='anatomy').at(-1);assert.equal(explanation.body.operation,'explain');assert.equal(explanation.body.reference_ids.length,0);assert.equal(explanation.body.example_id,'ke-example-motion-01');
  await submit('ke-example-form',{id:''},{title:'User test',mode:'motion',category:'Character Acting',goal:'Source motion',prompt:'',explanation:'A user example',references:'[]',duration:'',enabled:'on'});
  assert.ok(calls.some(x=>x.route==='example'&&x.body.title==='User test'));
  await submit('ke-use-form',{id:'ke-example-t2v-02',operation:'variation'},{profile:textProfile.id,idea:'A calm station scene'});
  const variation=calls.filter(x=>x.route==='director').at(-1);assert.equal(variation.body.operation,'variation');assert.equal(variation.body.example_id,'ke-example-t2v-02');assert.ok(variation.body.before_prompt.includes('bus stop'));assert.equal(run('KE.variant'),null);
  assert.ok(calls.every(x=>!['generate','poll'].includes(x.route)));
  console.log('Knowledge UI: tabs, filters, safe rendering, editor, bindings, explanations, user examples and variations passed. No live AI or video requests.');
})().catch(error=>{console.error(error);process.exitCode=1;});
