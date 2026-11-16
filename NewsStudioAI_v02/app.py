
from __future__ import annotations
import hashlib, json, os, re, secrets, shutil, sqlite3, subprocess, threading, uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    import sys
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    IS_FROZEN = getattr(sys, "frozen", False)
    APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
except Exception:
    IS_FROZEN = False
    RESOURCE_DIR = APP_DIR = Path(__file__).resolve().parent

WORKSPACE = (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NewsStudioAI" / "workspace") if IS_FROZEN else (APP_DIR / "workspace")
PROJECTS_DIR = WORKSPACE / "projects"
AUTH_DB = WORKSPACE / "auth.sqlite3"
STATIC_DIR = RESOURCE_DIR / "static"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="News Studio AI", version="0.2.1", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
COOKIE = "newsstudio_session"
MAX_UPLOAD = 4 * 1024 * 1024 * 1024

def db():
    c=sqlite3.connect(AUTH_DB, timeout=20); c.row_factory=sqlite3.Row; return c

def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,salt TEXT,password_hash TEXT,role TEXT,created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,username TEXT,expires_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY,project_id TEXT,username TEXT,body TEXT,created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS reviews(project_id TEXT PRIMARY KEY,status TEXT,updated_by TEXT,updated_at TEXT)")
        c.commit()
init_db()

def password_hash(password, salt=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),310000).hex()
    return salt,digest

def verify_password(password,salt,expected):
    return secrets.compare_digest(password_hash(password,salt)[1],expected)

def user_count():
    with db() as c: return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def user_for_token(token):
    if not token: return None
    th=hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        r=c.execute("SELECT users.username,users.role FROM sessions JOIN users ON users.username=sessions.username WHERE token_hash=? AND expires_at>?",
                    (th,datetime.now().isoformat(timespec="seconds"))).fetchone()
    return dict(r) if r else None

def issue_session(resp, username, request):
    token=secrets.token_urlsafe(36); th=hashlib.sha256(token.encode()).hexdigest()
    expiry=(datetime.now()+timedelta(days=7)).isoformat(timespec="seconds")
    with db() as c:
        c.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)",(th,username,expiry)); c.commit()
    resp.set_cookie(COOKIE,token,max_age=604800,httponly=True,samesite="strict",secure=request.url.scheme=="https",path="/")

OPEN_PATHS={"/","/api/health","/api/auth/status","/api/auth/setup","/api/auth/login"}
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path=request.url.path
    if path in OPEN_PATHS or path.startswith("/static/") or path=="/favicon.ico":
        return await call_next(request)
    if request.method in ("POST","PUT","PATCH","DELETE"):
        origin=request.headers.get("origin"); host=request.headers.get("host","")
        if origin and urlparse(origin).netloc and urlparse(origin).netloc!=host:
            return JSONResponse({"detail":"درخواست بین‌دامنه‌ای مجاز نیست"},status_code=403)
    user=user_for_token(request.cookies.get(COOKIE))
    if not user: return JSONResponse({"detail":"ابتدا وارد حساب کاربری شوید"},status_code=401)
    request.state.user=user
    return await call_next(request)

def role(request, allowed):
    u=getattr(request.state,"user",None)
    if not u or u["role"] not in allowed: raise HTTPException(403,"سطح دسترسی کافی نیست")
    return u

def safe_name(name):
    n=Path(name or "media").name
    return re.sub(r"[^A-Za-z0-9._\-\u0600-\u06FF ]+","_",n).strip(" .")[:120] or "media"

def pdir(pid):
    if not re.fullmatch(r"[a-f0-9]{8}",pid): raise HTTPException(404,"پروژه پیدا نشد")
    p=PROJECTS_DIR/pid
    if not p.exists(): raise HTTPException(404,"پروژه پیدا نشد")
    return p

def asset_dir(pid):
    p=pdir(pid)/"assets"; p.mkdir(exist_ok=True); return p

def child_file(folder,filename):
    p=folder/Path(filename).name
    if p.parent!=folder or not p.exists(): raise HTTPException(404,"فایل پیدا نشد")
    return p

def media_file(pid,filename): return child_file(pdir(pid)/"originals",filename)

def defaults(pid,title):
    now=datetime.now().isoformat(timespec="seconds")
    return {"id":pid,"title":title,"headline":"","profile":"vertical","source":None,"clips":[],"subtitles":[],
        "music":None,"audio_settings":{"denoise":True,"music_volume":0.16,"music_duck":True},
        "graphics":{"mode":"ready","template":"breaking","brand_name":"NEWS","headline":"","lower_name":"","lower_role":"",
                    "ticker":"","breaking":True,"show_logo":True,"primary":"#15344A","accent":"#E34C5A"},
        "silence_suggestions":[],"created_at":now,"updated_at":now}

def load_project(pid):
    try:
        data=json.loads((pdir(pid)/"project.json").read_text(encoding="utf-8"))
        d=defaults(pid,data.get("title","پروژه خبری"))
        for k,v in d.items(): data.setdefault(k,v)
        return data
    except HTTPException: raise
    except Exception: raise HTTPException(500,"فایل پروژه قابل خواندن نیست")

def save_project(data):
    p=pdir(data["id"])/"project.json"; t=p.with_suffix(".tmp")
    t.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"); t.replace(p)

def media_tool(name: str):
    """Find a bundled FFmpeg tool first, then fall back to the system PATH."""
    executable = name + (".exe" if os.name == "nt" and not name.lower().endswith(".exe") else "")
    candidates = (
        RESOURCE_DIR / "ffmpeg" / executable,
        RESOURCE_DIR / "vendor" / "ffmpeg" / "bin" / executable,
        APP_DIR / "ffmpeg" / executable,
        APP_DIR / "vendor" / "ffmpeg" / "bin" / executable,
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(executable) or shutil.which(name)

def ffmpeg(): return media_tool("ffmpeg")
def ffprobe(): return media_tool("ffprobe")

def probe(path):
    if not ffprobe(): return {"duration":0,"has_audio":False,"width":None,"height":None}
    cmd=[ffprobe(),"-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(path)]
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=45,check=True); d=json.loads(r.stdout or "{}")
        streams=d.get("streams",[]); v=next((s for s in streams if s.get("codec_type")=="video"),{})
        return {"duration":float(d.get("format",{}).get("duration",0) or 0),
                "has_audio":any(s.get("codec_type")=="audio" for s in streams),"width":v.get("width"),"height":v.get("height")}
    except Exception: return {"duration":0,"has_audio":False,"width":None,"height":None}

class ProjectCreate(BaseModel): title:str="پروژه خبری جدید"
class ProjectUpdate(BaseModel):
    title:str|None=None; headline:str|None=None; profile:str|None=None
    clips:list[dict[str,Any]]|None=None; subtitles:list[dict[str,Any]]|None=None
    graphics:dict[str,Any]|None=None; audio_settings:dict[str,Any]|None=None
class Credentials(BaseModel): username:str; password:str
class UserCreate(BaseModel): username:str; password:str; role:str="editor"
class CommentIn(BaseModel): body:str
class ReviewIn(BaseModel): status:str

@app.get("/",response_class=HTMLResponse)
def index(): return FileResponse(STATIC_DIR/"index.html")

@app.get("/api/health")
def health():
    try: import faster_whisper; whisper=True
    except Exception: whisper=False
    try: import PIL; pillow=True
    except Exception: pillow=False
    return {"ok":True,"ffmpeg":bool(ffmpeg()),"ffprobe":bool(ffprobe()),"whisper":whisper,"pillow":pillow,"version":"0.2.1"}

@app.get("/api/auth/status")
def auth_status(request:Request):
    u=user_for_token(request.cookies.get(COOKIE))
    return {"setup_required":user_count()==0,"authenticated":bool(u),"user":u}

@app.post("/api/auth/setup")
def auth_setup(data:Credentials,request:Request):
    username=data.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}",username): raise HTTPException(400,"نام کاربری باید ۳ تا ۳۲ نویسه انگلیسی باشد")
    if len(data.password)<10: raise HTTPException(400,"رمز عبور باید حداقل ۱۰ نویسه باشد")
    salt,digest=password_hash(data.password)
    # Serialize first-run setup so two simultaneous requests cannot create two admins.
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise HTTPException(409,"حساب مدیر قبلاً ساخته شده است")
        c.execute("INSERT INTO users(username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                  (username,salt,digest,"admin",datetime.now().isoformat(timespec="seconds")))
        c.commit()
    resp=JSONResponse({"ok":True,"user":{"username":username,"role":"admin"}}); issue_session(resp,username,request); return resp

@app.post("/api/auth/login")
def auth_login(data:Credentials,request:Request):
    username=data.username.strip().lower()
    with db() as c: row=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not row or not verify_password(data.password,row["salt"],row["password_hash"]): raise HTTPException(401,"نام کاربری یا رمز عبور نادرست است")
    resp=JSONResponse({"ok":True,"user":{"username":username,"role":row["role"]}}); issue_session(resp,username,request); return resp

@app.post("/api/auth/logout")
def auth_logout(request:Request):
    token=request.cookies.get(COOKIE)
    if token:
        with db() as c: c.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),)); c.commit()
    resp=JSONResponse({"ok":True}); resp.delete_cookie(COOKIE,path="/"); return resp

@app.get("/api/auth/me")
def auth_me(request:Request): return request.state.user

@app.get("/api/users")
def users(request:Request):
    role(request,("admin",))
    with db() as c: rows=c.execute("SELECT username,role,created_at FROM users ORDER BY username").fetchall()
    return [dict(x) for x in rows]

@app.post("/api/users")
def add_user(data:UserCreate,request:Request):
    role(request,("admin",)); username=data.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}",username): raise HTTPException(400,"نام کاربری نامعتبر است")
    if len(data.password)<10: raise HTTPException(400,"رمز عبور حداقل ۱۰ نویسه باشد")
    if data.role not in ("admin","editor","reviewer"): raise HTTPException(400,"نقش نامعتبر است")
    salt,digest=password_hash(data.password)
    try:
        with db() as c: c.execute("INSERT INTO users(username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?)",
            (username,salt,digest,data.role,datetime.now().isoformat(timespec="seconds"))); c.commit()
    except sqlite3.IntegrityError: raise HTTPException(409,"نام کاربری تکراری است")
    return {"username":username,"role":data.role}

@app.get("/api/projects")
def projects():
    out=[]
    for f in PROJECTS_DIR.iterdir():
        p=f/"project.json"
        if f.is_file() or not p.exists(): continue
        try:
            d=json.loads(p.read_text(encoding="utf-8")); out.append({"id":d["id"],"title":d.get("title","پروژه"),"updated_at":d.get("updated_at")})
        except Exception: pass
    return sorted(out,key=lambda x:x.get("updated_at") or "",reverse=True)

@app.post("/api/projects")
def create_project(data:ProjectCreate,request:Request):
    role(request,("admin","editor")); pid=uuid.uuid4().hex[:8]; folder=PROJECTS_DIR/pid
    for n in ("originals","renders","assets"): (folder/n).mkdir(parents=True,exist_ok=True)
    d=defaults(pid,data.title.strip()[:120] or "پروژه خبری"); save_project(d); return d

@app.get("/api/projects/{pid}")
def get_project(pid:str): return load_project(pid)

@app.put("/api/projects/{pid}")
def update_project(pid:str,data:ProjectUpdate,request:Request):
    role(request,("admin","editor")); d=load_project(pid)
    for k,v in data.model_dump(exclude_unset=True).items():
        if v is None: continue
        if k=="title": d[k]=str(v)[:120]
        elif k=="headline": d[k]=str(v)[:300]
        elif k=="profile" and v in ("vertical","horizontal","square"): d[k]=v
        elif k=="clips":
            arr=[]
            for x in v[:500]:
                try:
                    a,b=max(0,float(x.get("start",0))),max(0,float(x.get("end",0)))
                    if b>a: arr.append({"id":str(x.get("id") or uuid.uuid4().hex[:8]),"start":round(a,3),"end":round(b,3)})
                except Exception: pass
            d[k]=sorted(arr,key=lambda x:x["start"])
        elif k=="subtitles":
            arr=[]
            for x in v[:5000]:
                try:
                    a,b=max(0,float(x.get("start",0))),max(0,float(x.get("end",0))); txt=str(x.get("text","")).strip()[:1000]
                    if b>a and txt: arr.append({"id":str(x.get("id") or uuid.uuid4().hex[:8]),"start":round(a,3),"end":round(b,3),"text":txt})
                except Exception: pass
            d[k]=sorted(arr,key=lambda x:x["start"])
        elif k=="graphics" and isinstance(v,dict):
            g=d["graphics"]
            allowed={"mode","template","brand_name","headline","lower_name","lower_role","ticker","breaking","show_logo","primary","accent"}
            for a,b in v.items():
                if a in allowed: g[a]=bool(b) if a in ("breaking","show_logo") else str(b)[:500]
        elif k=="audio_settings" and isinstance(v,dict):
            a=d["audio_settings"]; a["denoise"]=bool(v.get("denoise",a["denoise"])); a["music_duck"]=bool(v.get("music_duck",a["music_duck"]))
            try: a["music_volume"]=min(1,max(0,float(v.get("music_volume",a["music_volume"]))))
            except Exception: pass
    d["updated_at"]=datetime.now().isoformat(timespec="seconds"); save_project(d); return d

async def save_upload(file:UploadFile,dest:Path,limit=MAX_UPLOAD):
    total=0
    try:
        with dest.open("wb") as out:
            while True:
                chunk=await file.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>limit: raise HTTPException(413,"حجم فایل بیش از حد مجاز است")
                out.write(chunk)
    except Exception: dest.unlink(missing_ok=True); raise
    return total

@app.post("/api/projects/{pid}/upload")
async def upload_video(pid:str,request:Request,file:UploadFile=File(...)):
    role(request,("admin","editor"))
    if Path(file.filename or "").suffix.lower() not in (".mp4",".mov",".m4v",".mkv",".webm",".avi"): raise HTTPException(400,"فرمت ویدئو پشتیبانی نمی‌شود")
    folder=pdir(pid)/"originals"; name=uuid.uuid4().hex[:8]+"_"+safe_name(file.filename); dest=folder/name
    size=await save_upload(file,dest); info=probe(dest); d=load_project(pid)
    d["source"]={"filename":name,"original_name":safe_name(file.filename),"size":size,**info}
    if info["duration"]>0: d["clips"]=[{"id":uuid.uuid4().hex[:8],"start":0.0,"end":round(info["duration"],3)}]
    d["subtitles"]=[]; d["updated_at"]=datetime.now().isoformat(timespec="seconds"); save_project(d); return d

@app.post("/api/projects/{pid}/music")
async def upload_music(pid:str,request:Request,file:UploadFile=File(...)):
    role(request,("admin","editor"))
    if Path(file.filename or "").suffix.lower() not in (".mp3",".wav",".m4a",".aac",".flac",".ogg"): raise HTTPException(400,"فرمت صدا پشتیبانی نمی‌شود")
    folder=pdir(pid)/"assets"; name="music_"+uuid.uuid4().hex[:8]+"_"+safe_name(file.filename)
    size=await save_upload(file,folder/name,1024*1024*1024); d=load_project(pid)
    d["music"]={"filename":name,"original_name":safe_name(file.filename),"size":size}; save_project(d); return d

@app.post("/api/projects/{pid}/logo")
async def upload_logo(pid:str,request:Request,file:UploadFile=File(...)):
    role(request,("admin","editor"))
    if Path(file.filename or "").suffix.lower() not in (".png",".jpg",".jpeg",".webp"): raise HTTPException(400,"فرمت لوگو نامعتبر است")
    folder=pdir(pid)/"assets"; name="logo_"+uuid.uuid4().hex[:8]+Path(file.filename).suffix.lower(); dest=folder/name
    await save_upload(file,dest,20*1024*1024)
    try:
        from PIL import Image
        with Image.open(dest) as im: im.verify()
    except Exception: dest.unlink(missing_ok=True); raise HTTPException(400,"فایل تصویر معتبر نیست")
    d=load_project(pid); d["graphics"]["logo_file"]=name; save_project(d); return d

@app.get("/media/{pid}/{filename}")
def media(pid:str,filename:str): return FileResponse(media_file(pid,filename))
@app.get("/assets/{pid}/{filename}")
def asset(pid:str,filename:str): return FileResponse(child_file(pdir(pid)/"assets",filename))

def set_job(jid,**kwargs):
    with JOBS_LOCK: JOBS.setdefault(jid,{}).update(kwargs)
def get_job(jid):
    with JOBS_LOCK:
        if jid not in JOBS: raise HTTPException(404,"کار پیدا نشد")
        return dict(JOBS[jid])
def new_job(kind,pid):
    jid=uuid.uuid4().hex[:12]
    with JOBS_LOCK: JOBS[jid]={"id":jid,"kind":kind,"project_id":pid,"status":"queued","progress":0,"message":"در صف پردازش"}
    return jid

def clips_for(d):
    a=[]
    for x in d.get("clips",[]):
        try:
            s,e=float(x["start"]),float(x["end"])
            if e>s>=0: a.append({"start":s,"end":e})
        except Exception: pass
    if not a and d.get("source",{}).get("duration"): a=[{"start":0.0,"end":float(d["source"]["duration"])}]
    return sorted(a,key=lambda x:x["start"])

def remap_subs(subs,clips):
    out=[]; cursor=0
    for c in clips:
        for s in subs:
            a=max(c["start"],float(s["start"])); b=min(c["end"],float(s["end"]))
            if b>a: out.append({"id":uuid.uuid4().hex[:8],"start":round(cursor+a-c["start"],3),"end":round(cursor+b-c["start"],3),"text":s["text"]})
        cursor+=c["end"]-c["start"]
    return sorted(out,key=lambda x:x["start"])

def transcribe_worker(jid,pid,model_name):
    try:
        set_job(jid,status="running",progress=5,message="آماده‌سازی Whisper")
        d=load_project(pid); src=media_file(pid,d["source"]["filename"])
        from faster_whisper import WhisperModel
        model=WhisperModel(model_name,device="cpu",compute_type="int8",cpu_threads=2,num_workers=1)
        set_job(jid,progress=25,message="تشخیص گفتار فارسی در حال انجام است")
        segs,info=model.transcribe(str(src),language="fa",task="transcribe",beam_size=1,best_of=1,vad_filter=True,condition_on_previous_text=False)
        raw=[{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segs]
        d["subtitles"]=remap_subs(raw,clips_for(d)); d["updated_at"]=datetime.now().isoformat(timespec="seconds"); save_project(d)
        set_job(jid,status="completed",progress=100,message="تشخیص گفتار تمام شد",result={"segments":len(d["subtitles"]),"language":getattr(info,"language","fa")})
    except Exception as e: set_job(jid,status="failed",progress=100,message=str(e))

@app.post("/api/projects/{pid}/transcribe")
def transcribe(pid:str,request:Request,background:BackgroundTasks,model:str="base"):
    role(request,("admin","editor"))
    if model not in ("tiny","base","small"): raise HTTPException(400,"مدل معتبر نیست")
    d=load_project(pid)
    if not d.get("source"): raise HTTPException(400,"ابتدا ویدئو وارد کنید")
    jid=new_job("transcription",pid); background.add_task(transcribe_worker,jid,pid,model); return {"job_id":jid}

@app.post("/api/projects/{pid}/detect-silence")
def detect_silence(pid:str,request:Request,background:BackgroundTasks,noise_db:int=-32,min_duration:float=0.6):
    role(request,("admin","editor")); d=load_project(pid)
    if not d.get("source") or not d["source"].get("has_audio"): raise HTTPException(400,"ویدئو باید صدای اصلی داشته باشد")
    jid=new_job("silence",pid); background.add_task(silence_worker,jid,pid,noise_db,min_duration); return {"job_id":jid}

def silence_worker(jid,pid,noise_db,min_duration):
    try:
        if not ffmpeg(): raise RuntimeError("FFmpeg نصب نیست")
        d=load_project(pid); src=media_file(pid,d["source"]["filename"])
        set_job(jid,status="running",progress=15,message="تحلیل سکوت و مکث‌ها")
        cmd=[ffmpeg(),"-hide_banner","-i",str(src),"-af",f"silencedetect=noise={noise_db}dB:d={min_duration}","-f","null","-"]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
        if r.returncode:
            raise RuntimeError("خطا در تحلیل سکوت با FFmpeg: "+(r.stderr or r.stdout or "نامشخص")[-1800:])
        log=r.stderr or ""
        starts=re.findall(r"silence_start:\s*([0-9.]+)",log); ends=re.findall(r"silence_end:\s*([0-9.]+)",log)
        duration=float(d.get("source",{}).get("duration") or 0); silences=[]
        for i,s in enumerate(starts):
            a=float(s); b=float(ends[i]) if i<len(ends) else duration
            if b>a: silences.append({"start":round(a,3),"end":round(min(b,duration or b),3)})
        d["silence_suggestions"]=silences; save_project(d)
        set_job(jid,status="completed",progress=100,message=f"{len(silences)} بازه سکوت پیدا شد",result={"silences":silences})
    except Exception as e: set_job(jid,status="failed",progress=100,message=str(e))

@app.post("/api/projects/{pid}/apply-silence-cuts")
def apply_silence(pid:str,request:Request):
    role(request,("admin","editor")); d=load_project(pid)
    duration=float(d.get("source",{}).get("duration") or 0); sil=sorted(d.get("silence_suggestions",[]),key=lambda x:x["start"])
    if not sil or duration<=0: raise HTTPException(400,"پیشنهاد سکوتی برای اعمال وجود ندارد")
    keep=[]; cursor=0.0
    for s in sil:
        a=max(0,float(s["start"])); b=min(duration,float(s["end"]))
        if a>cursor+0.08: keep.append({"start":cursor,"end":a})
        cursor=max(cursor,b)
    if duration>cursor+0.08: keep.append({"start":cursor,"end":duration})
    if not keep: raise HTTPException(400,"تمام ویدئو سکوت تشخیص داده شد؛ برش انجام نشد")
    d["subtitles"]=remap_subs(d.get("subtitles",[]),keep)
    d["clips"]=[{"id":uuid.uuid4().hex[:8],**x} for x in keep]
    d["updated_at"]=datetime.now().isoformat(timespec="seconds"); save_project(d); return d

def srt_ts(sec):
    ms=max(0,int(round(float(sec)*1000)))
    return f"{ms//3600000:02}:{(ms%3600000)//60000:02}:{(ms%60000)//1000:02},{ms%1000:03}"

def write_srt(path,subs):
    lines=[]
    for i,s in enumerate(sorted(subs,key=lambda x:float(x["start"])),1):
        txt=str(s.get("text","")).replace("\r","").strip()
        if txt: lines += [str(i),f"{srt_ts(s['start'])} --> {srt_ts(s['end'])}",txt,""]
    path.write_text("\n".join(lines),encoding="utf-8-sig")

def load_font(size):
    from PIL import ImageFont
    candidates=[os.environ.get("NEWS_STUDIO_FONT"),r"C:\Windows\Fonts\tahoma.ttf",r"C:\Windows\Fonts\arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for f in candidates:
        if f and Path(f).exists():
            try: return ImageFont.truetype(f,size)
            except Exception: pass
    return ImageFont.load_default()

def rtl_text(draw,xy,text,font,fill,anchor="ra"):
    try:
        draw.text(xy,text,font=font,fill=fill,anchor=anchor,direction="rtl",language="fa")
    except Exception:
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            shaped=get_display(arabic_reshaper.reshape(str(text)))
            draw.text(xy,shaped,font=font,fill=fill,anchor=anchor)
        except Exception:
            draw.text(xy,text,font=font,fill=fill,anchor=anchor)

def create_graphics(pid,d,w,h):
    from PIL import Image,ImageDraw
    g=d.get("graphics",{}); out=pdir(pid)/"renders"; out.mkdir(exist_ok=True)
    overlay=None; ticker=None
    scale=w/1080; margin=int(42*scale)
    has_graphics=bool(g.get("headline") or g.get("lower_name") or g.get("lower_role") or g.get("breaking") or g.get("show_logo") or g.get("logo_file"))
    if has_graphics:
        im=Image.new("RGBA",(w,h),(0,0,0,0)); dr=ImageDraw.Draw(im)
        def rgb(hex_value, alpha=232, fallback=(15,35,53)):
            try:
                v=str(hex_value).lstrip("#")
                return (int(v[0:2],16),int(v[2:4],16),int(v[4:6],16),alpha)
            except Exception:
                return (*fallback,alpha)
        navy=rgb(g.get("primary","#15344A"),232)
        red=rgb(g.get("accent","#E34C5A"),245,(220,65,78))
        white=(250,252,255,255)
        if g.get("show_logo",True):
            logo=g.get("logo_file"); lp=(pdir(pid)/"assets"/logo) if logo else None
            if lp and lp.exists():
                try:
                    li=Image.open(lp).convert("RGBA"); li.thumbnail((int(190*scale),int(85*scale))); im.alpha_composite(li,(margin,margin))
                except Exception: pass
            elif g.get("brand_name"):
                bw,bh=int(235*scale),int(58*scale)
                dr.rounded_rectangle((margin,margin,margin+bw,margin+bh),radius=int(10*scale),fill=navy,outline=(85,160,190,220),width=max(1,int(2*scale)))
                rtl_text(dr,(margin+bw-int(15*scale),margin+int(15*scale)),str(g["brand_name"])[:35],load_font(max(20,int(27*scale))),white)
        if g.get("breaking"):
            bw,bh=int(200*scale),int(58*scale); x=w-margin-bw
            dr.rounded_rectangle((x,margin,x+bw,margin+bh),radius=int(10*scale),fill=red)
            rtl_text(dr,(x+bw-int(15*scale),margin+int(14*scale)),"خبر فوری",load_font(max(20,int(28*scale))),white)
        headline=str(g.get("headline") or d.get("headline") or "").strip()
        name=str(g.get("lower_name") or "").strip(); job=str(g.get("lower_role") or "").strip()
        if headline or name or job:
            box_h=int((245 if h>w else 185)*scale); y=h-box_h-int(88*scale if g.get("ticker") else 20*scale)
            dr.rounded_rectangle((margin,y,w-margin,y+box_h),radius=int(14*scale),fill=navy,outline=(75,140,170,190),width=max(1,int(2*scale)))
            yy=y+int(55*scale)
            if headline:
                rtl_text(dr,(w-margin-int(22*scale),yy),headline[:105],load_font(max(20,int(39*scale))),white); yy+=int(75*scale)
            if name:
                rtl_text(dr,(w-margin-int(22*scale),yy),name[:55],load_font(max(18,int(31*scale))),(105,225,225,255)); yy+=int(48*scale)
            if job: rtl_text(dr,(w-margin-int(22*scale),yy),job[:75],load_font(max(16,int(24*scale))),(220,232,242,255))
        overlay=out/"graphics_overlay.png"; im.save(overlay)
    text=str(g.get("ticker") or "").strip()
    if text:
        font=load_font(max(22,int(32*scale))); pad=int(45*scale)
        try: box=font.getbbox(text,direction="rtl",language="fa")
        except Exception: box=font.getbbox(text)
        tw=max(250,box[2]-box[0]); sw=max(w,tw+pad*2+int(60*scale)); sh=max(65,int(82*scale))
        strip=Image.new("RGBA",(sw,sh),(13,34,51,242)); sd=ImageDraw.Draw(strip)
        sd.rectangle((0,0,sw,max(3,int(5*scale))),fill=(55,195,202,255))
        rtl_text(sd,(sw-pad,int(16*scale)),text[:240],font,(250,252,255,255))
        ticker=out/"ticker_strip.png"; strip.save(ticker)
    return overlay,ticker

@app.post("/api/projects/{pid}/render")
def render(pid:str,request:Request,background:BackgroundTasks,profile:str="vertical"):
    role(request,("admin","editor"))
    if profile not in ("vertical","horizontal","square"): raise HTTPException(400,"قالب خروجی معتبر نیست")
    if not load_project(pid).get("source"): raise HTTPException(400,"ابتدا ویدئو وارد کنید")
    jid=new_job("render",pid); background.add_task(render_worker,jid,pid,profile); return {"job_id":jid}

def render_worker(jid,pid,profile):
    try:
        if not ffmpeg(): raise RuntimeError("FFmpeg نصب نیست یا در PATH قرار ندارد")
        d=load_project(pid); src=media_file(pid,d["source"]["filename"]); clips=clips_for(d)
        if not clips: raise RuntimeError("هیچ کلیپ معتبری در تایم‌لاین وجود ندارد")
        sizes={"vertical":(1080,1920),"horizontal":(1920,1080),"square":(1080,1080)}; w,h=sizes[profile]
        set_job(jid,status="running",progress=5,message="ساخت ترک‌های تدوین و گرافیک")
        music=None
        if d.get("music"):
            try: music=child_file(pdir(pid)/"assets",d["music"]["filename"])
            except Exception: music=None
        overlay,ticker=create_graphics(pid,d,w,h)
        inputs=["-i",str(src)]; next_i=1; music_i=overlay_i=ticker_i=None
        if music: music_i=next_i; inputs += ["-stream_loop","-1","-i",str(music)]; next_i+=1
        if overlay: overlay_i=next_i; inputs += ["-loop","1","-i",str(overlay)]; next_i+=1
        if ticker: ticker_i=next_i; inputs += ["-loop","1","-i",str(ticker)]; next_i+=1
        graph=[]; vids=[]; auds=[]; has_audio=bool(d.get("source",{}).get("has_audio"))
        for i,c in enumerate(clips):
            a,b=c["start"],c["end"]
            graph.append(f"[0:v:0]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]")
            vids.append(f"[v{i}]")
            if has_audio:
                graph.append(f"[0:a:0]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]"); auds.append(f"[a{i}]")
        if has_audio: graph.append("".join(v+a for v,a in zip(vids,auds))+f"concat=n={len(clips)}:v=1:a=1[vcat][acat]")
        else: graph.append("".join(vids)+f"concat=n={len(clips)}:v=1:a=0[vcat]")
        vlabel="vcat"; subs=d.get("subtitles",[])
        if subs:
            srt=pdir(pid)/"renders"/"captions.srt"; write_srt(srt,subs); sp=srt.resolve().as_posix().replace(":",r"\:")
            mv=160 if ticker or overlay else 55
            graph.append(f"[{vlabel}]subtitles=filename='{sp}':force_style='FontName=Tahoma,FontSize=24,Outline=2,Shadow=1,Alignment=2,MarginV={mv}'[vsub]"); vlabel="vsub"
        if overlay_i is not None: graph.append(f"[{vlabel}][{overlay_i}:v]overlay=0:0:shortest=1:format=auto[vgraphic]"); vlabel="vgraphic"
        if ticker_i is not None: graph.append(f"[{vlabel}][{ticker_i}:v]overlay=x='W-mod(t*150,W+w)':y=H-h:shortest=1:format=auto[vticker]"); vlabel="vticker"
        aset=d.get("audio_settings",{}); voice=None
        if has_audio:
            voice="acat"
            if aset.get("denoise",True):
                graph.append(f"[{voice}]afftdn=nf=-25,highpass=f=70,lowpass=f=15000[vclean]"); voice="vclean"
            graph.append(f"[{voice}]loudnorm=I=-16:TP=-1.5:LRA=11[vnorm]"); voice="vnorm"
        audio_label=None
        if music_i is not None:
            vol=min(1,max(0,float(aset.get("music_volume",.16)))); total=sum(x["end"]-x["start"] for x in clips)
            graph.append(f"[{music_i}:a:0]atrim=duration={total:.3f},asetpts=PTS-STARTPTS,volume={vol:.3f}[musicbase]")
            if has_audio and aset.get("music_duck",True):
                graph.append(f"[musicbase][{voice}]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[ducked]")
                graph.append(f"[{voice}][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]")
            elif has_audio: graph.append(f"[{voice}][musicbase]amix=inputs=2:duration=first:dropout_transition=2[aout]")
            else: graph.append("[musicbase]anull[aout]")
            audio_label="aout"
        elif has_audio: graph.append(f"[{voice}]anull[aout]"); audio_label="aout"
        outdir=pdir(pid)/"renders"; outname=f"NewsStudio_{profile}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"; out=outdir/outname
        cmd=[ffmpeg(),"-y","-hide_banner",*inputs,"-filter_complex_threads","1","-filter_complex",";".join(graph),"-map",f"[{vlabel}]"]
        if audio_label: cmd += ["-map",f"[{audio_label}]","-c:a","aac","-b:a","192k","-ar","48000"]
        else: cmd += ["-an"]
        cmd += ["-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p","-threads","2","-movflags","+faststart",str(out)]
        set_job(jid,progress=20,message="رندر تصویر، زیرنویس، گرافیک و صدا")
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=21600)
        if result.returncode: raise RuntimeError("خطای FFmpeg: "+(result.stderr or result.stdout or "نامشخص")[-2800:])
        set_job(jid,status="completed",progress=100,message="رندر با موفقیت انجام شد",result={"filename":outname,"url":f"/outputs/{pid}/{outname}"})
    except subprocess.TimeoutExpired: set_job(jid,status="failed",progress=100,message="زمان رندر به پایان رسید")
    except Exception as e: set_job(jid,status="failed",progress=100,message=str(e))

@app.get("/api/jobs/{jid}")
def job(jid:str): return get_job(jid)
@app.get("/outputs/{pid}/{filename}")
def output(pid:str,filename:str): return FileResponse(child_file(pdir(pid)/"renders",filename),filename=Path(filename).name)
@app.get("/api/projects/{pid}/srt")
def srt_download(pid:str):
    d=load_project(pid); p=pdir(pid)/"renders"/"subtitles.srt"; write_srt(p,d.get("subtitles",[]))
    return FileResponse(p,filename=f"{pid}_subtitles.srt",media_type="application/x-subrip")

@app.get("/api/projects/{pid}/comments")
def comments(pid:str):
    pdir(pid)
    with db() as c: rows=c.execute("SELECT id,username,body,created_at FROM comments WHERE project_id=? ORDER BY id DESC",(pid,)).fetchall()
    return [dict(x) for x in rows]
@app.post("/api/projects/{pid}/comments")
def add_comment(pid:str,data:CommentIn,request:Request):
    pdir(pid); body=data.body.strip()
    if not body or len(body)>1500: raise HTTPException(400,"متن نظر باید ۱ تا ۱۵۰۰ نویسه باشد")
    with db() as c: c.execute("INSERT INTO comments(project_id,username,body,created_at) VALUES(?,?,?,?)",(pid,request.state.user["username"],body,datetime.now().isoformat(timespec="seconds"))); c.commit()
    return {"ok":True}
@app.get("/api/projects/{pid}/review")
def review(pid:str):
    pdir(pid)
    with db() as c: r=c.execute("SELECT status,updated_by,updated_at FROM reviews WHERE project_id=?",(pid,)).fetchone()
    return dict(r) if r else {"status":"draft"}
@app.post("/api/projects/{pid}/review")
def set_review(pid:str,data:ReviewIn,request:Request):
    role(request,("admin","reviewer"))
    if data.status not in ("draft","in_review","approved","changes_requested"): raise HTTPException(400,"وضعیت نامعتبر است")
    with db() as c:
        c.execute("""INSERT INTO reviews VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET status=excluded.status,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                  (pid,data.status,request.state.user["username"],datetime.now().isoformat(timespec="seconds"))); c.commit()
    return {"status":data.status}
