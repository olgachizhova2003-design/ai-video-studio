import copy,json,re,unittest
from pathlib import Path
from app import create_app,CloudError
from test_online import FakeSupabase

class KnowledgeAcceptance(unittest.TestCase):
    def setUp(self):
        self.store=FakeSupabase();self.config={'TESTING':True,'SECRET_KEY':'test-session-secret-32-characters-long','MASTER_KEY':'test-master-secret-32-characters-long','ALLOWED_EMAILS':'alice@example.com,bob@example.com'}
        self.app=create_app(self.config,self.store);self.client=self.app.test_client();self.engine=self.app.extensions['studio_engine'];self.captured=[]
        csrf=self.request('/auth/csrf').json['csrf'];r=self.request('/auth/login',{'email':'alice@example.com','password':'test-password-only'},csrf);self.csrf=r.json['csrf']
        self.state=self.request('/api/state').json
        settings=copy.deepcopy(self.state['settings']);settings['prompt'].update(url='https://mock.example/v1',model='mock-no-paid-requests')
        self.request('/api/settings',{'settings':settings,'keys':{'prompt':'test-prompt-key'}},self.csrf)
        self.next_prompt='A calm continuous scene.'
        def prompt_stub(url,key,payload=None,*args,**kwargs):
            self.assertTrue(url.endswith('/chat/completions'));self.captured.append(payload)
            if 'prompt teacher' in payload['messages'][0]['content']:
                content={'anatomy':[{'key':'subject','text':'One subject','explanation':'Главный объект назван явно.'}],'after':'An improved restrained scene.','changes':[{'what':'Уточнено действие','why':'Оно наблюдаемо в кадре.'}],'warnings':[]}
            else:content={'prompt':self.next_prompt,'parameters':{},'explanation':'Ответ подменён для проверки интеграции контекста.','warnings':[],'document_ids':[]}
            return {'choices':[{'message':{'content':json.dumps(content)}}]}
        self.engine.api_request=prompt_stub
    def request(self,path,body=None,csrf=None):
        return self.client.open(path,base_url='https://studio.example',method='POST' if body is not None else 'GET',json=body,headers={'Origin':'https://studio.example','X-Studio-Request':'local','X-CSRF-Token':csrf or getattr(self,'csrf','')})
    def reference(self,id_,role):
        typ='video' if id_.startswith('video') else 'audio' if id_.startswith('audio') else 'image'
        item={'id':id_,'name':id_,'role':role,'type':typ,'description':'Контрольный референс','remote_url':'https://example.com/'+id_+('.mp4' if typ=='video' else '.png'),'duration':8 if typ!='image' else 0,'width':1024,'height':1024,'size':1024,'fps':24,'metadata_checked':True,'mime':'image/png','created_at':'2026-11-21T00:00:00Z'}
        self.store.put('references',item);return id_
    def direct(self,profile,brief,refs=(),**extra):
        p=next(p for p in self.state['profiles'] if p['id']==profile)
        body={'profile_id':profile,'brief':brief,'reference_ids':list(refs),'parameters':{k:v['default'] for k,v in p['schema'].items()},**extra}
        response=self.request('/api/director',body);self.assertEqual(response.status_code,200,response.json)
        data=json.loads(self.captured[-1]['messages'][1]['content'][0]['text'])
        return response.json,data
    def assert_mode_context(self,data,mode):
        docs=data['knowledge_excerpts'];ids=[d['document_id'] for d in docs]
        self.assertTrue(any(id_=='ke-guide-'+mode for id_ in ids),ids)
        selected=[d for d in docs if d.get('kind')=='example'];self.assertGreaterEqual(len(selected),2);self.assertLessEqual(len(selected),4)
        self.assertTrue(all(d['document_id'].startswith('ke-example-'+mode+'-') for d in selected))
        self.assertFalse(any(id_.startswith('ke-guide-') and id_!='ke-guide-'+mode for id_ in ids))
        self.assertLessEqual(len(json.dumps(docs,ensure_ascii=False)),18000)
        self.assertTrue(all(d.get('source') and d.get('section_id') for d in docs))
    def test_a_image_to_video_receives_its_guide_and_examples(self):
        ref=self.reference('image9','First Frame');_,data=self.direct('hf-seedance-i2v','Оживить портрет: моргание, небольшая улыбка и мягкий наезд',[ref])
        self.assert_mode_context(data,'i2v');self.assertEqual(data['references'][0]['id'],'image9')
    def test_b_three_images_and_video_keep_roles_and_separate_internal_ids(self):
        ids=[self.reference('image7','First Frame'),self.reference('image21','Environment'),self.reference('image3','Outfit Reference'),self.reference('video4','Motion Reference')]
        self.next_prompt='image7 defines the protagonist. image21 defines the room. video4 defines motion.'
        record,data=self.direct('hf-seedance-r2v','Героиня идёт по комнате с движением из видео',ids,reference_roles={'image7':'Main Character'})
        self.assert_mode_context(data,'r2v');self.assertEqual(data['references'][0]['role'],'Main Character');self.assertEqual(self.store.get('references','image7')['role'],'First Frame')
        p=next(p for p in self.state['profiles'] if p['id']=='hf-seedance-r2v')
        prepared=self.request('/api/prepare',{'profile_id':p['id'],'prompt':record['result']['prompt'],'parameters':record['result']['parameters'],'reference_ids':ids,'reference_roles':{'image7':'Main Character'}})
        self.assertEqual(prepared.status_code,200,prepared.json);self.assertEqual(len(prepared.json['payload']['image_urls']),3)
        self.assertIn('the first supplied image',prepared.json['payload']['prompt']);self.assertNotIn('@Image7',prepared.json['payload']['prompt'])
    def test_c_motion_transfer_preserves_source_contract_and_can_use_empty_prompt(self):
        ids=[self.reference('video2','Motion Reference'),self.reference('image8','Main Character')];self.next_prompt=''
        record,data=self.direct('hf-genjutsu-motion','Хочу, чтобы девушка танцевала как в референс-видео',ids)
        self.assert_mode_context(data,'motion');self.assertIn('inherit source choreography',self.captured[-1]['messages'][0]['content'])
        self.assertEqual(record['result']['prompt'],'')
        p=next(p for p in self.state['profiles'] if p['id']=='hf-genjutsu-motion')
        prepared=self.request('/api/prepare',{'profile_id':p['id'],'prompt':'','parameters':{'resolution':'720p'},'reference_ids':ids})
        self.assertEqual(prepared.status_code,200,prepared.json);self.assertEqual(prepared.json['payload']['prompt'],'')
        self.assertFalse(self.store.all('jobs'))
    def test_d_object_swap_selects_local_replacement_examples(self):
        ids=[self.reference('video2','Motion Reference'),self.reference('image8','Replacement Object')]
        _,data=self.direct('hf-genjutsu-swap','Заменить только косметический флакон в правой руке. Остальное без изменений.',ids)
        self.assert_mode_context(data,'swap');self.assertTrue(any(d['document_id']=='ke-example-swap-01' for d in data['knowledge_excerpts']))
        self.assertFalse(any('ke-provider-nano' in d['document_id'] for d in data['knowledge_excerpts']))
    def test_e_switching_models_drops_prior_mode_context_and_conversation(self):
        refs=[self.reference('image8','Main Character'),self.reference('video2','Motion Reference')]
        previous={'profile_id':'hf-seedance-r2v','prompt':'old source scene'}
        _,data=self.direct('hf-genjutsu-motion','Танец из источника',refs,previous_result=previous,messages=[{'role':'user','content':'Old R2V scene'}])
        self.assert_mode_context(data,'motion');self.assertIsNone(data['previous_result']);self.assertEqual(data['conversation'],[])
    def test_f_user_document_and_example_are_found_and_survive_restart(self):
        doc=self.request('/api/document',{'title':'Правило AURORASET','category':'User Instructions','content':'# AURORASET\nДля AURORASET сохранять кремовый браслет героя.','profiles':['hf-genjutsu-motion'],'enabled':True}).json
        example=self.request('/api/example',{'title':'AURORASET gesture','category':'Character Acting','mode':'motion','goal':'AURORASET continuity','prompt':'Preserve the AURORASET bracelet and source movement.','references':[],'tags':['AURORASET']}).json
        context=self.request('/api/context',{'profile_id':'hf-genjutsu-motion','query':'AURORASET жест браслет'}).json
        self.assertIn(doc['id'],[d['document_id'] for d in context]);self.assertIn(example['id'],[d['document_id'] for d in context])
        new_app=create_app(self.config,self.store);new_client=new_app.test_client();csrf=new_client.get('/auth/csrf',base_url='https://studio.example').json['csrf']
        login=new_client.post('/auth/login',base_url='https://studio.example',json={'email':'alice@example.com','password':'test-password-only'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(login.status_code,200);state=new_client.get('/api/state',base_url='https://studio.example').json
        self.assertTrue(any(e['id']==example['id'] for e in state['examples']));self.assertTrue(any(d['id']==doc['id'] for d in state['documents']))
    def test_backup_precedes_migration_and_original_documents_survive(self):
        snapshot=self.request('/api/knowledge-backup').json
        self.assertEqual(len(snapshot['documents']),5);self.assertEqual(len(snapshot['profiles']),8)
        current={d['id']:d for d in self.state['documents']}
        for d in snapshot['documents']:self.assertEqual(current[d['id']]['content'],d['content'])
        self.assertFalse(any(key in snapshot for key in ['settings','secrets','tickets']))
        self.assertEqual(len(self.state['examples']),40)
        self.assertTrue(all(not e['generation_verified'] for e in self.state['examples']))
        for mode in ['t2v','i2v','r2v','motion','swap']:
            guide=current['ke-guide-'+mode];self.assertGreaterEqual(len(re.findall(r'\b[\w-]+\b',guide['content'])),1500)
            self.assertEqual(sum(e['mode']==mode for e in self.state['examples']),8)
    def test_failed_backup_blocks_all_knowledge_migration_writes(self):
        class NoBackupStore(FakeSupabase):
            def put(self,kind,item):
                if kind=='knowledge_backups':raise CloudError('Backup storage unavailable',503)
                return super().put(kind,item)
        store=NoBackupStore();app=create_app(self.config,store);client=app.test_client();csrf=client.get('/auth/csrf',base_url='https://studio.example').json['csrf']
        client.post('/auth/login',base_url='https://studio.example',json={'email':'alice@example.com','password':'test-password-only'},headers={'X-CSRF-Token':csrf})
        r=client.get('/api/state',base_url='https://studio.example');self.assertEqual(r.status_code,503)
        self.assertEqual(len(store.all('documents')),5);self.assertEqual(len(store.all('examples')),0)
    def test_anatomy_and_before_after_use_prompt_ai_and_always_show_ten_components(self):
        r=self.request('/api/anatomy',{'profile_id':'hf-seedance-t2v','prompt':'Девушка идёт по комнате, красиво и реалистично','operation':'improve','reference_ids':[]})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(len(r.json['anatomy']),10);self.assertNotEqual(r.json['before'],r.json['after']);self.assertTrue(r.json['context'])
        e=self.request('/api/anatomy',{'profile_id':'hf-seedance-t2v','prompt':'Keep this exact prompt.','operation':'explain','reference_ids':[]})
        self.assertEqual(e.json['after'],'Keep this exact prompt.')
    def test_reference_positions_are_provider_specific_and_nonexistent_ids_are_rejected(self):
        ids=[self.reference('image9','Main Character'),self.reference('video3','Motion Reference')]
        p=next(p for p in self.state['profiles'] if p['id']=='seedance-r2v')
        body={'profile_id':p['id'],'prompt':'image9 defines identity. video3 defines motion.','parameters':{k:v['default'] for k,v in p['schema'].items()},'reference_ids':ids}
        r=self.request('/api/prepare',body);self.assertEqual(r.status_code,200,r.json);self.assertIn('@Image1',r.json['payload']['prompt']);self.assertIn('@Video1',r.json['payload']['prompt'])
        r=self.request('/api/prepare',{**body,'prompt':'image1 defines identity.'});self.assertEqual(r.status_code,400)
    def test_example_validation_allows_empty_genjutsu_but_rejects_invalid_slots(self):
        body={'title':'Silent transfer','goal':'Use source motion','mode':'motion','prompt':'','references':[]}
        self.assertEqual(self.request('/api/example',body).status_code,200)
        self.assertEqual(self.request('/api/example',{**body,'mode':'t2v'}).status_code,400)
        self.assertEqual(self.request('/api/example',{**body,'references':[{'slot':'image1','type':'video','role':'Motion Reference'}]}).status_code,400)

if __name__=='__main__':unittest.main(verbosity=2)
