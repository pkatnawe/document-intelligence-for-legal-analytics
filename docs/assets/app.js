/* Shared nav + interactions for the working-doc site.
   Status dots: d=decided, r=recommended, o=open, l=learn, n=not-started */
const NAV = [
  {g:'Start', items:[
    {f:'index.html',          n:'⌂ Overview',                s:'n'},
    {f:'case.html',           n:'① Case Overview',           s:'d'},
  ]},
  {g:'★ Deliverable', items:[
    {f:'slides.html',         n:'▣ The Two Slides',          s:'d'},
    {f:'presentation.html',   n:'🎤 Presentation Prep',      s:'d'},
  ]},
  {g:'Part 1 — Architecture (locked)', items:[
    {f:'architecture.html',   n:'② Platform · Slide A',      s:'d'},
    {f:'pipeline.html',       n:'③ Execution · Slide B',     s:'d'},
    {f:'classification.html', n:'④ Classification',          s:'d'},
    {f:'storage-audit.html',  n:'⑤ Storage & Audit',         s:'d'},
    {f:'extensibility.html',  n:'⑥ Extensibility & Scale',   s:'d'},
  ]},
  {g:'Platform', items:[
    {f:'dev-loop.html',       n:'⑦ Dev / Test / Deploy',     s:'d'},
    {f:'eval.html',           n:'✓ Evaluation & Improvement', s:'d'},
    {f:'cost.html',           n:'💵 Cost & ROI',              s:'d'},
  ]},
  {g:'Reference', items:[
    {f:'concepts.html',       n:'★ Concepts & Glossary',     s:'n'},
  ]},
  {g:'Tracking', items:[
    {f:'decisions.html',      n:'⑧ Decisions & Open Qs',     s:'o'},
  ]},
  {g:'Part 2 — Service (built · deployed)', items:[
    {f:'task2-service.html',  n:'⑨ Extraction Service',      s:'d'},
  ]},
];

const here = location.pathname.split('/').pop() || 'index.html';

(function buildNav(){
  const nav = document.getElementById('side');
  if(!nav) return;
  let html = '<div class="brand">DOC INTELLIGENCE</div>'+
             '<div class="brandsub">Legal Analytics · Compass case</div>';
  NAV.forEach(group=>{
    html += '<div class="grp">'+group.g+'</div>';
    group.items.forEach(it=>{
      const active = it.f===here ? ' active' : '';
      html += '<a class="'+active.trim()+'" href="'+it.f+'">'+
                '<span>'+it.n+'</span><span class="dot '+it.s+'"></span></a>';
    });
  });
  html += '<div class="navstamp">Living doc — updates as we decide.<br>'+
          'Last updated: <b>2026-06-09</b><br>'+
          '<span style="opacity:.7">●</span> decided '+
          '<span style="color:#5fd778">●</span> rec '+
          '<span style="color:#a371f7">●</span> open</div>';
  nav.innerHTML = html;
})();

/* code tabs */
document.querySelectorAll('.tabs').forEach(tabs=>{
  const grp = tabs.dataset.grp;
  const pane = document.querySelector('.code[data-grp="'+grp+'"]');
  if(!pane) return;
  tabs.querySelectorAll('.tab').forEach(tab=>{
    tab.onclick=()=>{
      tabs.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      tab.classList.add('active');
      pane.querySelectorAll('pre').forEach(p=>p.hidden=(p.dataset.c!==tab.dataset.t));
    };
  });
});

/* open-question leans, persisted in localStorage, shared across pages */
const LEANS = JSON.parse(localStorage.getItem('di_leans')||'{}');
function renderLeans(){
  document.querySelectorAll('[data-oq]').forEach(row=>{
    const id = row.dataset.oq;
    row.querySelectorAll('button').forEach(b=>{
      b.classList.toggle('sel', LEANS[id]===b.dataset.v);
      b.onclick=()=>{
        LEANS[id] = (LEANS[id]===b.dataset.v ? undefined : b.dataset.v);
        if(LEANS[id]===undefined) delete LEANS[id];
        localStorage.setItem('di_leans', JSON.stringify(LEANS));
        renderLeans();
      };
    });
  });
  const sum = document.getElementById('leansum');
  if(sum){
    const picks = Object.keys(LEANS).map(k=>'<b>'+k+'</b> → '+LEANS[k]);
    sum.innerHTML = picks.length ? picks.join('<br>') : '— no leanings recorded yet —';
  }
}
renderLeans();

/* copy decisions to clipboard so they can be pasted back to Claude */
const copyBtn = document.getElementById('copyleans');
if(copyBtn){
  copyBtn.onclick = ()=>{
    const entries = Object.entries(LEANS);
    const txt = entries.length ? entries.map(([k,v])=>'- '+k+': '+v).join('\n') : '(no leans recorded yet)';
    navigator.clipboard.writeText('My decisions so far:\n'+txt).then(()=>{
      copyBtn.textContent='✓ copied — paste this to Claude';
      setTimeout(()=>copyBtn.textContent='📋 Copy my decisions',1800);
    });
  };
}

/* mermaid */
if(window.mermaid){ mermaid.initialize({startOnLoad:true, theme:'dark', themeVariables:{fontSize:'13px'}}); }
