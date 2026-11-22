"""Small private preview cache. Originals in Supabase are never rewritten."""
import hashlib,io,threading,time
from pathlib import Path
from PIL import Image,ImageOps,UnidentifiedImageError

class MediaCache:
    def __init__(self,store,directory):
        self.store=store;self.directory=Path(directory);self.directory.mkdir(exist_ok=True)
        self.locks=[threading.Lock() for _ in range(16)];self.workers=threading.BoundedSemaphore(2)
        self.link_lock=threading.Lock();self.links={}
    def signed_url(self,name,expires=3600):
        key=(name,expires)
        with self.link_lock:
            entry=self.links.get(key)
            if entry and entry[0]>time.monotonic():return entry[1]
            url=self.store.signed_url(name,expires)
            if len(self.links)>=512:self.links.clear()
            self.links[key]=(time.monotonic()+max(1,expires-60),url)
            return url
    def preview(self,name):
        target=self.directory/(name+'.webp')
        with self.locks[int(hashlib.sha256(name.encode()).hexdigest()[:8],16)%len(self.locks)]:
            if target.is_file():return target
            with self.workers:
                original=self.store.download(name)
                if len(original)>25*1024*1024:raise ValueError('Файл превышает 25 MB')
                try:
                    with Image.open(io.BytesIO(original)) as image:
                        if image.width*image.height>24_000_000:raise ValueError('Изображение слишком велико для превью. Откройте оригинал.')
                        image.draft('RGB',(640,640))
                        image=ImageOps.exif_transpose(image)
                        image.thumbnail((640,640),Image.Resampling.LANCZOS)
                        image=image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                        data=io.BytesIO();image.save(data,format='WEBP',quality=80,method=4)
                except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
                    raise ValueError('Не удалось построить превью. Откройте оригинал.')
                # At most 48 MB of disposable previews on the free server.
                files=sorted(self.directory.glob('*.webp'),key=lambda f:f.stat().st_mtime)
                total=sum(f.stat().st_size for f in files)
                for file in files:
                    if total<=48*1024*1024:break
                    total-=file.stat().st_size;file.unlink(missing_ok=True)
                temporary=target.with_suffix('.tmp');temporary.write_bytes(data.getvalue());temporary.replace(target)
                return target
    def remove(self,names):
        for name in names:
            with self.locks[int(hashlib.sha256(name.encode()).hexdigest()[:8],16)%len(self.locks)]:
                (self.directory/(name+'.webp')).unlink(missing_ok=True)
        with self.link_lock:
            for key in list(self.links):
                if key[0] in names:del self.links[key]
