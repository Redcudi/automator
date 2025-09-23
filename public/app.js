// ----- Consentimiento legal -----
// Configuración del consentimiento
const CONSENT_VERSION = "2024-06-11"; // Cambia si el texto cambia
const CONSENT_KEY = "consent_accepted_" + CONSENT_VERSION;
const USER_ID = "demo_user"; // O actualiza según lógica real

function showConsentModalIfNeeded() {
  if (sessionStorage.getItem(CONSENT_KEY)) return;
  // Modal HTML
  let modal = document.getElementById("consentModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "consentModal";
    modal.style.position = "fixed";
    modal.style.top = "0";
    modal.style.left = "0";
    modal.style.width = "100vw";
    modal.style.height = "100vh";
    modal.style.background = "rgba(0,0,0,0.45)";
    modal.style.zIndex = "9999";
    modal.style.display = "flex";
    modal.style.alignItems = "center";
    modal.style.justifyContent = "center";
    modal.innerHTML = `
      <div style="background:#fff;max-width:430px;padding:28px 26px;border-radius:16px;box-shadow:0 4px 24px #0002;">
        <h2 style="margin-top:0">Consentimiento legal</h2>
        <div style="max-height:260px;overflow:auto;font-size:14px;margin-bottom:16px;">
          <p>
            Al continuar, aceptas que los datos proporcionados serán procesados para la generación de guiones y análisis de perfiles. La información puede ser almacenada temporalmente para mejorar el servicio. No compartiremos tus datos con terceros fuera de lo estrictamente necesario para el funcionamiento de la plataforma.
          </p>
          <p>
            Para más detalles, consulta nuestra <a href="#" target="_blank">Política de Privacidad</a>.
          </p>
        </div>
        <label style="display:flex;align-items:center;margin-bottom:14px;">
          <input type="checkbox" id="consentCheckbox" style="margin-right:8px;">
          He leído y acepto el tratamiento de datos.
        </label>
        <div style="text-align:right">
          <button id="consentAcceptBtn" disabled style="padding:8px 18px;font-size:15px;border-radius:7px;background:#1976d2;color:#fff;border:none;cursor:pointer;">Acepto</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  // Lógica de habilitar botón solo si checkbox está marcado
  const cb = modal.querySelector("#consentCheckbox");
  const acceptBtn = modal.querySelector("#consentAcceptBtn");
  cb.addEventListener("change", () => {
    acceptBtn.disabled = !cb.checked;
  });
  acceptBtn.addEventListener("click", async () => {
    // Registrar consentimiento
    try {
      sessionStorage.setItem(CONSENT_KEY, "1");
      // Enviar log a backend
      await fetch(`${API_BASE}/consent/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: USER_ID,
          version: CONSENT_VERSION,
          timestamp: new Date().toISOString()
        })
      });
    } catch (e) {
      // Ignorar error
    }
    modal.remove();
  });
}

// Interceptar submit para mostrar consentimiento si no se aceptó (único y después de declarar `form`)
if (!window._consentSubmitHooked) {
  window._consentSubmitHooked = true;
  if (form) {
    form.addEventListener("submit", function(e) {
      if (!sessionStorage.getItem(CONSENT_KEY)) {
        e.preventDefault();
        showConsentModalIfNeeded();
        return false;
      }
    });
  }
}
// public/app.js
const tabs = document.querySelectorAll('.tab');
const creativeFields = document.getElementById('creativeFields');
const runBtn = document.getElementById('runBtn');
const form = document.getElementById('controlForm');
const cards = document.getElementById('cards');
const statusEl = document.getElementById('jobStatus');
const progressFill = document.getElementById('progressFill');
const progressLabel = document.getElementById('progressLabel');
const progressStepsEl = document.getElementById('progressSteps');

// --- API base (supports WordPress embed) ---
const API_BASE = (window.CREATORHOOP_API && window.CREATORHOOP_API.replace(/\/$/, '')) || window.location.origin;

let mode = 'collector';
window.currentMode = mode;

// --- Creative mode controls ---
const adaptationLevelEl = document.getElementById('adaptationLevel');
const rulesSourceRow = document.getElementById('rulesSourceRow');
const rulesSourceEl = document.getElementById('rulesSource');
const customRulesEl = document.getElementById('customRules');

function getCheckedValue(container, inputName){
  const el = container?.querySelector(`input[name="${inputName}"]:checked`);
  return el ? el.value : null;
}

function updateCreativeUI(){
  const level = getCheckedValue(adaptationLevelEl, 'adaptation') || 'simple';
  if (rulesSourceRow) rulesSourceRow.classList.toggle('hidden', level !== 'completa');
  const src = getCheckedValue(rulesSourceEl, 'rulesSrc') || 'guideon';
  if (level === 'completa'){
    if (customRulesEl) customRulesEl.classList.toggle('hidden', src !== 'custom');
  } else {
    if (customRulesEl) customRulesEl.classList.add('hidden');
  }
}

tabs.forEach(btn=>{
  btn.addEventListener('click', ()=>{
    tabs.forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    mode = btn.dataset.mode;
    window.currentMode = mode;
    creativeFields.classList.toggle('hidden', mode !== 'creative');
    runBtn.textContent = mode === 'creative' ? 'Generar guiones' : 'Analizar perfiles';
    updateCreativeUI();
  });
});

document.getElementById('clearBtn').addEventListener('click', ()=>{
  form.reset();
  cards.innerHTML = '';
  statusEl.textContent = 'Listo';
  updateCreativeUI();
});

// ------ Progress helpers ------
let progressTimer = null;
let currentSteps = [];
let currentStepIdx = 0;

function resetProgress() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  currentSteps = [];
  currentStepIdx = 0;
  if (progressFill) progressFill.style.width = '0%';
  if (progressLabel) progressLabel.textContent = 'Listo';
  if (progressStepsEl) progressStepsEl.innerHTML = '';
}

function setSteps(steps) {
  currentSteps = steps || [];
  if (!progressStepsEl) return;
  progressStepsEl.innerHTML = '';
  currentSteps.forEach((s, i) => {
    const li = document.createElement('li');
    li.textContent = s;
    if (i === 0) li.classList.add('active');
    progressStepsEl.appendChild(li);
  });
  if (progressLabel) progressLabel.textContent = currentSteps[0] || 'Procesando…';
  if (progressFill) progressFill.style.width = '5%';
  currentStepIdx = 0;
}

function advanceStep() {
  if (!currentSteps.length) return;
  const items = Array.from(progressStepsEl.querySelectorAll('li'));
  const lastWorkingIdx = Math.max(0, currentSteps.length - 2);
  if (currentStepIdx >= lastWorkingIdx) {
    if (progressFill) progressFill.style.width = '92%';
    return;
  }
  if (items[currentStepIdx]) items[currentStepIdx].classList.remove('active');
  currentStepIdx = Math.min(currentStepIdx + 1, lastWorkingIdx);
  if (items[currentStepIdx]) items[currentStepIdx].classList.add('active');
  const pct = Math.round(((currentStepIdx + 1) / (currentSteps.length)) * 90);
  if (progressFill) progressFill.style.width = `${Math.min(pct, 92)}%`;
  if (progressLabel) progressLabel.textContent = currentSteps[currentStepIdx] || 'Procesando…';
}

function completeProgress() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  const items = Array.from(progressStepsEl.querySelectorAll('li'));
  if (items.length) {
    items.forEach(li => li.classList.remove('active'));
    items[items.length - 1].classList.add('active');
  }
  if (progressFill) progressFill.style.width = '100%';
  if (progressLabel) progressLabel.textContent = 'Completado';
}

// React to changes in creative segmented controls
adaptationLevelEl?.addEventListener('change', updateCreativeUI);
rulesSourceEl?.addEventListener('change', updateCreativeUI);

// Transcripción de un link
const singleBtn = document.getElementById('singleBtn');
const singleUrl = document.getElementById('singleUrl');
if (singleBtn){
  singleBtn.addEventListener('click', async ()=>{
    const url = (singleUrl?.value || '').trim();
    if (!url) { alert('Pega un link de video'); return; }
    statusEl.textContent = 'Transcribiendo…';
    cards.innerHTML = '';
    try{
      const res = await fetch(`${API_BASE}/transcribe`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ url })
      });
      if(!res.ok){
        const err = await res.json().catch(()=>({}));
        throw new Error(err.detail || err.error || ('HTTP '+res.status));
      }
      const data = await res.json();
      (data.items || []).forEach(addCard);
      statusEl.textContent = 'Completado';
    }catch(err){
      console.error(err);
      statusEl.textContent = 'Error';
      alert('No se pudo transcribir este link.');
    }
  });
}

// Submit principal
form.addEventListener('submit', async (e)=>{
  // Consentimiento ya se verifica en submit (ver arriba)
  e.preventDefault();
  statusEl.textContent = 'Procesando…';
  cards.innerHTML = '';

  const links = Array.from(document.querySelectorAll('.link')).map(i=>i.value.trim()).filter(Boolean);
  if (links.length < 1) {
    alert('Agrega al menos 1 perfil (Instagram o TikTok).');
    return;
  }
  const windowVal = document.getElementById('window').value;
  const numScripts = parseInt(document.getElementById('numScripts').value,10);
  const sortBy = document.getElementById('sortBy')?.value || 'score';
  const sortOrder = document.getElementById('sortOrder')?.value || 'desc';
  const niche = document.getElementById('niche')?.value?.trim() || '';
  const rules = ''; // sin campo de reglas/tono en UI

  // Progreso
  resetProgress();
  const steps = (mode === 'creative')
    ? ['Recolectando publicaciones…','Rankeando…','Transcribiendo…','Adaptando…','Listo']
    : ['Recolectando publicaciones…','Rankeando…','Transcribiendo…','Listo'];
  setSteps(steps);
  progressTimer = setInterval(advanceStep, 1200);

  const adaptationLevel = getCheckedValue(adaptationLevelEl, 'adaptation') || 'simple';
  const rulesSource = getCheckedValue(rulesSourceEl, 'rulesSrc') || 'guideon';
  const customRules = (customRulesEl?.value || '').trim();

  const payload = {
    user_id: USER_ID,
    mode,
    profiles: links.slice(0,3).map(url => {
      const platform = url.includes('tiktok') ? 'tiktok' : 'instagram';
      return { platform, url };
    }),
    window: windowVal,
    num_scripts: numScripts,
    sort_by: sortBy,
    order: sortOrder,
    creative: mode === 'creative' ? {
      niche_prompt: niche,
      rules_prompt: rules,
      adaptation_level: adaptationLevel,              // 'simple' | 'completa'
      rules_source: adaptationLevel === 'completa' ? rulesSource : 'guideon',
      custom_rules: (adaptationLevel === 'completa' && rulesSource === 'custom') ? customRules : '',
      lang: 'es'
    } : null
  };

  try {
    const res = await fetch(`${API_BASE}/job/start`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if(!res.ok){
      const err = await res.json().catch(()=>({}));
      throw new Error(err.detail || err.error || ('HTTP '+res.status));
    }
    const data = await res.json();
    if(data.error && !data.items){
      throw new Error(data.hint || data.detail || data.error);
    }
    (data.items || []).forEach(addCard);
    completeProgress();
    statusEl.textContent = 'Completado';
  } catch (err) {
    console.error(err);
    resetProgress();
    if (progressLabel) progressLabel.textContent = 'Error';
    statusEl.textContent = 'Error';
    alert('Error procesando: '+ (err?.message || 'desconocido'));
  }
});

// ---------- Cards con historial de versiones + “mini chat” ----------
function addCard(item){
  const fragment = document.getElementById('cardTemplate').content.cloneNode(true);
  const cardEl = fragment.querySelector('.card');

  // Métricas y link
  cardEl.querySelector('.v').textContent = item.metrics?.views ?? '-';
  cardEl.querySelector('.l').textContent = item.metrics?.likes ?? '-';
  cardEl.querySelector('.c').textContent = item.metrics?.comments ?? '-';
  cardEl.querySelector('.s').textContent = item.metrics?.score ?? '-';
  cardEl.querySelector('.link').href = item.url || '#';

  // Estado de versiones de esta card
  const scriptEl = cardEl.querySelector('.script');
  const revPrev = cardEl.querySelector('.rev-prev');
  const revNext = cardEl.querySelector('.rev-next');
  const revIndicator = cardEl.querySelector('.rev-indicator');

  const revisions = [{
    text: item.script || '',
    meta: { label: 'Original', ts: Date.now() }
  }];
  let revIdx = 0;

  function renderRevision() {
    const cur = revisions[revIdx] || { text: '' };
    scriptEl.textContent = cur.text || '';
    if (revIndicator) revIndicator.textContent = `${revIdx + 1}/${revisions.length}`;
    if (revPrev) revPrev.disabled = (revIdx === 0);
    if (revNext) revNext.disabled = (revIdx === revisions.length - 1);
  }
  renderRevision();

  revPrev?.addEventListener('click', () => {
    if (revIdx > 0) { revIdx -= 1; renderRevision(); }
  });
  revNext?.addEventListener('click', () => {
    if (revIdx < revisions.length - 1) { revIdx += 1; renderRevision(); }
  });

  // Copiar versión visible
  cardEl.querySelector('.copy').addEventListener('click', ()=>{
    const cur = revisions[revIdx]?.text || '';
    navigator.clipboard.writeText(cur);
    alert('Guion copiado');
  });

  // Añade la card al DOM
  cards.appendChild(fragment);

  // Mini chat (refinar)
  const refineInput = cardEl.querySelector('.refine-input');
  const refineBtn = cardEl.querySelector('.refine-send');
  const refineLog = cardEl.querySelector('.refine-log');

  function appendLog(role, text){
    const div = document.createElement('div');
    div.className = 'refine-msg ' + role;
    div.textContent = text;
    refineLog.appendChild(div);
    refineLog.scrollTop = refineLog.scrollHeight;
  }

  refineBtn.addEventListener('click', async ()=>{
    const prompt = (refineInput.value || '').trim();
    if(!prompt){ alert('Escribe qué cambio quieres.'); return; }
    refineBtn.disabled = true;
    appendLog('user', prompt);
    try{
      // toma la versión visible como base
      const baseScript = revisions[revIdx]?.text || '';

      const level = getCheckedValue(document.getElementById('adaptationLevel'), 'adaptation') || 'simple';
      const rulesSrc = getCheckedValue(document.getElementById('rulesSource'), 'rulesSrc') || 'guideon';
      const custom = (document.getElementById('customRules')?.value || '').trim();
      const niche = (document.getElementById('niche')?.value || '').trim();

      const res = await fetch(`${API_BASE}/guideon/rewrite`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          script: baseScript,
          user_prompt: prompt,
          mode: window.currentMode || 'collector',
          niche_prompt: niche,
          adaptation_level: level,
          rules_source: level === 'completa' ? rulesSrc : 'guideon',
          custom_rules: (level === 'completa' && rulesSrc === 'custom') ? custom : '',
          lang: 'es'
        })
      });
      if(!res.ok){
        const err = await res.json().catch(()=>({}));
        throw new Error(err.detail || ('HTTP '+res.status));
      }
      const data = await res.json();
      const newScript = (() => {
        if ((Array.isArray(data.hooks) && data.hooks.length) || data.cta){
          const header = [];
          if (Array.isArray(data.hooks) && data.hooks.length){
            header.push('[HOOKS]\n- ' + data.hooks.map(h=>String(h)).join('\n- '));
          }
          if (data.cta){
            header.push('\n[CTA]\n' + String(data.cta));
          }
          return (header.join('\n') + (header.length? '\n\n[GUION]\n' : '') + (data.script || '')).trim();
        }
        return data.script || '';
      })();

      // Guardar como nueva versión y mostrarla
      const label = (prompt.length > 28 ? prompt.slice(0,28) + '…' : prompt) || 'Edición';
      revisions.push({ text: newScript, meta: { label, ts: Date.now() } });
      revIdx = revisions.length - 1;
      renderRevision();

      appendLog('assistant', `✅ Nueva versión guardada (${revIdx + 1}/${revisions.length}).`);
      refineInput.value = '';
    }catch(err){
      console.error(err);
      appendLog('assistant', '⚠️ Error: ' + (err?.message || 'desconocido'));
    }finally{
      refineBtn.disabled = false;
    }
  });
}

updateCreativeUI();

// Mostrar consentimiento al cargar la página si no se aceptó aún
showConsentModalIfNeeded();