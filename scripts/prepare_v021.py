from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "NewsStudioAI_v02"
if not ROOT.is_dir():
    raise SystemExit(f"Source folder not found: {ROOT}")

def patch(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Patch anchor not found in {relative_path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

patch(
    "app.py",
    'app = FastAPI(title="News Studio AI", version="0.2.0", docs_url=None, redoc_url=None)',
    'app = FastAPI(title="News Studio AI", version="0.2.1", docs_url=None, redoc_url=None)',
)
patch(
    "app.py",
    'def ffmpeg(): return shutil.which("ffmpeg")\ndef ffprobe(): return shutil.which("ffprobe")',
    '''def media_tool(name: str):
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
def ffprobe(): return media_tool("ffprobe")''',
)
patch("app.py", '"version":"0.2.0"', '"version":"0.2.1"')
patch(
    "app.py",
    '''    if user_count(): raise HTTPException(409,"حساب مدیر قبلاً ساخته شده است")
    username=data.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}",username): raise HTTPException(400,"نام کاربری باید ۳ تا ۳۲ نویسه انگلیسی باشد")
    if len(data.password)<10: raise HTTPException(400,"رمز عبور باید حداقل ۱۰ نویسه باشد")
    salt,digest=password_hash(data.password)
    with db() as c:
        c.execute("INSERT INTO users(username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                  (username,salt,digest,"admin",datetime.now().isoformat(timespec="seconds"))); c.commit()
''',
    '''    username=data.username.strip().lower()
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
''',
)
patch(
    "app.py",
    '''        r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800); log=r.stderr or ""
        starts=re.findall(r"silence_start:\\s*([0-9.]+)",log); ends=re.findall(r"silence_end:\\s*([0-9.]+)",log)
''',
    '''        r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
        if r.returncode:
            raise RuntimeError("خطا در تحلیل سکوت با FFmpeg: "+(r.stderr or r.stdout or "نامشخص")[-1800:])
        log=r.stderr or ""
        starts=re.findall(r"silence_start:\\s*([0-9.]+)",log); ends=re.findall(r"silence_end:\\s*([0-9.]+)",log)
''',
)

reviewer_helper = '''function setReviewerMode(){
  $("newProject").hidden=true;
  const selectors=["#chooseVideo","#replaceVideo","#timeline input","#timeline button","#audio input","#audio button","#graphics input","#graphics select","#graphics button","#transcribe","#addSubtitle","#whisperModel","#subtitleRows input","#subtitleRows button","#profile","#render"];
  selectors.forEach(selector=>document.querySelectorAll(selector).forEach(el=>el.disabled=true));
  $("downloadSrt").disabled=false;
  $("reviewStatus").disabled=false;
  $("saveReview").disabled=false;
  $("sendComment").disabled=false;
  $("commentText").disabled=false;
}
'''
js_path = ROOT / "static/app.js"
js = js_path.read_text(encoding="utf-8")
if "function setReviewerMode()" not in js:
    js = js.replace("async function start()", reviewer_helper + "async function start()", 1)
old_editor = 'if(user.role==="editor"){$("reviewStatus").disabled=true;$("saveReview").disabled=true}await health();await loadProjects()}'
new_editor = 'if(user.role==="editor"){$("reviewStatus").disabled=true;$("saveReview").disabled=true}if(user.role==="reviewer")setReviewerMode();await health();await loadProjects()}'
if new_editor not in js:
    if old_editor not in js:
        raise SystemExit("Patch anchor not found in static/app.js (start)")
    js = js.replace(old_editor, new_editor, 1)
old_projects = 'else if(arr.length)await openProject(arr[0].id);else await createProject("پروژه خبری جدید")}'
new_projects = 'else if(arr.length)await openProject(arr[0].id);else if(user?.role==="reviewer"){project=null;$("projectTitle").textContent="هنوز پروژه‌ای برای بازبینی وجود ندارد";$("sourceTag").textContent="بدون فایل";$("duration").textContent="—";$("dimensions").textContent="—";$("hasAudio").textContent="—";$("player").hidden=true;$("emptyVideo").hidden=false;$("emptyVideo").querySelector("b").textContent="هنوز پروژه‌ای ثبت نشده است";$("emptyVideo").querySelector("button").hidden=true}else await createProject("پروژه خبری جدید")}'
if new_projects not in js:
    if old_projects not in js:
        raise SystemExit("Patch anchor not found in static/app.js (loadProjects)")
    js = js.replace(old_projects, new_projects, 1)
old_subtitle = '$("addSubtitle").onclick=async()=>{if(!project.source)return toast("ابتدا ویدئو وارد کنید");const a=Number($("player").currentTime||0);project.subtitles=[...(project.subtitles||[]),{id:crypto.randomUUID().slice(0,8),start:a,end:a+3,text:"متن زیرنویس را وارد کنید"}];await save(false);renderSubs();refreshTracks()};'
new_subtitle = old_subtitle + '\n$("downloadSrt").onclick=()=>{if(!project)return toast("ابتدا یک پروژه انتخاب کنید");window.location.href="/api/projects/"+project.id+"/srt"};'
if new_subtitle not in js:
    if old_subtitle not in js:
        raise SystemExit("Patch anchor not found in static/app.js (addSubtitle)")
    js = js.replace(old_subtitle, new_subtitle, 1)
js = js.replace("AI EDITOR · 0.2.0", "AI EDITOR · 0.2.1")
js_path.write_text(js, encoding="utf-8")

patch("static/index.html", "NEWS STUDIO AI · 0.2.0", "NEWS STUDIO AI · 0.2.1")
patch(
    "NewsStudioAI.spec",
    '''from PyInstaller.utils.hooks import collect_all

datas = [("static", "static"), ("config", "config")]
binaries = []
hiddenimports = []
''',
    '''from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas = [("static", "static"), ("config", "config"), ("README_FA.md", "."), ("docs", "docs")]
binaries = []
hiddenimports = []
# Bundle static Windows FFmpeg binaries when supplied by the build workflow.
for tool in ("ffmpeg.exe", "ffprobe.exe"):
    candidate = Path("vendor") / "ffmpeg" / "bin" / tool
    if candidate.is_file():
        binaries.append((str(candidate), "ffmpeg"))
''',
)
patch(
    "build_windows.bat",
    '''echo EXE created: dist\\NewsStudioAI\\NewsStudioAI.exe
echo To create Setup, install Inno Setup and compile installer\\NewsStudioAI.iss.
''',
    '''echo EXE created: dist\\NewsStudioAI\\NewsStudioAI.exe
if exist "vendor\\ffmpeg\\bin\\ffmpeg.exe" (
  echo FFmpeg is bundled with the application.
) else (
  echo WARNING: FFmpeg is not bundled. Install FFmpeg and add it to PATH on the target PC.
)
echo To create Setup, install Inno Setup and compile installer\\NewsStudioAI.iss.
''',
)
patch("installer/NewsStudioAI.iss", "AppVersion=0.2.0", "AppVersion=0.2.1")
patch("installer/NewsStudioAI.iss", "DefaultDirName={autopf}\\News Studio AI", "DefaultDirName={localappdata}\\Programs\\News Studio AI")
patch("installer/NewsStudioAI.iss", "NewsStudioAI_Setup_0.2.0", "NewsStudioAI_Setup_0.2.1")
patch("README_FA.md", "# News Studio AI — نسخه 0.2.0", "# News Studio AI — نسخه 0.2.1")
patch("docs/FEATURES_FA.md", "نسخه 0.2.0", "نسخه 0.2.1")
patch("docs/TEST_REPORT_FA.md", "گزارش آزمون نسخه 0.2.0", "گزارش آزمون نسخه 0.2.1")

gitignore = ROOT / ".gitignore"
git_text = gitignore.read_text(encoding="utf-8")
for line in (".pytest_cache/", ".coverage", "htmlcov/", "vendor/ffmpeg/"):
    if line not in git_text.splitlines():
        git_text += ("\n" if not git_text.endswith("\n") else "") + line + "\n"
gitignore.write_text(git_text, encoding="utf-8")


readme_path = ROOT / "README_FA.md"
readme_text = readme_path.read_text(encoding="utf-8")
section_start = readme_text.index("## نصب روی Windows")
section_end = readme_text.index("## سخت‌افزار", section_start)
new_install = """## نصب نسخه آماده Windows
1. فایل NewsStudioAI_Setup_0.2.1.exe را از بخش Releases مخزن GitHub دریافت و اجرا کنید.
2. برنامه در پوشه کاربر نصب می‌شود و برای اجرای نسخه آماده به نصب جداگانه Python یا FFmpeg نیاز ندارد.
3. در اولین اجرا حساب مدیر را بسازید.
4. برای نمایش پنجره دسکتاپ، Microsoft Edge WebView2 Runtime لازم است؛ در صورت نبود آن، برنامه مرورگر پیش‌فرض را باز می‌کند.
5. مدل Whisper در اولین استفاده از تشخیص گفتار فارسی دریافت می‌شود و ممکن است به اینترنت نیاز داشته باشد.

## اجرای نسخه سورس روی Windows
1. پوشه NewsStudioAI_v02 را از مخزن دریافت کنید.
2. Python 3.11 x64 را نصب کنید و گزینه Add Python to PATH را فعال کنید.
3. FFmpeg و ffprobe را نصب و پوشه bin را به PATH اضافه کنید؛ یا فایل‌های اجرایی آن‌ها را در vendor/ffmpeg/bin قرار دهید.
4. run_windows.bat را اجرا کنید.
5. مرورگر را در http://127.0.0.1:8765 باز کنید.
6. در اولین اجرا، حساب مدیر بسازید.
7. برای فعال‌سازی تشخیص گفتار فارسی، برنامه را ببندید و install_ai.bat را اجرا کنید.

"""
readme_text = readme_text[:section_start] + new_install + readme_text[section_end:]
readme_text = readme_text.replace(
    "ساخت نهایی EXE ویندوز باید روی خود ویندوز انجام شود؛ در محیط فعلی فقط اسکریپت و تنظیمات ساخت آماده شده‌اند.",
    "ساخت EXE و Setup ویندوز در فرایند CI روی Windows x64 انجام می‌شود. بسته آماده شامل FFmpeg و ffprobe است.",
    1,
)
readme_path.write_text(readme_text, encoding="utf-8")
patch(
    "docs/TEST_REPORT_FA.md",
    "آزمون‌های زیر در محیط لینوکسی ساخت، با FFmpeg و TestClient انجام شدند؛ بنابراین جایگزین آزمون نصب و اجرا روی ویندوز کاربر نیستند.",
    "آزمون‌های خودکار نسخه 0.2.1 با Python، FastAPI TestClient و FFmpeg در محیط لینوکس اجرا شدند. این آزمون‌ها جایگزین آزمون نصب و اجرای نسخه نهایی روی سخت‌افزار واقعی Windows 10/11 نیستند.\\n\\nاجرای مجموعه آزمون: \`python -m pytest -q\` — نتیجه: 3 passed.",
)
patch(
    "docs/TEST_REPORT_FA.md",
    "- دریافت فایل خروجی از API",
    "- دریافت فایل خروجی از API\n- آزمون دسترسی نقش‌ها و جلوگیری از ساخت پروژه توسط بازبین\n- دانلود فایل SRT از API\n- کنترل سلامت آرشیو و استخراج خودکار بسته سورس در GitHub Actions",
)


patch(
    "app.py",
    '''def rtl_text(draw,xy,text,font,fill,anchor="ra"):
    try: draw.text(xy,text,font=font,fill=fill,anchor=anchor,direction="rtl",language="fa")
    except Exception: draw.text(xy,text,font=font,fill=fill,anchor=anchor)
''',
    '''def rtl_text(draw,xy,text,font,fill,anchor="ra"):
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
''',
)
patch(
    "requirements.txt",
    "Pillow>=10.0",
    "Pillow>=10.0\narabic-reshaper>=3.0.0\npython-bidi>=0.6.0",
)
patch(
    "NewsStudioAI.spec",
    '"webview", "clr_loader", "pythonnet")',
    '"webview", "clr_loader", "pythonnet", "arabic_reshaper", "bidi")',
)

print("News Studio AI source patched to 0.2.1")
