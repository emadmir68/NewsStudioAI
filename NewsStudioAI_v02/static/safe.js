"use strict";
const $ = id => document.getElementById(id);
let project = null;
let script = null;
let poller = null;
let activeJobId = null;
let setupMode = false;

function message(text, good = false) {
  const box = $("alert");
  box.hidden = false;
  box.className = good ? "notice ok" : "notice";
  box.textContent = String(text);
}
function escapeText(text) {
  return String(text ?? "").replace(/[&<>"']/g, char =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}
async function request(path, options = {}) {
  let res;
  try { res = await fetch(path, {credentials:"same-origin",...options}); }
  catch (error) { throw new Error("اتصال به نرم‌افزار قطع شده است؛ برنامه را بررسی کن."); }
  let body = {};
  try { body = await res.json(); } catch {}
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "خطای " + res.status);
  return body;
}
function setStage(number) {
  for (let i=1; i<=5; i++) {
    const n = $("stage"+i);
    n.className = i===number ? "active" : i<number ? "done" : "";
  }
}
async function checkStatus() {
  const [health, engines] = await Promise.all([request("/api/health"),request("/api/animation-ai/status")]);
  const free = Number(health.available_ram_gb || 0);
  $("hardwareState").textContent = "رم آزاد: " + (free ? free.toFixed(1) + " گیگابایت" : "نامشخص") + " | حالت ایمن";
  $("engineState").textContent = engines.vision?.model_ready && engines.tts?.ready ? "هر دو موتور داخلی آماده‌اند" : "فایل‌های یک موتور ناقص‌اند";
  if (!engines.vision?.model_ready) {
    $("engineInfo").textContent = "مدل بینایی در این نصب یافت نشد؛ نصب‌کننده کامل حاوی موتورهای داخلی را نصب کن.";
  } else if (free && free < 5.5) {
    $("engineInfo").textContent = "حافظه آزاد برای پردازش ایمن کافی نیست؛ برنامه‌های اضافی را ببند.";
  } else {
    $("engineInfo").textContent = "موتورهای داخلی آماده‌اند؛ هر بار فقط یک پردازش با CPU محدود اجرا می‌شود.";
  }
  $("analyzeBtn").disabled = !project?.source || !engines.vision?.model_ready || Boolean(free && free < 5.5) || !!activeJobId;
  $("audioBtn").disabled = !(script?.dialogues || []).length || !!activeJobId;
  $("renderBtn").disabled = !(script?.dialogues || []).some(line=>line.audio_file) || !!activeJobId;
}
async function loadProject(id) {
  project = await request("/api/projects/" + encodeURIComponent(id));
  $("projectName").textContent = "پروژه: " + project.title;
  $("videoName").textContent = project.source?.original_name || "هنوز ویدئو بارگذاری نشده است";
  if (project.source) {
    $("videoPreview").src = "/media/" + project.id + "/" + encodeURIComponent(project.source.filename);
    $("videoPreview").hidden = false;
  } else {
    $("videoPreview").hidden = true;
  }
  script = await request("/api/projects/" + project.id + "/animation-dubbing");
  renderScript();
  setStage(script?.dialogues?.length ? (script.dialogues.some(line=>line.audio_file) ? 5 : 3) : project.source ? 2 : 1);
  await checkStatus();
}
function renderScript() {
  const characters = script?.characters || [];
  const lines = script?.dialogues || [];
  $("summary").textContent = script?.summary || "بعد از تحلیل، خلاصه داستان اینجا نمایش داده می‌شود.";
  $("characters").innerHTML = characters.map(c =>
    '<section class="character" data-character="'+escapeText(c.id)+'">'+
    '<strong>'+escapeText(c.name)+'</strong>'+
    '<span class="small muted">'+escapeText(c.voice_profile || "صدای طبیعی")+'</span>'+
    '<span class="small">صدای داخلی فارسی؛ بدون نیاز به فایل مرجع</span>'+
    '</section>').join("");
  $("dialogues").innerHTML = lines.map(line => {
    const opts = characters.map(c=>'<option value="'+escapeText(c.id)+'" '+(c.id===line.character_id ? "selected":"")+'>'+escapeText(c.name)+'</option>').join("");
    return '<div class="dialogue" data-line="'+escapeText(line.id)+'">'+
    '<label>شروع<input class="begin" type="number" min="0" step=".1" value="'+Number(line.start||0)+'"></label>'+
    '<label>پایان<input class="end" type="number" min="0" step=".1" value="'+Number(line.end||0)+'"></label>'+
    '<label class="voice-select">شخصیت<select class="who">'+opts+'</select></label>'+
    '<label class="wide">متن فارسی<textarea class="words">'+escapeText(line.text||"")+'</textarea></label></div>';
  }).join("");
  $("saveScriptBtn").disabled = !lines.length || !!activeJobId;
  $("audioBtn").disabled = !lines.length || !!activeJobId;
  $("renderBtn").disabled = !lines.some(line=>line.audio_file) || !!activeJobId;

}
async function saveScript() {
  if (!script?.dialogues?.length) return;
  const data = {...script,dialogues:[...document.querySelectorAll(".dialogue")].map(el=>{
    const original=script.dialogues.find(x=>x.id===el.dataset.line)||{};
    const changed=el.querySelector(".words").value.trim();
    return {...original,start:Number(el.querySelector(".begin").value),end:Number(el.querySelector(".end").value),
      character_id:el.querySelector(".who").value,text:changed};
  })};
  script=await request("/api/projects/"+project.id+"/animation-dubbing/script",{
    method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)
  });
  renderScript();
}
async function watch(jobId) {
  clearInterval(poller);activeJobId=jobId;
  $("progressBox").hidden=false;
  const refresh=async ()=>{
    try {
      const job=await request("/api/jobs/"+jobId);
      $("progressMessage").textContent=job.message||"در حال پردازش";
      $("percent").textContent=(job.progress||0)+"٪";
      $("progressFill").style.width=(job.progress||0)+"%";
      if (["completed","failed","cancelled"].includes(job.status)) {
        clearInterval(poller);poller=null;activeJobId=null;
        $("progressBox").hidden=true;
        if (job.status==="completed") {
          if (job.result?.url) {
            $("resultLink").href=job.result.url;
            $("resultLink").hidden=false;
          }
          await loadProject(project.id);
          message("مرحله پردازش تمام شد.",true);
        } else {
          message(job.message || "پردازش متوقف شد.");
          await checkStatus();
        }
      }
    } catch(e) {clearInterval(poller);poller=null;activeJobId=null;message(e.message);}
  };
  await refresh();
  if(activeJobId)poller=setInterval(refresh,1500);
}
async function startJob(url){
  if(activeJobId)return message("کار قبلی هنوز تمام نشده است.");
  try {
    const res=await request(url,{method:"POST"});
    await watch(res.job_id);
  }catch(e){message(e.message);}
}
async function authenticate() {
  const status=await request("/api/auth/status");
  if(status.authenticated){$("authBox").hidden=true;$("mainBox").hidden=false;await initializeEditor();return;}
  setupMode=!!status.setup_required;
  $("authHeading").textContent=setupMode?"ساخت حساب مدیر":"ورود به حساب";
  $("authBox").hidden=false;$("mainBox").hidden=true;
}
async function initializeEditor() {
  const projects=await request("/api/projects");
  if(projects.length)await loadProject(projects[0].id);
  else await checkStatus();
}
$("authForm").addEventListener("submit",async(e)=>{
  e.preventDefault();
  const url=setupMode?"/api/auth/setup":"/api/auth/login";
  try{
    await request(url,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username:$("username").value,password:$("password").value})});
    $("authError").hidden=true;await authenticate();
  }catch(err){$("authError").hidden=false;$("authError").textContent=err.message;}
});
$("freshProject").addEventListener("click",async()=>{
  try {
    if(activeJobId)return message("ابتدا پردازش جاری را متوقف کن.");
    project=null;script=null;
    $("videoInput").value="";$("videoPreview").hidden=true;$("videoPreview").removeAttribute("src");
    $("videoName").textContent="هنوز فایلی انتخاب نشده است";
    $("projectName").textContent="";$("resultLink").hidden=true;
    renderScript();setStage(1);await checkStatus();
  }catch(e){message(e.message);}
});
$("videoInput").addEventListener("change",async()=>{
  const file=$("videoInput").files?.[0];
  if(!file)return;
  try {
    if(activeJobId)return message("تا پایان پردازش قبلی امکان تعویض ویدئو نیست.");
    if (!project) project=await request("/api/projects",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({title:file.name.replace(/\.[^.]+$/,"").slice(0,100)||"انیمیشن جدید"})});
    const form=new FormData();form.append("file",file);
    project=await request("/api/projects/"+project.id+"/upload",{method:"POST",body:form});
    await loadProject(project.id);message("ویدئو دریافت شد.",true);
  }catch(e){message(e.message);}
});
$("analyzeBtn").addEventListener("click",()=>project && startJob("/api/projects/"+project.id+"/animation-dubbing/analyze"));
$("saveScriptBtn").addEventListener("click",async()=>{try{await saveScript();message("تغییرات ذخیره شد.",true);}catch(e){message(e.message);}});
$("audioBtn").addEventListener("click",async()=>{
  try{await saveScript();await startJob("/api/projects/"+project.id+"/animation-dubbing/generate-audio");}catch(e){message(e.message);}
});
$("renderBtn").addEventListener("click",()=>project&&startJob(
 "/api/projects/"+project.id+"/animation-dubbing/render?keep_original_audio="+$("originalSound").checked));
$("cancelBtn").addEventListener("click",async()=>{
 if(!activeJobId)return;
 try {
  await request("/api/jobs/"+activeJobId+"/cancel",{method:"POST"});
  $("progressMessage").textContent="درخواست توقف ثبت شد؛ ممکن است مرحله فعلی هنوز ادامه داشته باشد.";
 }catch(e){message(e.message);}
});
authenticate().catch(e=>message(e.message));
