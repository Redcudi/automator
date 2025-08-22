
const tabs = document.querySelectorAll('.tab');
const creativeFields = document.getElementById('creativeFields');
const runBtn = document.getElementById('runBtn');
const form = document.getElementById('controlForm');
const cards = document.getElementById('cards');
const statusEl = document.getElementById('jobStatus');

let mode = 'collector';

tabs.forEach(btn=>{
  btn.addEventListener('click', ()=>{
    tabs.forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    mode = btn.dataset.mode;
    creativeFields.classList.toggle('hidden', mode !== 'creative');
    runBtn.textContent = mode === 'creative' ? 'Generar guiones' : 'Analizar perfiles';
  });
});

document.getElementById('clearBtn').addEventListener('click', ()=>{
  form.reset();
  cards.innerHTML = '';
  statusEl.textContent = 'Listo';
});

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
      const res = await fetch('/transcribe', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ url })
      });
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

// Demo de /job/start (cuando conectes scraping)
form.addEventListener('submit', async (e)=>{
  e.preventDefault();
  statusEl.textContent = 'Procesando…';
  cards.innerHTML = '';

  const links = Array.from(document.querySelectorAll('.link')).map(i=>i.value.trim()).filter(Boolean);
  const windowVal = document.getElementById('window').value;
  const numScripts = parseInt(document.getElementById('numScripts').value,10);
  const niche = document.getElementById('niche')?.value?.trim() || '';
  const rules = document.getElementById('rules')?.value?.trim() || '';

  const payload = {
    user_id: 'demo_user',
    mode,
    profiles: links.slice(0,3).map(url => {
      const platform = url.includes('tiktok') ? 'tiktok' : 'instagram';
      return { platform, url };
    }),
    window: windowVal,
    num_scripts: numScripts,
    creative: mode === 'creative' ? { niche_prompt: niche, rules_prompt: rules } : null
  };

  try {
    const res = await fetch('/job/start', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    (data.items || []).forEach(addCard);
    statusEl.textContent = 'Completado';
  } catch (err) {
    console.error(err);
    statusEl.textContent = 'Error';
  }
});

function addCard(item){
  const tpl = document.getElementById('cardTemplate').content.cloneNode(true);
  tpl.querySelector('.v').textContent = item.metrics?.views ?? '-';
  tpl.querySelector('.l').textContent = item.metrics?.likes ?? '-';
  tpl.querySelector('.c').textContent = item.metrics?.comments ?? '-';
  tpl.querySelector('.s').textContent = item.metrics?.score ?? '-';
  tpl.querySelector('.script').textContent = item.script || '';
  tpl.querySelector('.link').href = item.url || '#';
  tpl.querySelector('.copy').addEventListener('click', ()=>{
    navigator.clipboard.writeText(item.script || '');
    alert('Guion copiado');
  });
  cards.appendChild(tpl);
}
