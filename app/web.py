"""The upload UI served at `/`.

A single self-contained HTML page (no build step, no framework): pick one or more PDF
invoices, each is POSTed to /api/extract, and the page shows the **async job lifecycle** —
the job id returned instantly (HTTP 202), the status moving PENDING -> RUNNING -> SUCCEEDED,
and finally the extracted invoice. Kept as one string so the service stays a single
deployable unit. The app runs behind Databricks OAuth, so same-origin fetches carry the
session automatically.
"""

UPLOAD_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Invoice Extraction</title>
<style>
  :root {
    --bg:#0b0e14; --bg2:#0f141c; --card:#141a23; --line:#252d3a; --line2:#323c4d;
    --mut:#8b97a8; --txt:#e6edf3; --acc:#3b82f6; --acc2:#2563eb;
    --ok:#3fb950; --okbg:rgba(63,185,80,.14); --err:#f85149; --errbg:rgba(248,81,73,.14);
    --run:#3b82f6; --runbg:rgba(59,130,246,.14); --pend:#a371f7; --pendbg:rgba(163,113,247,.14);
  }
  * { box-sizing:border-box; }
  body { margin:0; background:radial-gradient(1200px 600px at 50% -10%, #131a26 0%, var(--bg) 55%);
         color:var(--txt); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         line-height:1.5; min-height:100vh; }
  .wrap { max-width:780px; margin:0 auto; padding:56px 20px 100px; }
  .head { display:flex; align-items:center; gap:13px; margin-bottom:6px; }
  .logo { width:38px; height:38px; border-radius:9px; background:linear-gradient(135deg,var(--acc),#7c3aed);
          display:grid; place-items:center; font-size:20px; }
  h1 { font-size:23px; margin:0; letter-spacing:-.2px; }
  .sub { color:var(--mut); font-size:14px; margin:0 0 30px; }
  .sub code { background:var(--bg2); border:1px solid var(--line); border-radius:5px; padding:1px 6px;
              font-size:12.5px; color:var(--txt); }

  .drop { display:block; width:100%; border:1.5px dashed var(--line2); border-radius:14px;
          padding:40px 24px; text-align:center; background:linear-gradient(180deg,var(--card),var(--bg2));
          cursor:pointer; transition:border-color .15s, background .15s; }
  .drop:hover, .drop.hl { border-color:var(--acc); background:linear-gradient(180deg,#16202e,var(--bg2)); }
  .drop input { display:none; }
  .drop .ic { font-size:30px; opacity:.8; }
  .pick { display:inline-block; margin-top:12px; background:var(--acc); color:#fff; padding:10px 22px;
          border-radius:8px; font-weight:600; font-size:14px; box-shadow:0 2px 12px rgba(59,130,246,.35); }
  .drop:hover .pick { background:var(--acc2); }
  .hint { color:var(--mut); font-size:13px; margin-top:14px; }

  .cards { margin-top:22px; display:flex; flex-direction:column; gap:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden;
          animation:rise .25s ease; }
  @keyframes rise { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
  .top { display:flex; align-items:center; gap:12px; padding:14px 16px; }
  .fic { font-size:18px; }
  .fname { font-weight:600; font-size:14.5px; word-break:break-all; flex:1; }
  .pill { font-size:11px; font-weight:700; padding:4px 11px; border-radius:20px; white-space:nowrap;
          display:flex; align-items:center; gap:6px; letter-spacing:.3px; }
  .pill .dot { width:7px; height:7px; border-radius:50%; background:currentColor; }
  .pill.live .dot { animation:pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.35;} }
  .PENDING { background:var(--pendbg); color:var(--pend); }
  .RUNNING { background:var(--runbg); color:var(--run); }
  .SUCCEEDED { background:var(--okbg); color:var(--ok); }
  .FAILED { background:var(--errbg); color:var(--err); }

  .meta { display:flex; gap:16px; flex-wrap:wrap; padding:0 16px 12px; font-size:12px; color:var(--mut); }
  .meta b { color:var(--txt); font-weight:600; }
  .jobid { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }

  .steps { display:flex; gap:0; padding:0 16px 14px; }
  .step { flex:1; display:flex; flex-direction:column; gap:6px; }
  .step .bar { height:3px; border-radius:3px; background:var(--line); transition:background .3s; }
  .step.on .bar { background:var(--acc); }
  .step.ok .bar { background:var(--ok); }
  .step .lbl { font-size:11px; color:var(--mut); }
  .step.on .lbl, .step.ok .lbl { color:var(--txt); }

  .trail { padding:0 16px 14px; }
  .trail .th { font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.5px; margin-bottom:8px; }
  .ev { display:flex; gap:10px; padding:2px 0; }
  .ev .stg { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; font-weight:700;
             color:var(--acc); min-width:92px; }
  .ev.done .stg { color:var(--ok); }
  .ev .det { font-size:12.5px; color:var(--mut); word-break:break-word; }
  .ev .det b { color:var(--txt); font-weight:500; }
  .saved { margin-top:10px; padding:9px 11px; background:var(--bg2); border:1px solid var(--line);
           border-radius:8px; font-size:11.5px; color:var(--mut); }
  .saved .sk { color:var(--txt); font-weight:600; }
  .saved code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:#9fb4d0; }

  .body { border-top:1px solid var(--line); padding:14px 16px; }
  table { width:100%; border-collapse:collapse; font-size:13.5px; }
  td { padding:6px 4px; border-top:1px solid var(--line); vertical-align:top; }
  tr:first-child td { border-top:0; }
  td.k { color:var(--mut); width:120px; white-space:nowrap; }
  td.v { font-weight:500; }
  .total td.v { color:var(--ok); font-weight:700; font-size:15px; }
  .items { margin-top:12px; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  .items .ih { font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.5px;
               padding:7px 12px; background:var(--bg2); }
  .items .it { display:flex; justify-content:space-between; gap:12px; padding:7px 12px;
               border-top:1px solid var(--line); font-size:13px; }
  .items .it span:last-child { color:var(--mut); white-space:nowrap; }
  .prov { margin-top:12px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px;
          color:var(--mut); word-break:break-all; }
  .err { color:var(--err); font-size:13px; padding:0 16px 14px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div class="logo">📄</div>
    <h1>Invoice Extraction</h1>
  </div>
  <p class="sub">Upload PDF invoices. Each returns a job id instantly (<code>202</code>), processes on a
    background worker, and is stored to Unity Catalog with an audit trail. One PDF = one invoice.</p>

  <label class="drop" id="drop">
    <input type="file" id="file" accept="application/pdf" multiple />
    <div class="ic">⬆️</div>
    <div><span class="pick">Choose PDF(s)</span></div>
    <div class="hint">or drag &amp; drop here</div>
  </label>

  <div class="cards" id="cards"></div>
</div>

<script>
const cards = document.getElementById('cards');
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const STEPS = ['Submitted', 'Reading', 'Extracting', 'Stored'];

fileInput.onchange = e => { handle(e.target.files); fileInput.value = ''; };
['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('hl'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('hl'); }));
drop.addEventListener('drop', e => handle(e.dataTransfer.files));

function handle(files) {
  for (const f of files) if (f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')) submit(f);
}

function stepHTML(active) {
  return STEPS.map((s, i) => {
    const cls = i < active ? 'ok' : (i === active ? 'on' : '');
    return `<div class="step ${cls}"><div class="bar"></div><div class="lbl">${s}</div></div>`;
  }).join('');
}

function card(name) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = `
    <div class="top">
      <span class="fic">📄</span>
      <span class="fname">${esc(name)}</span>
      <span class="pill PENDING live"><span class="dot"></span>SUBMITTING</span>
    </div>
    <div class="meta"><span>job <b class="jobid">—</b></span><span>elapsed <b class="el">0.0s</b></span></div>
    <div class="steps">${stepHTML(0)}</div>
    <div class="trail"></div>`;
  cards.prepend(el);
  return el;
}

function renderAudit(el, audit) {
  const events = audit.events || [];
  if (!events.length) return;
  const done = s => ['SUCCEEDED','STORED','READ'].includes(s);
  let html = '<div class="th">Audit trail</div>';
  html += events.map(e =>
    `<div class="ev ${done(e.stage)?'done':''}"><span class="stg">${esc(e.stage)}</span>` +
    `<span class="det">${esc(e.detail)}</span></div>`).join('');
  const s = audit.stored_in || {};
  html += `<div class="saved"><span class="sk">Saved to Unity Catalog</span><br>` +
          `Delta: <code>${esc(s.jobs_table||'')}</code> · <code>${esc(s.audit_table||'')}</code><br>` +
          `Volume: <code>${esc(s.volume||'')}</code></div>`;
  el.querySelector('.trail').innerHTML = html;
}

function setStatus(el, status, live) {
  const pill = el.querySelector('.pill');
  pill.className = 'pill ' + status + (live ? ' live' : '');
  pill.innerHTML = (live ? '<span class="dot"></span>' : '') + status;
}

async function submit(file) {
  // Ingestion splits a multi-invoice PDF into one job per invoice (one doc = one invoice).
  let resp;
  try {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/ingest', { method:'POST', body:fd });
    if (!r.ok) throw new Error('ingest failed: HTTP ' + r.status);
    resp = await r.json();
  } catch (e) {
    const el = card(file.name); setStatus(el, 'FAILED', false);
    el.insertAdjacentHTML('beforeend', `<div class="err">${esc(e.message)}</div>`);
    return;
  }
  if (resp.invoices > 1) {
    const note = document.createElement('div');
    note.className = 'note';
    note.innerHTML = `Split <b>${esc(resp.document)}</b> into <b>${resp.invoices}</b> invoices → ${resp.invoices} jobs`;
    cards.prepend(note);
  }
  resp.jobs.forEach(j => track(j, resp.document, resp.invoices));
}

function track(j, docName, total) {
  const el = card(j.filename);
  if (total > 1) el.querySelector('.fname').insertAdjacentHTML('afterend',
    `<span class="split">page ${j.page}</span>`);
  el.querySelector('.jobid').textContent = j.job_id.slice(0, 8) + '…';
  setStatus(el, 'PENDING', true);
  el.querySelector('.steps').innerHTML = stepHTML(1);
  const t0 = performance.now();
  const timer = setInterval(() => { el.querySelector('.el').textContent = ((performance.now()-t0)/1000).toFixed(1)+'s'; }, 100);
  poll(j.job_id, el).finally(() => clearInterval(timer));
}

async function poll(jobId, el) {
  for (let i = 0; i < 120; i++) {
    await sleep(2000);
    const job = await (await fetch('/api/jobs/' + jobId)).json();
    fetch('/api/jobs/' + jobId + '/audit').then(r => r.json()).then(a => renderAudit(el, a)).catch(()=>{});
    if (job.status === 'RUNNING') {
      setStatus(el, 'RUNNING', true);
      el.querySelector('.steps').innerHTML = stepHTML(job.source_path ? 2 : 1);
    } else if (job.status === 'SUCCEEDED') {
      setStatus(el, 'SUCCEEDED', false);
      el.querySelector('.steps').innerHTML = stepHTML(4);
      return render(el, job);
    } else if (job.status === 'FAILED') {
      setStatus(el, 'FAILED', false);
      el.insertAdjacentHTML('beforeend', `<div class="err">${esc(job.error || 'extraction failed')}</div>`);
      return;
    }
  }
}

function render(el, job) {
  const inv = job.result || {};
  const cur = inv.currency ? inv.currency + ' ' : '';
  const money = v => v == null ? null : cur + (+v).toFixed(2);
  const rows = [
    ['Vendor', inv.vendor], ['Invoice #', inv.invoice_number], ['Date', inv.invoice_date],
    ['Bill to', inv.bill_to], ['Subtotal', money(inv.subtotal)], ['Tax', money(inv.tax)],
    ['Payment', inv.payment_method],
  ].filter(([,v]) => v != null && v !== '');
  let html = '<div class="body"><table>';
  html += rows.map(([k,v]) => `<tr><td class="k">${k}</td><td class="v">${esc(String(v))}</td></tr>`).join('');
  html += `<tr class="total"><td class="k">Total</td><td class="v">${esc(money(inv.total) || '—')}</td></tr></table>`;
  const items = inv.line_items || [];
  if (items.length) {
    html += `<div class="items"><div class="ih">${items.length} line item${items.length>1?'s':''}</div>` +
      items.map(li => `<div class="it"><span>${esc(li.description||'')}</span><span>${esc(money(li.amount) || '')}</span></div>`).join('') +
      '</div>';
  }
  html += `<div class="prov">model: ${esc(job.tier_used||'?')} · scanned: ${job.was_scan} · stored: ${esc(job.source_path||'')}</div>`;
  html += '</div>';
  el.insertAdjacentHTML('beforeend', html);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
</script>
</body>
</html>"""
