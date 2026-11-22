import copy,json,unittest
from app import create_app
from test_online import FakeSupabase

class StoryAcceptance(unittest.TestCase):
 def setUp(self):
  self.store=FakeSupabase();self.config={'TESTING':True,'SECRET_KEY':'test-session-secret-32-characters-long','MASTER_KEY':'test-master-secret-32-characters-long','ALLOWED_EMAILS':'alice@example.com,bob@example.com'}
  self.app=create_app(self.config,self.store);self.client=self.app.test_client();self.e=self.app.extensions['studio_engine'];self.s=self.app.extensions['studio_story'];self.calls=[]
  csrf=self.req('/auth/csrf').json['csrf'];self.csrf=self.req('/auth/login',{'email':'alice@example.com','password':'test-password-only'},csrf).json['csrf'];self.req('/api/state')
  self.p=self.req('/api/story/project',{'title':'Private test series','canon':'Approved: the partners are equals. The tattoo is on the anatomical LEFT side.','open_questions':'Origin of the tattoo is not approved.','characters':[{'id':'hero','name':'Private Hero','age':'28','appearance':'Amber eyes, left shoulder tattoo','personality':'Playful, not a cold boss','history':'Approved history','relationships':'Partners are equals'}],'assets':[]}).json
  self.ep=self.req('/api/story/episode',{'project_id':self.p['id'],'title':'Pilot','brief':'A draft, not approved canon','number':1,'scenes':[{'id':'scene','title':'Bar scene','location':'Bar','time':'Night','goal':'Observe','conflict':'Trust','outcome':'Suspicion','script':'Original script','notes':'','character_ids':['hero'],'shots':[{'id':'shot','title':'Reaction','duration':6,'character_ids':['hero'],'action':'Looks up','asset_needs':[{'id':'need','kind':'outfit','name':'Same outfit','character_id':'hero','description':'Keep exact costume'}]}]}]}).json
  settings=self.req('/api/state').json['settings'];settings['prompt'].update(url='https://mock.example/v1',model='mock-model');self.req('/api/settings',{'settings':settings,'keys':{'prompt':'private-test-key'}})
  self.answer={'summary':'Proposal','synopsis':'A proposed synopsis','script':'A proposed scene','scenes':[{'title':'Proposed outline scene','character_ids':['hero'],'script':'Proposed outline script'}],'shots':[{'title':'A new reaction','duration':6,'character_ids':['hero'],'action':'A restrained look','asset_needs':[{'kind':'face','name':'Hero portrait','character_id':'hero','description':'Identity reference, not a first frame'},{'kind':'location','name':'Bar','description':'Empty location reference'},{'kind':'first_frame','name':'Composite','description':'Prepare the hero in the bar externally'}]}],'issues':['Causality needs clarification'],'questions':['What is approved?']}
  def mock(url,key,payload,*args,**kw):
   self.calls.append(payload)
   if 'screenplay collaborator' in payload['messages'][0]['content']:return {'choices':[{'message':{'content':json.dumps(self.answer)}}]}
   return {'choices':[{'message':{'content':json.dumps({'prompt':'The supplied first frame comes alive.','parameters':json.loads(payload['messages'][1]['content'][0]['text'])['current_parameters'],'warnings':[],'document_ids':[],'explanation':'Test only'})}}]}
  self.e.api_request=mock
 def req(self,path,body=None,csrf=None,client=None):
  return (client or self.client).open(path,base_url='https://studio.example',method='POST' if body is not None else 'GET',json=body,headers={'Origin':'https://studio.example','X-Studio-Request':'local','X-CSRF-Token':csrf or getattr(self,'csrf','')})
 def analyze(self,operation):
  r=self.req('/api/story/analyze',{'operation':operation,'project_id':self.p['id'],'episode_id':self.ep['id'],'scene_id':'scene','instruction':'Preserve the canon'});self.assertEqual(r.status_code,200,r.json);return r.json
 def test_story_requires_login_and_csrf(self):
  anonymous=self.app.test_client();self.assertEqual(self.req('/api/story/state',client=anonymous).status_code,401)
  self.assertEqual(self.req('/api/story/project',{'title':'x'},csrf='wrong').status_code,403)
 def test_version_conflicts_and_restore_keep_prior_text(self):
  new=self.req('/api/story/episode',{**self.ep,'synopsis':'Changed'});self.assertEqual(new.status_code,200,new.json)
  stale=self.req('/api/story/episode',self.ep);self.assertEqual(stale.status_code,409)
  revisions=self.req('/api/story/revisions',{'kind':'episodes','id':self.ep['id']}).json;self.assertEqual(len(revisions),1)
  restored=self.req('/api/story/restore',{'revision_id':revisions[0]['id'],'version':new.json['version']});self.assertEqual(restored.status_code,200,restored.json);self.assertEqual(restored.json['scenes'][0]['script'],'Original script');self.assertEqual(restored.json['version'],3)
 def test_all_ai_operations_propose_without_changing_canon_or_script(self):
  before=copy.deepcopy(self.store.rows)
  for operation in ['develop','outline','scene','shots','assets','review']:
   suggestion=self.analyze(operation);self.assertEqual(suggestion['status'],'proposed')
   self.assertEqual(self.store.get('story_episodes',self.ep['id']),self.ep);self.assertEqual(self.store.get('story_projects',self.p['id']),self.p)
   payload=self.calls[-1];data=json.loads(payload['messages'][1]['content']);self.assertIn('LEFT',data['series_bible']['canon']);self.assertIn('not approved',data['series_bible']['open_questions']);self.assertNotIn('private-test-key',json.dumps(payload));self.assertIn('No images',data['media_notice']);self.assertIn('first frame',payload['messages'][0]['content'])
  self.assertFalse(self.store.all('jobs'))
 def test_review_and_episode_development_receive_the_full_saved_script(self):
  for operation in ['develop','outline','review']:
   self.analyze(operation);data=json.loads(self.calls[-1]['messages'][1]['content'])
   self.assertEqual(data['episode']['scenes'][0]['script'],'Original script');self.assertIsNone(data['scene'])
 def test_apply_only_changes_selected_part_and_records_revision(self):
  suggestion=self.analyze('scene');r=self.req('/api/story/apply',{'id':suggestion['id']});self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['scenes'][0]['script'],'A proposed scene');self.assertEqual(r.json['scenes'][0]['shots'],self.ep['scenes'][0]['shots']);self.assertEqual(self.store.get('story_projects',self.p['id']),self.p)
  self.assertEqual(self.req('/api/story/apply',{'id':suggestion['id']}).status_code,409);self.assertEqual(len(self.store.all('story_revisions')),1)
 def test_outline_applies_scenes_only_and_keeps_episode_brief(self):
  suggestion=self.analyze('outline');r=self.req('/api/story/apply',{'id':suggestion['id']});self.assertEqual(r.status_code,200,r.json)
  self.assertEqual(r.json['scenes'][0]['script'],'Proposed outline script');self.assertEqual(r.json['brief'],self.ep['brief']);self.assertEqual(self.store.get('story_projects',self.p['id']),self.p)
 def test_stale_suggestions_and_invalid_character_ids_are_rejected(self):
  suggestion=self.analyze('shots');self.req('/api/story/project',{**self.p,'canon':'New approved canon'})
  self.assertEqual(self.req('/api/story/apply',{'id':suggestion['id']}).status_code,409)
  self.answer['shots'][0]['character_ids']=['invented-person'];self.assertEqual(self.req('/api/story/analyze',{'operation':'shots','project_id':self.p['id'],'episode_id':self.ep['id'],'scene_id':'scene'}).status_code,400)
 def test_asset_readiness_requires_an_existing_file_and_matching_type(self):
  r={'id':'image7','name':'Face','type':'image','role':'First Frame','remote_url':'https://example.com/a.png','width':1024,'height':1024,'size':1000}
  self.store.put('references',r);asset={'id':'face','kind':'face','name':'Hero portrait','character_id':'hero','description':'Identity','reference_id':'image7'}
  self.p=self.req('/api/story/project',{**self.p,'assets':[asset]}).json
  plan=self.req('/api/story/plan',{'project_id':self.p['id'],'episode_id':self.ep['id'],'scene_id':'scene','shot_id':'shot'}).json
  self.assertTrue(next(a for a in plan if a['kind']=='face')['ready']);self.assertFalse(next(a for a in plan if a['kind']=='location')['ready'])
  self.assertEqual(self.req('/api/story/project',{**self.p,'assets':[{**asset,'kind':'motion'}]}).status_code,400)
 def test_shot_handoff_does_not_generate_or_modify_the_current_workspace(self):
  before=self.req('/api/state').json['workspace'];r=self.req('/api/story/handoff',{'project_id':self.p['id'],'episode_id':self.ep['id'],'scene_id':'scene','shot_id':'shot','profile_id':'hf-seedance-i2v','bindings':[]});self.assertEqual(r.status_code,200,r.json)
  self.assertTrue(r.json['warnings']);self.assertEqual(r.json['parameters']['duration'],6);self.assertEqual(r.json['story_context']['characters'][0]['id'],'hero');self.assertEqual(self.req('/api/state').json['workspace'],before);self.assertFalse(self.calls);self.assertFalse(self.store.all('jobs'))
 def test_handoff_context_reaches_prompt_ai_and_stale_source_is_blocked(self):
  r=self.req('/api/story/handoff',{'project_id':self.p['id'],'episode_id':self.ep['id'],'scene_id':'scene','shot_id':'shot','profile_id':'hf-seedance-i2v','bindings':[]}).json
  body={k:r[k] for k in ['profile_id','brief','parameters','reference_ids','reference_roles','story_source']}
  response=self.req('/api/director',body);self.assertEqual(response.status_code,200,response.json)
  data=json.loads(self.calls[-1]['messages'][1]['content'][0]['text']);self.assertEqual(data['series_context']['characters'][0]['id'],'hero');self.assertIn('LEFT',data['series_context']['canon']);self.assertEqual(response.json['result']['story_source'],r['story_source'])
  self.req('/api/story/episode',{**self.ep,'synopsis':'Changed after handoff'})
  self.assertEqual(self.req('/api/director',body).status_code,400)
 def test_import_export_and_restart_keep_private_series_separate(self):
  package=self.req('/api/story/export',{'project_id':self.p['id']}).json
  imported=self.req('/api/story/import',package);self.assertEqual(imported.status_code,200,imported.json);self.assertNotEqual(imported.json['id'],self.p['id']);self.assertEqual(imported.json['characters'],self.p['characters'])
  app=create_app(self.config,self.store);client=app.test_client();csrf=self.req('/auth/csrf',client=client).json['csrf'];token=self.req('/auth/login',{'email':'bob@example.com','password':'test-password-only'},csrf,client).json['csrf']
  state=self.req('/api/story/state',client=client).json;self.assertEqual(len(state['projects']),2);self.assertEqual(len(state['episodes']),2)
  package['episodes'][0]['scenes'][0]['character_ids']=['unknown'];before=len(self.store.rows);self.assertEqual(self.req('/api/story/import',package).status_code,400);self.assertEqual(len(self.store.rows),before)
 def test_invalid_handoff_roles_and_cross_project_episode_are_blocked(self):
  other=self.req('/api/story/project',{'title':'Other','characters':[],'assets':[]}).json
  self.assertEqual(self.req('/api/story/analyze',{'operation':'review','project_id':other['id'],'episode_id':self.ep['id']}).status_code,400)
  self.store.put('references',{'id':'video9','name':'Wrong type','type':'video','role':'Motion Reference'})
  self.assertEqual(self.req('/api/story/handoff',{'project_id':self.p['id'],'episode_id':self.ep['id'],'scene_id':'scene','shot_id':'shot','profile_id':'hf-seedance-i2v','bindings':[{'reference_id':'video9','role':'First Frame'}]}).status_code,400)
 def test_asset_deletion_removes_only_selected_duplicate_and_is_recoverable(self):
  reference={'id':'image7','name':'Portrait','type':'image','file':'test.png'};self.store.put('references',reference);self.store.files['test.png']=b'original'
  asset={'id':'original','kind':'face','name':'Portrait','character_id':'hero','reference_id':'image7'}
  project=self.req('/api/story/project',{**self.p,'assets':[asset,{**asset,'id':'duplicate'}]}).json
  body={'project_id':project['id'],'version':project['version'],'asset_id':'duplicate'}
  self.assertEqual(self.req('/api/story/delete-asset',body,csrf='wrong').status_code,403)
  result=self.req('/api/story/delete-asset',body);self.assertEqual(result.status_code,200,result.json)
  self.assertEqual([a['id'] for a in result.json['assets']],['original'])
  self.assertEqual(result.json['characters'],project['characters']);self.assertEqual(result.json['canon'],project['canon'])
  self.assertEqual(self.store.get('references','image7'),reference);self.assertEqual(self.store.files['test.png'],b'original')
  self.assertEqual(self.store.get('story_episodes',self.ep['id']),self.ep)
  self.assertEqual(self.req('/api/story/delete-asset',body).status_code,409)
  revisions=self.req('/api/story/revisions',{'kind':'projects','id':project['id']}).json
  revision=next(r for r in revisions if r['version']==project['version'])
  restored=self.req('/api/story/restore',{'revision_id':revision['id'],'version':result.json['version']})
  self.assertEqual(restored.status_code,200,restored.json);self.assertEqual(len(restored.json['assets']),2)
 def test_asset_deletion_blocks_used_cards_without_partial_changes(self):
  asset={'id':'outfit','name':'Costume','kind':'outfit','character_id':'hero'}
  project=self.req('/api/story/project',{**self.p,'assets':[asset]}).json
  episode=copy.deepcopy(self.ep);episode['scenes'][0]['shots'][0]['asset_needs'][0]['asset_id']='outfit'
  self.assertEqual(self.req('/api/story/episode',episode).status_code,200)
  before=copy.deepcopy(self.store.rows)
  result=self.req('/api/story/delete-asset',{'project_id':project['id'],'version':project['version'],'asset_id':'outfit'})
  self.assertEqual(result.status_code,400);self.assertIn('Reaction',result.json['error']);self.assertEqual(self.store.rows,before)
  self.assertEqual(self.req('/api/story/delete-asset',{'project_id':project['id'],'version':project['version'],'asset_id':'missing'}).status_code,400)

if __name__=='__main__':unittest.main()
