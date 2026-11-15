"""The FreshGuard dashboard: one self-contained page (no build step, no external files).

It is served at /dashboard, holds no secrets, and asks the viewer for the API key, which it
keeps only for the browser tab (sessionStorage) and sends as X-API-Key. Every piece of text that
comes from the API or from web pages is inserted with textContent, never as HTML.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FreshGuard dashboard</title>
<style>
:root{
  --bg:#f6f7f9;--panel:#fff;--ink:#16202b;--muted:#5b6876;--line:#dfe3e8;--accent:#1d4ed8;
  --fresh:#0f7a3d;--fresh-bg:#e3f5ea;--pot:#8a5a00;--pot-bg:#fff1d6;
  --stale:#b42318;--stale-bg:#fde8e6;--unv:#475467;--unv-bg:#e9ecf1;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f141a;--panel:#171e26;--ink:#e8edf2;--muted:#9aa7b4;--line:#2a3541;--accent:#7aa2ff;
  --fresh:#6fdc9a;--fresh-bg:#12301f;--pot:#ffc766;--pot-bg:#3a2c0c;
  --stale:#ff8d82;--stale-bg:#3d1714;--unv:#b8c2cd;--unv-bg:#252e38;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding:14px 20px;background:var(--panel);border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}
h1 small{font-weight:400;color:var(--muted);margin-left:8px}
main{max-width:1200px;margin:0 auto;padding:16px 20px 40px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
input,textarea,button,select{font:inherit;color:inherit}
input,textarea{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;width:100%}
textarea{min-height:64px;resize:vertical}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;font-weight:600}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
button:disabled{opacity:.55;cursor:default}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.stat b{display:block;font-size:24px}
.stat span{color:var(--muted);font-size:13px}
.layout{display:grid;grid-template-columns:minmax(280px,420px) 1fr;gap:16px;align-items:start}
@media (max-width:820px){.layout{grid-template-columns:1fr}}
.list{display:flex;flex-direction:column;gap:8px;max-height:70vh;overflow:auto}
.item{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--panel);cursor:pointer;text-align:left;width:100%;color:inherit}
.item:hover,.item.sel{border-color:var(--accent)}
.item .ans{margin:6px 0 2px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.meta{color:var(--muted);font-size:12.5px}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12.5px;font-weight:700;white-space:nowrap}
.fresh{color:var(--fresh);background:var(--fresh-bg)}
.potentially_stale{color:var(--pot);background:var(--pot-bg)}
.stale{color:var(--stale);background:var(--stale-bg)}
.unverifiable,.failed,.pending,.running{color:var(--unv);background:var(--unv-bg)}
.chip{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;padding:4px 12px;font-weight:500}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
h2{font-size:17px;margin:0 0 8px}
h3{font-size:14.5px;margin:14px 0 6px}
.q{color:var(--muted)}
.claim{border-top:1px solid var(--line);padding:12px 0}
.ev{margin:8px 0;padding:8px 10px;border-left:3px solid var(--line);background:var(--bg);border-radius:0 8px 8px 0}
.ev.supports{border-left-color:var(--fresh)}
.ev.contradicts{border-left-color:var(--stale)}
.quote{font-style:italic;white-space:pre-wrap;word-break:break-word;margin:4px 0}
a{color:var(--accent);word-break:break-all}
.note{padding:10px 12px;border-radius:8px;background:var(--pot-bg);color:var(--pot)}
.fix{padding:10px 12px;border-radius:8px;background:var(--fresh-bg);color:var(--fresh)}
.err{color:var(--stale)}
.empty{color:var(--muted);padding:24px;text-align:center}
</style>
</head>
<body>
<header>
  <h1>FreshGuard <small>stale-answer detection</small></h1>
  <form class="row" id="connect" autocomplete="off">
    <input id="key" type="password" placeholder="API key" style="width:240px" aria-label="API key">
    <button type="submit">Connect</button>
  </form>
</header>
<main>
  <div id="status" class="meta" role="status"></div>
  <div class="stats" id="stats"></div>

  <details class="card" id="newbox" style="margin-bottom:16px">
    <summary><b>Check a new answer</b></summary>
    <div style="margin-top:10px;display:grid;gap:8px">
      <input id="nq" placeholder="Question the AI was asked, e.g. Who is the CEO of Apple?" maxlength="2000">
      <textarea id="na" placeholder="The answer to check, e.g. Tim Cook is the CEO of Apple." maxlength="8000"></textarea>
      <div class="row"><button id="go">Check freshness</button><span class="meta" id="gostat"></span></div>
    </div>
  </details>

  <div class="row" id="filters" style="margin-bottom:12px"></div>
  <div class="layout">
    <div>
      <div class="list" id="list"></div>
      <div style="margin-top:8px"><button class="ghost" id="more" hidden>Load more</button></div>
    </div>
    <div class="card" id="detail"><div class="empty">Connect with your API key, then pick a result.</div></div>
  </div>
</main>
<script>
(function(){
"use strict";
var LABELS=["fresh","potentially_stale","stale","unverifiable"];
var TTL_HOURS=24;
var state={key:"",items:[],next:null,filter:"all",sel:null,timer:null};
var $=function(id){return document.getElementById(id);};

function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined&&text!==null)e.textContent=String(text);return e;}
function pill(label){var p=el("span","pill "+label,label==="potentially_stale"?"potentially stale":label);return p;}
function safeUrl(u){try{var x=new URL(u);return(x.protocol==="http:"||x.protocol==="https:")?x.href:null;}catch(e){return null;}}
function ago(iso){
  if(!iso)return "";var s=(Date.now()-new Date(iso).getTime())/1000;
  if(s<60)return "just now";if(s<3600)return Math.floor(s/60)+" min ago";
  if(s<86400)return Math.floor(s/3600)+" h ago";return Math.floor(s/86400)+" d ago";
}
function hoursOld(iso){return iso?(Date.now()-new Date(iso).getTime())/3600000:0;}
function shown(r){return r.status==="completed"?(r.label||"unverifiable"):r.status;}

function api(method,path,body){
  var opt={method:method,headers:{"X-API-Key":state.key}};
  if(body){opt.headers["Content-Type"]="application/json";opt.body=JSON.stringify(body);}
  return fetch(path,opt).then(function(r){
    return r.json().catch(function(){return {};}).then(function(j){
      if(!r.ok){var m=(j.error&&j.error.message)||("HTTP "+r.status);var e=new Error(m);e.status=r.status;throw e;}
      return j;});
  });
}
function setStatus(msg,isErr){var s=$("status");s.textContent=msg||"";s.className=isErr?"meta err":"meta";}

function load(append){
  var q="/v1/verifications?limit=20"+(state.filter!=="all"&&LABELS.indexOf(state.filter)>=0?"&label="+state.filter:"")+(append&&state.next?"&before="+encodeURIComponent(state.next):"");
  return api("GET",q).then(function(p){
    state.items=append?state.items.concat(p.items):p.items;state.next=p.next_before;
    renderList();renderStats();schedule();setStatus("");
  }).catch(function(e){
    setStatus(e.status===401?"Wrong or missing API key.":"Could not load: "+e.message,true);
  });
}
function schedule(){
  clearTimeout(state.timer);
  var open=state.items.some(function(r){return r.status==="pending"||r.status==="running";});
  if(open)state.timer=setTimeout(function(){load(false).then(function(){if(state.sel)refreshSel();});},4000);
}
function refreshSel(){
  var cur=state.items.find(function(r){return r.id===state.sel;});if(cur)renderDetail(cur);
}

function renderStats(){
  var c={fresh:0,potentially_stale:0,stale:0,unverifiable:0,failed:0};
  state.items.forEach(function(r){var k=shown(r);if(c[k]!==undefined)c[k]++;});
  var box=$("stats");box.textContent="";
  [["Checked",state.items.length,""],["Fresh",c.fresh,"fresh"],["Potentially stale",c.potentially_stale,"potentially_stale"],["Stale",c.stale,"stale"],["Unverifiable",c.unverifiable,"unverifiable"]].forEach(function(s){
    var d=el("div","card stat");var b=el("b",s[2],s[1]);b.style.background="none";d.appendChild(b);d.appendChild(el("span","",s[0]));box.appendChild(d);
  });
}
function renderFilters(){
  var box=$("filters");box.textContent="";
  ["all"].concat(LABELS).forEach(function(f){
    var b=el("button","chip"+(state.filter===f?" on":""),f==="potentially_stale"?"potentially stale":f);
    b.type="button";b.onclick=function(){state.filter=f;renderFilters();load(false);};box.appendChild(b);
  });
}
function renderList(){
  var box=$("list");box.textContent="";
  if(!state.items.length){box.appendChild(el("div","empty","No results yet. Use “Check a new answer”."));}
  state.items.forEach(function(r){
    var b=el("button","item"+(r.id===state.sel?" sel":""));b.type="button";
    var top=el("div","row");top.appendChild(pill(shown(r)));
    if(r.confidence!==null&&r.confidence!==undefined)top.appendChild(el("span","meta","confidence "+Math.round(r.confidence*100)+"%"));
    if(r.metadata&&r.metadata.reverified_from)top.appendChild(el("span","meta","re-check"));
    if(r.status==="completed"&&hoursOld(r.finished_at||r.created_at)>TTL_HOURS)top.appendChild(el("span","meta","· re-check due"));
    b.appendChild(top);
    b.appendChild(el("div","ans",r.answer||""));
    b.appendChild(el("div","meta",ago(r.created_at)));
    b.onclick=function(){state.sel=r.id;renderList();renderDetail(r);};
    box.appendChild(b);
  });
  $("more").hidden=!state.next;
}

function renderDetail(r){
  var d=$("detail");d.textContent="";
  var head=el("div","row");head.appendChild(pill(shown(r)));
  if(r.confidence!==null&&r.confidence!==undefined)head.appendChild(el("span","meta","confidence "+Math.round(r.confidence*100)+"%"));
  head.appendChild(el("span","meta","checked "+ago(r.finished_at||r.created_at)));
  d.appendChild(head);
  d.appendChild(el("h2","",r.answer||""));
  d.appendChild(el("div","q","Question: "+(r.question||"")));
  if(r.metadata&&r.metadata.reverified_from){
    var o=el("div","meta","Re-check of an earlier result. ");var a=el("a","","open original");a.href="#";
    a.onclick=function(ev){ev.preventDefault();openById(r.metadata.reverified_from);};o.appendChild(a);d.appendChild(o);
  }
  if(r.status==="pending"||r.status==="running"){d.appendChild(el("div","note","Checking now. This usually takes under a minute."));}
  if(r.status==="failed"){d.appendChild(el("div","err","The check failed: "+(r.error||"unknown error")));}
  if(r.suggested_correction){var f=el("div","fix");f.appendChild(el("b","","Suggested correction: "));f.appendChild(document.createTextNode(r.suggested_correction));d.appendChild(f);
    d.appendChild(el("div","meta","Always confirm the correction against the sources below: it can be only as current as they are."));}
  if(r.label==="potentially_stale"){d.appendChild(el("div","note","Evidence was weak, old or undated: a human should look."));}
  if(r.label==="unverifiable"&&r.status==="completed"){d.appendChild(el("div","note","No verified evidence was found. FreshGuard does not guess."));}

  var acts=el("div","row");acts.style.margin="12px 0";
  var rv=el("button","","Re-verify now");rv.type="button";
  rv.onclick=function(){rv.disabled=true;rv.textContent="Starting…";
    api("POST","/v1/verifications/"+encodeURIComponent(r.id)+"/reverify").then(function(j){state.sel=j.id;return load(false).then(function(){refreshSel();});})
    .catch(function(e){setStatus("Re-verify failed: "+e.message,true);rv.disabled=false;rv.textContent="Re-verify now";});};
  acts.appendChild(rv);d.appendChild(acts);

  var checks=state.items.filter(function(x){return x.metadata&&x.metadata.reverified_from===r.id;});
  if(checks.length){d.appendChild(el("h3","","Later re-checks"));
    checks.forEach(function(x){var row=el("div","row");row.appendChild(pill(shown(x)));row.appendChild(el("span","meta",ago(x.created_at)));
      var l=el("a","","open");l.href="#";l.onclick=function(ev){ev.preventDefault();state.sel=x.id;renderList();renderDetail(x);};row.appendChild(l);d.appendChild(row);});}

  (r.claims||[]).forEach(function(c){
    var box=el("div","claim");var t=el("div","row");t.appendChild(pill(c.label));t.appendChild(el("b","",c.text));box.appendChild(t);
    box.appendChild(el("div","meta","Volatility: "+c.volatility+(c.freshness_window_days?" · evidence counts as recent within "+c.freshness_window_days+" days":"")));
    box.appendChild(el("div","","Why: "+c.reasoning));
    (c.evidence||[]).forEach(function(e){
      var ev=el("div","ev "+e.stance);
      var hd=el("div","meta",e.stance.toUpperCase()+" · tier "+e.tier+" · "+(e.published_at?"dated "+e.published_at.slice(0,10):"undated"));ev.appendChild(hd);
      if(e.quoted_span)ev.appendChild(el("div","quote","“"+e.quoted_span+"”"));
      var u=safeUrl(e.url);if(u){var a=el("a","",e.url);a.href=u;a.target="_blank";a.rel="noopener noreferrer nofollow";ev.appendChild(a);}else{ev.appendChild(el("span","meta",e.url));}
      box.appendChild(ev);
    });
    d.appendChild(box);
  });
}
function openById(id){
  var cur=state.items.find(function(r){return r.id===id;});
  if(cur){state.sel=id;renderList();renderDetail(cur);return;}
  api("GET","/v1/verifications/"+encodeURIComponent(id)).then(function(r){state.sel=id;renderDetail(r);}).catch(function(e){setStatus(e.message,true);});
}

$("connect").onsubmit=function(ev){
  ev.preventDefault();state.key=$("key").value.trim();
  try{sessionStorage.setItem("fg_key",state.key);}catch(e){}
  setStatus("Connecting…");load(false);
};
$("more").onclick=function(){load(true);};
$("go").onclick=function(){
  var q=$("nq").value.trim(),a=$("na").value.trim();
  if(!q||!a){$("gostat").textContent="Enter both a question and an answer.";return;}
  var b=$("go");b.disabled=true;$("gostat").textContent="Checking… this can take up to a minute.";
  api("POST","/v1/verifications?wait=true&timeout=120",{question:q,answer:a,metadata:{source:"dashboard"}})
  .then(function(j){$("gostat").textContent="";state.sel=j.id;$("na").value="";return load(false).then(function(){refreshSel();});})
  .catch(function(e){$("gostat").textContent="Failed: "+e.message;}).then(function(){b.disabled=false;});
};
renderFilters();renderStats();
try{var saved=sessionStorage.getItem("fg_key");if(saved){$("key").value=saved;state.key=saved;load(false);}}catch(e){}
})();
</script>
</body>
</html>
"""