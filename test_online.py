import base64,copy,importlib.util,json,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from app import create_app,CloudError

class FakeSupabase:
    def __init__(self):self.rows={};self.files={};self.auth_calls=[]
    def get(self,kind,id_):
        if (kind,id_) not in self.rows:raise ValueError('Запись не найдена')
        return copy.deepcopy(self.rows[kind,id_])
    def all(self,kind):return [copy.deepcopy(v) for (k,i),v in self.rows.items() if k==kind]
    def put(self,kind,item):self.rows[kind,item['id']]=copy.deepcopy(item);return copy.deepcopy(item)
    def delete(self,kind,id_):self.rows.pop((kind,id_),None)
    def upload(self,name,blob,mime):self.files[name]=bytes(blob)
    def remove_files(self,names):
        for name in names:self.files.pop(name,None)
    def download(self,name):return self.files[name]
    def signed_url(self,name,expires=86400):return 'https://project.supabase.co/storage/v1/object/sign/studio-media/'+name+'?token=temporary-test-link'
    def signin(self,email,password):
        self.auth_calls.append(email)
        if password!='test-password-only':raise CloudError('Supabase HTTP 400: Invalid login credentials',400)
        name=email.split('@')[0];return {'access_token':name+'-access','refresh_token':name+'-refresh','expires_in':3600}
    def refresh(self,token):return {'access_token':token.replace('-refresh','-access'),'refresh_token':token,'expires_in':3600}
    def user(self,token):
        name=token.split('-')[0]
        if name not in ['alice','bob']:raise CloudError('Invalid token',401)
        return {'id':name+'-id','email':name+'@example.com','email_confirmed_at':'2026-11-21T00:00:00Z','user_metadata':{'name':name}}

class OnlineAcceptance(unittest.TestCase):
    def setUp(self):
        self.store=FakeSupabase();self.config={'TESTING':True,'SECRET_KEY':'test-session-secret-32-characters-long','MASTER_KEY':'test-master-secret-32-characters-long','ALLOWED_EMAILS':'alice@example.com,bob@example.com'}
        self.app=create_app(self.config,self.store);self.alice=self.app.test_client();self.bob=self.app.test_client();self.engine=self.app.extensions['studio_engine']
    def req(self,client,path,body=None,token=None,origin='https://studio.example'):
        return client.open(path,base_url='https://studio.example',method='POST' if body is not None else 'GET',json=body,headers={'Origin':origin,'X-Studio-Request':'local','X-CSRF-Token':token or ''})
    def login(self,client,email='alice@example.com'):
        token=self.req(client,'/auth/csrf').json['csrf'];r=self.req(client,'/auth/login',{'email':email,'password':'test-password-only'},token);self.assertEqual(r.status_code,200,r.json);return r.json['csrf']
    def state(self,client):
        r=self.req(client,'/api/state');self.assertEqual(r.status_code,200,r.json);return r.json
    def test_01_anonymous_users_cannot_access_data_or_media(self):
        self.assertEqual(self.req(self.alice,'/api/state').status_code,401)
        self.assertEqual(self.req(self.alice,'/').status_code,302)
        self.assertEqual(self.req(self.alice,'/media/'+'a'*32+'.png').status_code,302)
        self.assertEqual(self.req(self.alice,'/healthz').status_code,200)
        with self.req(self.alice,'/static/app.js') as response:self.assertEqual(response.status_code,200)
    def test_02_only_two_allowlisted_accounts_can_sign_in(self):
        csrf=self.req(self.alice,'/auth/csrf').json['csrf'];r=self.req(self.alice,'/auth/login',{'email':'outsider@example.com','password':'test-password-only'},csrf)
        self.assertEqual(r.status_code,403);self.assertEqual(self.store.auth_calls,[])
        self.login(self.alice);s=self.state(self.alice);self.assertEqual(s['user']['email'],'alice@example.com');self.assertEqual(len(s['profiles']),8)
    def test_03_password_failures_and_csrf_are_enforced(self):
        self.assertEqual(self.req(self.alice,'/auth/login',{'email':'alice@example.com','password':'bad'}).status_code,403)
        csrf=self.req(self.alice,'/auth/csrf').json['csrf'];r=self.req(self.alice,'/auth/login',{'email':'alice@example.com','password':'bad'},csrf);self.assertEqual(r.status_code,400)
        token=self.login(self.alice);self.state(self.alice)
        self.assertEqual(self.req(self.alice,'/api/history',{'title':'x'}).status_code,403)
        self.assertEqual(self.req(self.alice,'/api/history',{'title':'x'},token,origin='https://evil.example').status_code,403)
    def test_04_api_keys_are_private_encrypted_and_not_returned(self):
        a=self.login(self.alice);b=self.login(self.bob,'bob@example.com');sa=self.state(self.alice);self.state(self.bob)
        r=self.req(self.alice,'/api/settings',{'settings':sa['settings'],'keys':{'prompt':'test-private-alice-key'}},a);self.assertEqual(r.status_code,200,r.json)
        self.assertTrue(self.state(self.alice)['settings']['prompt']['has_key']);self.assertFalse(self.state(self.bob)['settings']['prompt']['has_key'])
        self.assertNotIn('test-private-alice-key',json.dumps(list(self.store.rows.values()),default=str));self.assertNotIn('test-private-alice-key',json.dumps(self.state(self.alice)))
    def test_05_library_and_history_are_shared_but_drafts_are_personal(self):
        a=self.login(self.alice);b=self.login(self.bob,'bob@example.com');sa=self.state(self.alice);self.state(self.bob)
        d=self.req(self.alice,'/api/document',{'title':'Общая заметка','content':'# Свет\nМягкий свет','category':'User Instructions','profiles':['hf-seedance-i2v'],'enabled':True},a);self.assertEqual(d.status_code,200,d.json)
        self.assertTrue(any(x['title']=='Общая заметка' for x in self.state(self.bob)['documents']))
        w=sa['workspace'];w['brief']='Личный черновик Алисы';self.assertEqual(self.req(self.alice,'/api/workspace',w,a).status_code,200)
        self.assertEqual(self.state(self.bob)['workspace']['brief'],'')
        self.req(self.alice,'/api/history',{'title':'Общий результат','result':{'prompt':'A flower','parameters':{}},'profile_id':'hf-seedance-i2v','reference_ids':[]},a)
        self.assertTrue(any(x['title']=='Общий результат' for x in self.state(self.bob)['history']))
    def test_06_media_are_stored_outside_the_web_server(self):
        token=self.login(self.alice);self.state(self.alice)
        data='data:image/png;base64,'+base64.b64encode(b'fake-test-png').decode()
        r=self.req(self.alice,'/api/reference',{'name':'Shared frame','type':'image','role':'First Frame','data':data,'width':1024,'height':1024},token)
        self.assertEqual(r.status_code,200,r.json);name=r.json['file'];self.assertIn(name,self.store.files)
        media=self.req(self.alice,'/media/'+name);self.assertEqual(media.status_code,302);self.assertTrue(media.location.startswith('https://project.supabase.co/'))
        engine=self.app.extensions['studio_engine'];p=engine.BUILTINS['hf-seedance-i2v']
        self.assertIn('/storage/v1/object/sign/',engine.reference_value(r.json,p))
    def test_07_restart_keeps_shared_data_and_encrypted_credentials(self):
        token=self.login(self.alice);state=self.state(self.alice);self.req(self.alice,'/api/settings',{'settings':state['settings'],'keys':{'prompt':'test-persistent-key'}},token)
        new_app=create_app(self.config,self.store);new_client=new_app.test_client();self.login(new_client);self.assertTrue(self.state(new_client)['settings']['prompt']['has_key'])
    def test_08_other_member_cannot_poll_someone_elses_paid_job(self):
        token=self.login(self.bob,'bob@example.com');self.state(self.bob)
        self.store.put('jobs',{'id':'alice-job','owner_id':'alice-id','remote_id':'test','provider':'higgsfield'})
        r=self.req(self.bob,'/api/poll',{'id':'alice-job'},token);self.assertEqual(r.status_code,403)
    def test_09_online_app_does_not_expose_an_open_relay(self):
        token=self.login(self.alice);self.state(self.alice)
        self.assertEqual(self.req(self.alice,'/api/relay',{'url':'https://api.higgsfield.ai'},token).status_code,404)
    def test_10_logout_invalidates_session_and_cookie_settings_are_secure(self):
        token=self.login(self.alice);self.state(self.alice);r=self.req(self.alice,'/auth/logout',{},token);self.assertEqual(r.status_code,200)
        self.assertEqual(self.req(self.alice,'/api/state').status_code,401)
        self.assertTrue(self.app.config['SESSION_COOKIE_SECURE']);self.assertTrue(self.app.config['SESSION_COOKIE_HTTPONLY']);self.assertEqual(self.app.config['SESSION_COOKIE_SAMESITE'],'Lax')
    def test_11_shared_document_deletion_does_not_need_local_sqlite(self):
        token=self.login(self.alice);self.state(self.alice)
        r=self.req(self.alice,'/api/delete',{'kind':'documents','id':'cinematic-notes'},token);self.assertEqual(r.status_code,200,r.json)
        self.assertFalse(any(d['id']=='cinematic-notes' for d in self.state(self.alice)['documents']))
    def test_12_concurrent_document_edits_require_the_current_version(self):
        a=self.login(self.alice);b=self.login(self.bob,'bob@example.com');d=next(d for d in self.state(self.alice)['documents'] if d['id']=='cinematic-notes');self.state(self.bob)
        changed={**d,'content':d['content']+'\nA new line'};self.assertEqual(self.req(self.alice,'/api/document',changed,a).status_code,200)
        stale=self.req(self.bob,'/api/document',{**d,'content':'Stale edit'},b);self.assertEqual(stale.status_code,409)

if __name__=='__main__':unittest.main(verbosity=2)
