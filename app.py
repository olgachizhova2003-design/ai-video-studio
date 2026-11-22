"""Private two-person studio: Render Free + Supabase Auth/Postgres/Storage."""
from __future__ import annotations
import base64,copy,hashlib,importlib.util,io,ipaddress,json,mimetypes,os,re,secrets,socket,tempfile,threading,time,uuid
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote,urlencode,urlparse
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from cryptography.fernet import Fernet,InvalidToken
from flask import Flask,Response,abort,g,jsonify,redirect,request,send_from_directory,send_file,session
from media_cache import MediaCache
from story_engine import StoryEngine,StoryConflict
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT=Path(__file__).resolve().parent
PRIVATE_KINDS={'settings','workspace','secrets','tickets'}
MEDIA_NAME=re.compile(r'^[a-f0-9]{32}\.[a-z0-9]+$')

class CloudError(ValueError):
    def __init__(self,message,status=502):super().__init__(message);self.status=status

class SupabaseStore:
    def __init__(self,url,anon_key,service_key,bucket='studio-media'):
        url=url.strip();anon_key=anon_key.strip();service_key=service_key.strip()
        if not anon_key or not service_key:raise ValueError('Заполните оба ключа Supabase в настройках сервера')
        if any(re.search(r'[\s\x00-\x1f\x7f]',key) for key in [anon_key,service_key]):raise ValueError('Ключ Supabase содержит пробел или управляющий символ внутри значения. Скопируйте ключ заново.')
        parsed=urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co') or parsed.username or parsed.password:raise ValueError('SUPABASE_URL должен быть HTTPS адресом проекта *.supabase.co')
        self.url=url.rstrip('/');self.anon_key=anon_key;self.service_key=service_key;self.bucket=bucket
    def auth_headers(self,auth=None):
        header={'apikey':self.anon_key if auth is not None else self.service_key}
        # New sb_* API keys are not JWTs. The gateway authorizes them via apikey.
        if auth is None and not self.service_key.startswith('sb_secret_'):header['Authorization']='Bearer '+self.service_key
        elif auth:header['Authorization']='Bearer '+auth
        return header
    def http(self,path,method='GET',payload=None,auth=None,raw=None,mime=None,headers=None):
        header=self.auth_headers(auth)
        if raw is not None:data=raw;header['Content-Type']=mime or 'application/octet-stream'
        elif payload is not None:data=json.dumps(payload).encode();header['Content-Type']='application/json'
        else:data=None
        header.update(headers or {})
        try:
            with urlopen(Request(self.url+path,method=method,data=data,headers=header),timeout=45) as response:
                blob=response.read(50*1024*1024)
                return json.loads(blob) if blob else None
        except HTTPError as error:
            blob=error.read(4000).decode('utf-8',errors='replace')
            try:detail=json.loads(blob);detail=detail.get('msg') or detail.get('message') or detail.get('error_description') or detail.get('error') or 'Ошибка Supabase'
            except json.JSONDecodeError:detail='Ошибка доступа к Supabase'
            for secret in [self.anon_key,self.service_key,auth]:
                if secret:detail=str(detail).replace(secret,'[ключ скрыт]')
            raise CloudError('Supabase HTTP '+str(error.code)+': '+str(detail),error.code)
        except (URLError,TimeoutError):raise CloudError('Supabase недоступен. Проверьте, не приостановлен ли бесплатный проект, и настройки подключения.')
    def get(self,kind,item_id):
        query=urlencode({'kind':'eq.'+kind,'id':'eq.'+item_id,'select':'body','limit':'1'})
        rows=self.http('/rest/v1/studio_objects?'+query)
        if not rows:raise ValueError('Запись не найдена')
        return rows[0]['body']
    def all(self,kind):
        result=[];offset=0
        while True:
            query=urlencode({'kind':'eq.'+kind,'select':'body','order':'created_at.asc,id.asc','limit':'500','offset':str(offset)})
            rows=self.http('/rest/v1/studio_objects?'+query);result.extend(row['body'] for row in rows)
            if len(rows)<500:return result
            offset+=500
    def snapshot(self,kinds):
        result={kind:[] for kind in kinds};offset=0
        while True:
            query=urlencode({'kind':'in.('+','.join(json.dumps(k) for k in kinds)+')','select':'kind,body','order':'created_at.asc,id.asc','limit':'500','offset':str(offset)})
            rows=self.http('/rest/v1/studio_objects?'+query)
            for row in rows:result[row['kind']].append(row['body'])
            if len(rows)<500:return result
            offset+=500
    def put(self,kind,item):
        self.http('/rest/v1/studio_objects?on_conflict=kind,id','POST',{'kind':kind,'id':item['id'],'body':item},headers={'Prefer':'resolution=merge-duplicates,return=minimal'})
        return copy.deepcopy(item)
    def delete(self,kind,item_id):self.http('/rest/v1/studio_objects?'+urlencode({'kind':'eq.'+kind,'id':'eq.'+item_id}),'DELETE')
    def upload(self,name,blob,mime):
        if not MEDIA_NAME.fullmatch(name):raise ValueError('Некорректное имя медиа')
        if len(blob)>25*1024*1024:raise ValueError('Один медиафайл должен быть не больше 25 MB')
        self.http('/storage/v1/object/'+quote(self.bucket,safe='')+'/'+name,'POST',raw=blob,mime=mime,headers={'x-upsert':'true'})
    def download(self,name):
        if not MEDIA_NAME.fullmatch(name):raise ValueError('Некорректное имя медиа')
        header=self.auth_headers()
        try:
            with urlopen(Request(self.url+'/storage/v1/object/authenticated/'+quote(self.bucket,safe='')+'/'+name,headers=header),timeout=45) as response:return response.read(25*1024*1024+1)
        except (HTTPError,URLError):raise CloudError('Не удалось получить сохранённый референс из Supabase Storage')
    def signed_url(self,name,expires=86400):
        if not MEDIA_NAME.fullmatch(name):raise ValueError('Некорректное имя медиа')
        result=self.http('/storage/v1/object/sign/'+quote(self.bucket,safe='')+'/'+name,'POST',{'expiresIn':expires})
        signed=result.get('signedURL') or result.get('signedUrl')
        if not signed:raise CloudError('Supabase не вернул ссылку на медиа')
        if signed.startswith('/object/'):signed='/storage/v1'+signed
        url=self.url+signed if signed.startswith('/') else signed
        if urlparse(url).hostname!=urlparse(self.url).hostname:raise CloudError('Supabase вернул посторонний адрес медиа')
        return url
    def remove_files(self,names):
        if any(not MEDIA_NAME.fullmatch(name) for name in names):raise ValueError('Некорректное имя медиа')
        if names:self.http('/storage/v1/object/'+quote(self.bucket,safe=''),'DELETE',{'prefixes':names})
    def signin(self,email,password):return self.http('/auth/v1/token?grant_type=password','POST',{'email':email,'password':password},auth='')
    def refresh(self,token):return self.http('/auth/v1/token?grant_type=refresh_token','POST',{'refresh_token':token},auth='')
    def user(self,token):return self.http('/auth/v1/user',auth=token)

def create_app(config=None,store=None):
    app=Flask(__name__,static_folder=None)
    app.config.update(SECRET_KEY=os.environ.get('APP_SECRET',''),MASTER_KEY=os.environ.get('STUDIO_MASTER_KEY',''),SUPABASE_URL=os.environ.get('SUPABASE_URL',''),SUPABASE_ANON_KEY=os.environ.get('SUPABASE_ANON_KEY',''),SUPABASE_SERVICE_ROLE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY',''),ALLOWED_EMAILS=os.environ.get('STUDIO_ALLOWED_EMAILS',''),SESSION_COOKIE_NAME='studio_session',SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=timedelta(days=7),MAX_CONTENT_LENGTH=38*1024*1024)
    app.config.update(config or {})
    if len(app.config['SECRET_KEY'])<32 or len(app.config['MASTER_KEY'])<32:raise ValueError('Задайте постоянные APP_SECRET и STUDIO_MASTER_KEY длиной от 32 символов в настройках хостинга')
    allowed={email.strip().lower() for email in app.config['ALLOWED_EMAILS'].split(',') if email.strip()}
    if not 1<=len(allowed)<=2:raise ValueError('В STUDIO_ALLOWED_EMAILS укажите один или два разрешённых email через запятую')
    if store is None:
        if not app.config['SUPABASE_ANON_KEY'] or not app.config['SUPABASE_SERVICE_ROLE_KEY']:raise ValueError('Настройте ключи Supabase на сервере')
        store=SupabaseStore(app.config['SUPABASE_URL'],app.config['SUPABASE_ANON_KEY'],app.config['SUPABASE_SERVICE_ROLE_KEY'])
    app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=0)
    cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(app.config['MASTER_KEY'].encode()).digest()))
    spec=importlib.util.spec_from_file_location('cloud_engine_'+uuid.uuid4().hex,ROOT/'engine.py');engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
    engine.DATA=Path(tempfile.mkdtemp(prefix='video-studio-cache-'));(engine.DATA/'media').mkdir()
    who=ContextVar('studio-user',default=None);init_lock=threading.RLock();seeded=False
    media_cache=MediaCache(store,engine.DATA/'previews');ref_lock=threading.RLock();ref_cache={'until':0,'items':[]}
    identity_lock=threading.RLock();identity_cache={}
    asset_versions={file.name:hashlib.sha256(file.read_bytes()).hexdigest()[:12] for file in (ROOT/'static').iterdir() if file.is_file()}
    def scope(kind):
        user=who.get()
        if kind in PRIVATE_KINDS:
            if not user:raise ValueError('Для личных данных требуется вход')
            return kind+':'+user['id']
        return kind
    def get(kind,id_):
        key=scope(kind)
        if hasattr(g,'studio_snapshot') and key in g.studio_snapshot:
            item=next((x for x in g.studio_snapshot[key] if x['id']==id_),None)
            if item is None:raise ValueError('Запись не найдена')
            return copy.deepcopy(item)
        return store.get(key,id_)
    def all_items(kind):
        key=scope(kind)
        if hasattr(g,'studio_snapshot') and key in g.studio_snapshot:return copy.deepcopy(g.studio_snapshot[key])
        return store.all(key)
    def media_references():
        with ref_lock:
            if time.monotonic()>=ref_cache['until']:
                ref_cache.update(items=store.all('references'),until=time.monotonic()+10)
            return ref_cache['items']
    def invalidate_references():
        with ref_lock:ref_cache['until']=0

    def put(kind,item):
        item=copy.deepcopy(item);user=who.get()
        if kind in ['jobs','history'] and user:item.setdefault('owner_id',user['id']);item.setdefault('created_by',user.get('name') or user['email'])
        if kind=='references':
            try:previous=store.get('references',item['id'])
            except ValueError:previous={}
            old_files=([previous['file']] if previous.get('file') else [])+previous.get('frames',[])
            for filename in ([item['file']] if item.get('file') else [])+item.get('frames',[]):
                if not MEDIA_NAME.fullmatch(filename):raise ValueError('Некорректное имя референса')
                file=engine.DATA/'media'/filename
                if filename not in old_files and file.is_file():
                    store.upload(filename,file.read_bytes(),mimetypes.guess_type(file)[0] or 'application/octet-stream');file.unlink(missing_ok=True)
        result=store.put(scope(kind),item)
        if kind=='references':invalidate_references()
        return result
    def delete(kind,id_):
        if kind=='references':
            r=get(kind,id_);other_refs=[x for x in all_items('references') if x['id']!=id_]
            used={name for ref in other_refs for name in ([ref['file']] if ref.get('file') else [])+ref.get('frames',[])}
            names=[name for name in ([r['file']] if r.get('file') else [])+r.get('frames',[]) if name not in used]
            store.remove_files(names);media_cache.remove(names);invalidate_references()
        return store.delete(scope(kind),id_)
    engine.get=get;engine.all_items=all_items;engine.put=put;engine.delete=delete
    engine.protect=lambda value,decrypt=False:cipher.decrypt(value.encode()).decode() if decrypt else cipher.encrypt(value.encode()).decode()
    def save_document(d):
        d=copy.deepcopy(d);engine.require(bool(d.get('title','').strip()),'Укажите название документа');engine.require(d.get('category') in engine.CATEGORIES,'Неизвестная категория');engine.require(isinstance(d.get('content'),str) and len(d['content'])<=2_000_000,'Некорректный документ')
        d['id']=d.get('id') or engine.uid();d.setdefault('created_at',engine.now());d['updated_at']=engine.now();d.setdefault('version',1);d.setdefault('enabled',True);d.setdefault('profiles',[])
        for profile_id in d['profiles']:get('profiles',profile_id)
        return put('documents',d)
    def context(profile_id,query,limit=6):
        words=list(dict.fromkeys(re.findall(r'[\w]{3,}',query.lower())))[:24];sections=[]
        for d in all_items('documents'):
            if not d.get('enabled') or profile_id not in d.get('profiles',[]):continue
            for part in re.split(r'(?m)(?=^#{1,6} )',d['content']):
                heading=part.split('\n',1)[0].lstrip('# ') if part.startswith('#') else d['title'];content=part.split('\n',1)[1] if part.startswith('#') and '\n' in part else part
                for offset in range(0,len(content),2800):
                    text=content[offset:offset+2800].strip()
                    if text:sections.append(dict(document_id=d['id'],title=d['title'],heading=heading,content=text,version=d['version'],score=sum(w in (heading+' '+text).lower() for w in words)))
        sections.sort(key=lambda section:section['score'],reverse=True);first=[];seen=set()
        for section in sections:
            if section['document_id'] not in seen:first.append(section);seen.add(section['document_id'])
        return [{k:v for k,v in section.items() if k!='score'} for section in (first+[s for s in sections if s not in first])[:limit]]
    engine.save_document=save_document;engine.context=engine.knowledge.context
    story=StoryEngine(engine)
    original_director=engine.director
    def hydrate(filename):
        if not MEDIA_NAME.fullmatch(filename):raise ValueError('Некорректное имя медиа')
        file=engine.DATA/'media'/filename
        if not file.is_file():
            blob=store.download(filename)
            if len(blob)>25*1024*1024:raise ValueError('Файл превышает 25 MB')
            file.write_bytes(blob)
    cache_lock=threading.RLock();cache_readers={}
    def director(body):
        body=copy.deepcopy(body);body.pop('story_context',None)
        if body.get('story_source'):body['story_context']=story.prompt_context(body['story_source'])
        media=[]
        if get('settings','main')['prompt'].get('vision'):
            for r in engine.selected_refs(body.get('reference_ids',[])):
                media.extend(([r['file']] if r.get('file') and r['type']=='image' else [])+r.get('frames',[]))
        acquired=[]
        try:
            with cache_lock:
                for filename in set(media):hydrate(filename);cache_readers[filename]=cache_readers.get(filename,0)+1;acquired.append(filename)
            return original_director(body)
        finally:
            with cache_lock:
                for filename in acquired:
                    cache_readers[filename]-=1
                    if not cache_readers[filename]:
                        (engine.DATA/'media'/filename).unlink(missing_ok=True);del cache_readers[filename]
    engine.director=director
    original_reference_value=engine.reference_value
    engine.reference_value=lambda r,p:media_cache.signed_url(r['file'],86400) if r.get('file') and not r.get('remote_url') else original_reference_value(r,p)
    original_api_request=engine.api_request
    def cloud_api_request(url,*args,**kwargs):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.username or parsed.password:raise ValueError('Онлайн-версия принимает только публичные HTTPS API')
        try:
            addresses=socket.getaddrinfo(parsed.hostname,parsed.port or 443,type=socket.SOCK_STREAM)
            if any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):raise ValueError('Внутренние адреса запрещены в онлайн-версии')
        except socket.gaierror:raise ValueError('Не удалось найти адрес API через DNS')
        return original_api_request(url,*args,**kwargs)
    engine.api_request=cloud_api_request
    def seed():
        nonlocal seeded
        if seeded:return
        with init_lock:
            if seeded:return
            seed_data=json.loads((ROOT/'seed-data.json').read_text(encoding='utf-8'))
            existing={p['id'] for p in store.all('profiles')}
            for p in seed_data['profiles']:
                if p['id'] not in existing:store.put('profiles',p)
            existing={d['id'] for d in store.all('documents')}
            for d in seed_data['documents']:
                if d['id'] not in existing:store.put('documents',d)
            engine.knowledge.migrate()
            seeded=True
    ready_users=set()
    def user_defaults():
        if who.get()['id'] in ready_users:return
        for kind,item in [('settings',{'id':'main','prompt':{'url':'https://elysiumai.net/v1','model':'','vision':False,'video':False,'temperature':.6},'video':{'higgsfield':{'name':'Higgsfield API'},'atlas':{'name':'Atlas Cloud'},'nano':{'name':'NanoAPI'}}}),('workspace',{'id':'main','profile_id':'hf-seedance-i2v','brief':'','reference_ids':[],'parameters':{},'result':None,'messages':[]})]:
            try:get(kind,'main')
            except ValueError:put(kind,item)
        ready_users.add(who.get()['id'])
    def sealed_session(tokens):
        return cipher.encrypt(json.dumps({'access_token':tokens['access_token'],'refresh_token':tokens['refresh_token'],'expires_at':tokens.get('expires_at',time.time()+tokens.get('expires_in',3600))}).encode()).decode()
    def session_tokens():
        try:return json.loads(cipher.decrypt(session['auth'].encode()).decode())
        except (KeyError,InvalidToken,ValueError):return None
    def identity():
        tokens=session_tokens()
        if not tokens:return None
        try:
            if tokens['expires_at']<time.time()+90:tokens=store.refresh(tokens['refresh_token']);session['auth']=sealed_session(tokens)
            token_hash=hashlib.sha256(tokens['access_token'].encode()).hexdigest()
            with identity_lock:
                cached=identity_cache.get(token_hash)
                if cached and cached[0]>time.monotonic():user=copy.deepcopy(cached[1])
                else:
                    user=store.user(tokens['access_token'])
                    if len(identity_cache)>=128:identity_cache.clear()
                    identity_cache[token_hash]=(time.monotonic()+20,copy.deepcopy(user))
        except CloudError as error:
            if error.status in [400,401,403]:session.clear();return None
            raise
        if user.get('email','').lower() not in allowed or not user.get('email_confirmed_at'):session.clear();return None
        return {'id':user['id'],'email':user['email'],'name':user.get('user_metadata',{}).get('name') or user['email'].split('@')[0]}
    @app.before_request
    def authorize():
        if request.path=='/healthz' or request.path.startswith('/static/') or request.path in ['/login','/auth/login','/auth/csrf']:return
        user=identity()
        if not user:
            if request.path.startswith('/api/') or request.path.startswith('/auth/'):return jsonify(error='Сессия истекла. Войдите в студию.',login_required=True),401
            return redirect('/login')
        g.user=user;g.user_context=who.set(user)
        if request.method not in ['GET','HEAD','OPTIONS']:
            if request.headers.get('Origin') and request.headers['Origin']!=request.host_url.rstrip('/'):return jsonify(error='Внешний Origin запрещён'),403
            if request.headers.get('X-Studio-Request')!='local' or not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf','')):return jsonify(error='Проверка CSRF не пройдена. Обновите страницу.'),403
        if request.path.startswith('/api/relay'):return jsonify(error='Онлайн-студия не предоставляет открытый proxy'),404
        if request.path.startswith('/media/'):return
        seed();user_defaults()
    @app.teardown_request
    def clear_context(error):
        if hasattr(g,'user_context'):who.reset(g.user_context)
    @app.after_request
    def headers(response):
        if request.path.startswith('/static/'):
            name=request.path.rsplit('/',1)[-1]
            immutable=request.args.get('v')==asset_versions.get(name) or name.endswith('.woff2')
            response.headers['Cache-Control']='public, max-age=31536000, immutable' if immutable else 'public, max-age=0, must-revalidate'
        elif request.path.startswith('/media/') and response.status_code in [200,302,304]:response.headers['Cache-Control']='private, max-age=300'
        else:response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer';response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        return response
    @app.errorhandler(StoryConflict)
    def story_conflict(error):return jsonify(error=str(error)),409
    @app.errorhandler(CloudError)
    def cloud_error(error):return jsonify(error=str(error)),error.status if 400<=error.status<600 else 502
    @app.errorhandler(413)
    def payload_error(error):return jsonify(error='Файл слишком большой. Для онлайн-версии используйте медиа до 25 MB.'),413
    @app.get('/healthz')
    def health():return jsonify(ok=True,app='ai-video-studio-online',version='2.1.0')
    @app.get('/auth/csrf')
    def csrf():session.setdefault('csrf',secrets.token_urlsafe(32));return jsonify(csrf=session['csrf'])
    @app.get('/login')
    def login_page():return send_from_directory(ROOT/'static','login.html')
    @app.post('/auth/login')
    def login():
        if request.headers.get('Origin') and request.headers['Origin']!=request.host_url.rstrip('/'):return jsonify(error='Внешний Origin запрещён'),403
        if not session.get('csrf') or not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf']):return jsonify(error='Обновите страницу входа'),403
        body=request.get_json(silent=True) or {};email=str(body.get('email','')).strip().lower();password=str(body.get('password',''))
        if email not in allowed:return jsonify(error='Доступ разрешён только двум участницам студии.'),403
        tokens=store.signin(email,password);user=store.user(tokens['access_token'])
        if user.get('email','').lower()!=email or not user.get('email_confirmed_at'):return jsonify(error='Подтвердите email аккаунта Supabase Auth'),403
        session.clear();session.permanent=True;session['auth']=sealed_session(tokens);session['csrf']=secrets.token_urlsafe(32)
        return jsonify(ok=True,csrf=session['csrf'])
    @app.get('/auth/me')
    def me():return jsonify(user=g.user,csrf=session['csrf'])
    @app.post('/auth/logout')
    def logout():
        tokens=session_tokens()
        if tokens:
            with identity_lock:identity_cache.pop(hashlib.sha256(tokens['access_token'].encode()).hexdigest(),None)
        session.clear();return jsonify(ok=True)
    @app.get('/static/<path:name>')
    def static_file(name):return send_from_directory(ROOT/'static',name)
    @app.get('/media/<name>')
    def media(name):
        if not MEDIA_NAME.fullmatch(name):abort(404)
        references=media_references()
        if not any(name==r.get('file') or name in r.get('frames',[]) for r in references):abort(404)
        if request.args.get('preview')=='1':
            try:
                file=media_cache.preview(name)
                return send_file(file,mimetype='image/webp',conditional=True,etag='preview-v1-'+name)
            except ValueError:return redirect(media_cache.signed_url(name))
        return redirect(media_cache.signed_url(name))
    class CloudHandler(engine.Handler):
        def authorized(self,write=False):pass # Flask above authenticates, authorizes Origin and checks CSRF.
        def send(self,data,status=200,mime='application/json; charset=utf-8'):
            if isinstance(data,dict) and 'profiles' in data and 'workspace' in data:data.update(user=g.user,online=True)
            blob=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode();self.result=Response(blob,status=status,content_type=mime);return self.result
    @app.route('/',defaults={'path':''},methods=['GET'])
    @app.route('/api/<path:path>',methods=['GET','POST'])
    def engine_route(path):
        if path.startswith('story/'):
            action=path[6:]
            try:
                if action=='state' and request.method=='GET':return jsonify(story.state())
                if request.method!='POST':return jsonify(error='Неизвестная сценарная операция'),404
                body=request.get_json(silent=True) or {}
                if not isinstance(body,dict):raise ValueError('Нужен JSON объект')
                if action=='project':result=story.save_project(body)
                elif action=='episode':result=story.save_episode(body)
                elif action=='import':result=story.import_project(body)
                elif action=='export':result=story.export(body.get('project_id',''))
                elif action=='revisions':
                    if body.get('kind') not in ['projects','episodes']:raise ValueError('Неизвестный вид материала')
                    result=story.revisions(body['kind'],body.get('id',''))
                elif action=='restore':result=story.restore(body)
                elif action=='analyze':result=story.analyze(body)
                elif action=='apply':result=story.apply(body)
                elif action=='handoff':result=story.handoff(body)
                elif action=='plan':
                    project,episode,scene,shot=story.shot_context(body);result=story.plan(project,scene,shot)
                else:return jsonify(error='Неизвестная сценарная операция'),404
                return jsonify(result)
            except StoryConflict:raise
            except ValueError as error:return jsonify(error=str(error)),400
        if request.path=='/':
            html=(ROOT/'static'/'index.html').read_text(encoding='utf-8')
            for name,version in asset_versions.items():
                if name.endswith(('.js','.css')):html=html.replace('/static/'+name+'"','/static/'+name+'?v='+version+'"')
            return Response(html,content_type='text/html; charset=utf-8')
        if path=='state' and request.method=='GET':
            kinds=['profiles','documents','references','history','jobs','examples','workspace','settings','secrets']
            scoped=[scope(kind) for kind in kinds]
            g.studio_snapshot=store.snapshot(scoped) if hasattr(store,'snapshot') else {key:store.all(key) for key in scoped}
            with ref_lock:ref_cache.update(items=g.studio_snapshot['references'],until=time.monotonic()+10)
        if request.path.startswith('/api/') and request.method=='POST':
            body=request.get_json(silent=True) or {}
            if path=='poll':
                job=get('jobs',body.get('id',''))
                if job.get('owner_id')!=g.user['id']:return jsonify(error='Проверять задание может участница, которая его создала.'),403
            if path=='delete' and body.get('kind')=='documents':delete('documents',body['id']);return jsonify(ok=True)
            if path=='document' and body.get('id'):
                current=get('documents',body['id'])
                if body.get('version') is not None and body['version']!=current['version']:return jsonify(error='Документ уже изменён другой участницей. Обновите библиотеку и откройте новую версию.'),409
        handler=object.__new__(CloudHandler);handler.path=request.path;handler.headers=request.headers;handler.rfile=io.BytesIO(request.get_data());handler.result=None
        if request.method=='POST':handler.do_POST()
        else:handler.do_GET()
        return handler.result if handler.result is not None else (jsonify(error='Неизвестная операция'),400)
    app.extensions['studio_story']=story;app.extensions['studio_engine']=engine;app.extensions['studio_store']=store;app.extensions['studio_cipher']=cipher
    return app

if __name__=='__main__':
    application=create_app();application.run(host='127.0.0.1',port=int(os.environ.get('PORT','8767')),debug=False)
