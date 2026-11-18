let animationDubbing = null;

function renderAnimationDubbing() {
  const d = animationDubbing || {};
  const chars = d.characters || [];
  const lines = d.dialogues || [];
  const summary = $("animationSummary");
  summary.hidden = !d.summary;
  summary.innerHTML = d.summary
    ? "<b>" + esc(d.title || "خلاصه داستان") + "</b><br>" + esc(d.summary) +
      "<br><small>صحنه‌ها: " + ((d.scenes || []).length) + " · شخصیت‌ها: " + chars.length + " · دیالوگ‌ها: " + lines.length + (d.source_language ? " · زبان گفتار اصلی: " + esc(d.source_language) : "") + " · بخش‌های گفتار تشخیص‌داده‌شده: " + ((d.source_transcript || []).length) + "</small>"
    : "";

  $("animationCharacters").innerHTML = chars.map(ch => {
    const safe = String(ch.id).replace(/[^a-zA-Z0-9_-]/g, "_");
    return '<div class="animation-character"><strong>' + esc(ch.name) + '</strong>' +
      '<p>' + esc(ch.appearance || "توصیف ظاهری ثبت نشده است") + '</p>' +
      '<p>پیشنهاد صدا: ' + esc(ch.voice_profile || "طبیعی و محاوره‌ای") + '</p>' +
      '<span class="voice-state">' + (ch.voice_reference ? "✓ نمونه صدا بارگذاری شده" : "نیازمند نمونه صدای مرجع") + '</span>' +
      '<input class="voice-ref-file" data-char="' + esc(ch.id) + '" id="voiceRef_' + safe + '" type="file" accept="audio/*">' +
      '<button class="btn secondary upload-voice-ref" data-char="' + esc(ch.id) + '">بارگذاری نمونه صدا</button></div>';
  }).join("") || '<div class="muted-note">پس از تحلیل ویدئو، شخصیت‌ها اینجا نمایش داده می‌شوند.</div>';

  $("animationDialogueRows").innerHTML = lines.map(line => {
    const options = chars.map(ch =>
      '<option value="' + esc(ch.id) + '"' + (ch.id === line.character_id ? " selected" : "") + '>' + esc(ch.name) + '</option>'
    ).join("");
    return '<tr class="dub-line" data-id="' + esc(line.id) + '">' +
      '<td><input class="dub-start" type="number" min="0" step=".1" value="' + (Number(line.start) || 0) + '"></td>' +
      '<td><input class="dub-end" type="number" min="0" step=".1" value="' + (Number(line.end) || 0) + '"></td>' +
      '<td><select class="dub-speaker">' + options + '</select></td>' +
      '<td><input class="dub-emotion" value="' + esc(line.emotion || "طبیعی") + '"></td>' +
      '<td><input class="dub-text" value="' + esc(line.text || "") + '"></td></tr>';
  }).join("") || '<tr><td colspan="5" class="empty">هنوز فیلمنامه‌ای ساخته نشده است.</td></tr>';

  const hasScript = lines.length > 0;
  $("saveAnimationScript").disabled = !hasScript;
  $("generateAnimationAudio").disabled = !hasScript;
  $("renderAnimationDub").disabled = !lines.some(x => x.audio_file);

  document.querySelectorAll(".upload-voice-ref").forEach(button => {
    button.onclick = () => {
      const safe = String(button.dataset.char).replace(/[^a-zA-Z0-9_-]/g, "_");
      $("voiceRef_" + safe).click();
    };
  });
  document.querySelectorAll(".voice-ref-file").forEach(input => {
    input.onchange = async event => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      try {
        const form = new FormData();
        form.append("file", file);
        await api("/api/projects/" + project.id + "/animation-dubbing/voice/" + encodeURIComponent(input.dataset.char), {
          method: "POST", body: form
        });
        await loadAnimationDubbing();
        toast("نمونه صدای شخصیت ثبت شد");
      } catch (error) {
        toast(error.message);
      }
      event.target.value = "";
    };
  });
}

async function loadAnimationDubbing() {
  if (!project) return;
  try {
    const results = await Promise.all([
      api("/api/animation-ai/status"),
      api("/api/projects/" + project.id + "/animation-dubbing")
    ]);
    const status = results[0];
    animationDubbing = results[1];
    const vision = status.vision || {};
    const tts = status.tts || {};
    const perf = status.performance || {};
    const profileNode = $("hardwareProfile");
    if (profileNode) profileNode.textContent = perf.label_fa ? "پروفایل فعال: " + perf.label_fa + " | رم شناسایی‌شده: " + perf.installed_ram_gb + " GB | هسته‌های منطقی: " + perf.logical_cpus + " | Whisper: " + perf.whisper_model + " / int8 / CPU | فریم‌ها: " + perf.frames + " | رندر: " + perf.render_threads + " رشته" : "پروفایل سخت‌افزاری هنوز مشخص نشده است.";
    $("visionAIStatus").textContent = vision.model_ready ? "آماده · " + vision.model : (vision.available ? "Ollama فعال؛ مدل نصب نیست" : "Ollama اجرا نیست");
    $("visionAIStatus").style.color = vision.model_ready ? "#6ed4ac" : "#e6b76c";
    $("ttsAIStatus").textContent = tts.ready ? "آماده · صدای فارسی" : (tts.available ? "در حال آماده‌سازی" : "خاموش؛ هنگام تولید روشن می‌شود");
    $("ttsAIStatus").style.color = tts.ready ? "#6ed4ac" : "#e6b76c";
    $("animationAIHelp").textContent = "تحلیل تصویر: " + (vision.message || "—") + " | تولید صدا: " + (tts.message || "—") + " موتور صدای فارسی هنگام شروع تولید صدا به‌صورت خودکار روشن می‌شود.";
    $("analyzeAnimation").disabled = !project.source || !vision.model_ready;
    $("generateAnimationAudio").disabled = !(animationDubbing.dialogues || []).length || !tts.ready;
    renderAnimationDubbing();
  } catch (error) {
    $("animationAIHelp").textContent = error.message;
  }
}

$("checkAnimationAI").onclick = () => loadAnimationDubbing().then(() => toast("وضعیت موتورهای هوشمند به‌روزرسانی شد"));
$("analyzeAnimation").onclick = async () => {
  if (!project || !project.source) return toast("ابتدا انیمیشن را وارد کنید");
  try {
    await save(false);
    const result = await api("/api/projects/" + project.id + "/animation-dubbing/analyze", { method: "POST" });
    poll(result.job_id);
  } catch (error) {
    toast(error.message);
  }
};
$("saveAnimationScript").onclick = async () => {
  try {
    const dialogues = Array.from(document.querySelectorAll(".dub-line")).map(row => ({
      id: row.dataset.id,
      start: Number(row.querySelector(".dub-start").value),
      end: Number(row.querySelector(".dub-end").value),
      character_id: row.querySelector(".dub-speaker").value,
      emotion: row.querySelector(".dub-emotion").value,
      text: row.querySelector(".dub-text").value
    }));
    const payload = Object.assign({}, animationDubbing, { dialogues: dialogues });
    animationDubbing = await api("/api/projects/" + project.id + "/animation-dubbing/script", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    renderAnimationDubbing();
    toast("فیلمنامه ذخیره شد");
  } catch (error) {
    toast(error.message);
  }
};
$("generateAnimationAudio").onclick = async () => {
  try {
    await $("saveAnimationScript").onclick();
    const result = await api("/api/projects/" + project.id + "/animation-dubbing/generate-audio", { method: "POST" });
    poll(result.job_id);
  } catch (error) {
    toast(error.message);
  }
};
$("renderAnimationDub").onclick = async () => {
  try {
    const result = await api("/api/projects/" + project.id + "/animation-dubbing/render?keep_original_audio=" + $("keepOriginalDubAudio").checked, { method: "POST" });
    poll(result.job_id);
  } catch (error) {
    toast(error.message);
  }
};
