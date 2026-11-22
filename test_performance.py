import base64,copy,io,json,unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from app import create_app,SupabaseStore
from test_online import FakeSupabase

class CountingStore(FakeSupabase):
    def __init__(self):super().__init__();self.calls=[]
    def get(self,kind,id_):self.calls.append(('get',kind));return super().get(kind,id_)
    def all(self,kind):self.calls.append(('all',kind));return super().all(kind)
    def snapshot(self,kinds):
        self.calls.append(('snapshot',tuple(kinds)))
        return {kind:[copy.deepcopy(v) for (k,i),v in self.rows.items() if k==kind] for kind in kinds}
    def user(self,token):self.calls.append(('user',token));return super().user(token)
    def download(self,name):self.calls.append(('download',name));return super().download(name)
    def signed_url(self,name,expires=86400):self.calls.append(('sign',name));return super().signed_url(name,expires)

class ReferencePerformance(unittest.TestCase):
    def setUp(self):
        self.store=CountingStore();self.app=create_app({'TESTING':True,'SECRET_KEY':'test-session-secret-32-characters-long','MASTER_KEY':'test-master-secret-32-characters-long','ALLOWED_EMAILS':'alice@example.com,bob@example.com'},self.store)
        self.client=self.app.test_client()
        csrf=self.request('/auth/csrf').json['csrf']
        self.csrf=self.request('/auth/login',{'email':'alice@example.com','password':'test-password-only'},csrf).json['csrf']
        self.request('/api/state')
    def request(self,path,body=None,csrf=None,client=None,**headers):
        return (client or self.client).open(path,base_url='https://studio.example',method='POST' if body is not None else 'GET',json=body,headers={'Origin':'https://studio.example','X-Studio-Request':'local','X-CSRF-Token':csrf or getattr(self,'csrf',''),**headers})
    def add_image(self):
        image=Image.new('RGB',(900,1600),'blue');draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,899,100),fill='red');draw.rectangle((0,1500,899,1599),fill='green')
        data=io.BytesIO();image.save(data,format='PNG');self.original=data.getvalue()
        response=self.request('/api/reference',{'name':'Full portrait','type':'image','role':'First Frame','data':'data:image/png;base64,'+base64.b64encode(self.original).decode(),'width':900,'height':1600})
        self.assertEqual(response.status_code,200,response.json);return response.json
    def test_state_uses_one_scoped_snapshot_without_repeated_secret_reads(self):
        self.store.calls=[];response=self.request('/api/state')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(self.store.calls),1,self.store.calls)
        kinds=self.store.calls[0][1]
        self.assertIn('workspace:alice-id',kinds);self.assertIn('secrets:alice-id',kinds);self.assertNotIn('secrets:bob-id',kinds)
        self.assertNotIn('secrets',response.json)
    def test_preview_preserves_edges_and_original_and_is_downloaded_only_once(self):
        ref=self.add_image();path='/media/'+ref['file']+'?preview=1';self.store.calls=[]
        first=self.request(path)
        self.assertEqual(first.status_code,200);self.assertEqual(first.mimetype,'image/webp')
        with Image.open(io.BytesIO(first.data)) as preview:
            self.assertEqual(preview.size,(360,640));self.assertGreater(preview.getpixel((180,5))[0],200);self.assertGreater(preview.getpixel((180,635))[1],90)
        self.assertLess(len(first.data),len(self.original));self.assertEqual(self.store.files[ref['file']],self.original)
        second=self.request(path,**{'If-None-Match':first.headers['ETag']})
        self.assertEqual(second.status_code,304);self.assertEqual(second.data,b'')
        self.assertEqual(sum(c[0]=='download' for c in self.store.calls),1)
        self.assertEqual(sum(c[0]=='all' for c in self.store.calls),1)
        self.assertEqual(first.headers['Cache-Control'],'private, max-age=300')
        first.close();second.close()
        anonymous=self.request(path,client=self.app.test_client());self.assertEqual(anonymous.status_code,302);self.assertTrue(anonymous.location.endswith('/login'))
        deleted=self.request('/api/delete',{'kind':'references','id':ref['id']});self.assertEqual(deleted.status_code,200,deleted.json)
        self.assertEqual(self.request(path).status_code,404)
    def test_full_original_links_are_reused_without_resigning_on_each_render(self):
        ref=self.add_image();self.store.calls=[]
        for _ in range(3):self.assertEqual(self.request('/media/'+ref['file']).status_code,302)
        self.assertEqual(sum(c[0]=='sign' for c in self.store.calls),1)
    def test_html_versions_assets_and_keeps_personal_pages_uncached(self):
        response=self.request('/');self.assertIn(b'/static/app.js?v=',response.data);self.assertEqual(response.headers['Cache-Control'],'no-store')
        import re
        url=re.search(rb'(/static/app.js\?v=[a-f0-9]+)',response.data).group(1).decode()
        with self.request(url) as resource:
            self.assertIn('immutable',resource.headers['Cache-Control']);etag=resource.headers['ETag']
        with self.request(url,**{'If-None-Match':etag}) as cached:self.assertEqual(cached.status_code,304)
        self.assertEqual(self.request('/api/state').headers['Cache-Control'],'no-store')
    def test_identity_cache_is_short_lived_and_logout_still_blocks_media(self):
        self.store.calls=[];self.request('/auth/me');self.request('/auth/me')
        self.assertFalse(any(c[0]=='user' for c in self.store.calls))
        import time
        later=time.monotonic()+21
        with patch('app.time.monotonic',return_value=later):self.request('/auth/me')
        self.assertEqual(sum(c[0]=='user' for c in self.store.calls),1)
        self.request('/auth/logout',{})
        self.assertEqual(self.request('/api/state').status_code,401)

class SnapshotQuery(unittest.TestCase):
    def test_supabase_fetches_requested_shared_and_personal_kinds_in_one_query(self):
        store=SupabaseStore('https://project.supabase.co','sb_publishable_test','sb_secret_test');sent=[]
        def http(path,*a,**kw):sent.append(path);return [{'kind':'profiles','body':{'id':'p'}},{'kind':'workspace:alice-id','body':{'id':'main'}}]
        store.http=http
        result=store.snapshot(['profiles','workspace:alice-id','secrets:alice-id'])
        self.assertEqual(len(sent),1);self.assertEqual(result['profiles'],[{'id':'p'}]);self.assertEqual(result['secrets:alice-id'],[])

if __name__=='__main__':unittest.main()
