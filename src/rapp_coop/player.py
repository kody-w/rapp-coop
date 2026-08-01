"""Browser player for telemetry recordings.

The CLI replay is for developers. This is for everyone else: open a page, pick a
perspective, press play, and watch a learning lifecycle unfold at the pace it
actually happened.

The player is deliberately a *projection client*. It fetches the one recorded
event log and does all perspective filtering in the browser, which means
switching viewpoint is instant and never re-reads the file -- and, more
importantly, it means the server never has to know what perspectives exist. A
viewpoint invented later is a change to this file alone.

Full fidelity is the point, so nothing is truncated here. The timeline shows
every event; selecting one shows its complete payload, including keys this
player has never heard of. A recorder that starts emitting richer events gets
richer playback for free.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Views the player offers in addition to each participant. Kept in sync with
# rapp_coop.replay by name only -- the filtering itself happens client-side.
BUILTIN_VIEWS = ("observer", "memory", "exam")


def list_recordings(root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Every .jsonl recording under ``root``, newest first."""
    base = Path(root).expanduser()
    found: list[dict[str, Any]] = []
    if not base.is_dir():
        return found
    for path in base.glob("*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append({
            "name": path.name,
            "bytes": stat.st_size,
            "modified": int(stat.st_mtime),
        })
    return sorted(found, key=lambda item: item["modified"], reverse=True)


def read_recording(root: str | os.PathLike[str], name: str) -> list[dict]:
    """Load one recording by name.

    ``name`` is taken as a bare filename: anything with a separator or a parent
    reference is refused rather than resolved, so a crafted name cannot escape
    the recordings directory.
    """
    safe = Path(str(name)).name
    if not safe.endswith(".jsonl") or safe != str(name):
        raise ValueError("recording must be a plain .jsonl filename")
    path = Path(root).expanduser() / safe
    if not path.is_file():
        raise FileNotFoundError(safe)
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                events.append(raw)
    return sorted(events, key=lambda e: e.get("seq", 0))


PLAYER_HTML = """<!doctype html>
<meta charset="utf-8"><title>rapp-coop &mdash; replay</title>
<style>
 :root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--dim:#7d8590;--fg:#e6edf3;
       --accent:#58a6ff;--good:#3fb950;--bad:#f85149;--warm:#d29922}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:14px/1.5 ui-sans-serif,system-ui,sans-serif}
 header{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;
        gap:10px;align-items:center;flex-wrap:wrap}
 h1{font-size:14px;margin:0 12px 0 0;font-weight:700;letter-spacing:.02em}
 select,button{font:inherit;background:var(--panel);color:var(--fg);
        border:1px solid var(--line);border-radius:6px;padding:5px 9px;cursor:pointer}
 button:hover,select:hover{border-color:var(--accent)}
 button.on{background:var(--accent);color:#04121f;border-color:var(--accent);font-weight:600}
 #scrub{flex:1;min-width:220px;accent-color:var(--accent)}
 #clock{font-variant-numeric:tabular-nums;color:var(--dim);min-width:96px;
        text-align:right;font-size:12px}
 main{display:grid;grid-template-columns:1fr 400px;height:calc(100vh - 96px)}
 #feed{overflow:auto;padding:6px 0}
 #detail{border-left:1px solid var(--line);overflow:auto;padding:12px 14px;
         background:var(--panel)}
 .row{display:grid;grid-template-columns:66px 26px 150px 1fr;gap:8px;
      padding:4px 14px;cursor:pointer;border-left:3px solid transparent}
 .row:hover{background:#1c2128}
 .row.sel{background:#1f2937;border-left-color:var(--accent)}
 .row.past{opacity:1}
 .row.future{opacity:.32}
 .t{color:var(--dim);font-variant-numeric:tabular-nums;font-size:12px;text-align:right}
 .g{text-align:center}
 .who{color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .txt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#c9d1d9}
 .act{color:var(--dim);font-size:11px}
 pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);
     border:1px solid var(--line);border-radius:6px;padding:10px;font-size:12px;
     margin:6px 0 14px}
 .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em;
    margin-top:12px}
 .pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;
       border:1px solid var(--line);color:var(--dim)}
 .pass{color:var(--good);border-color:var(--good)}
 .fail{color:var(--bad);border-color:var(--bad)}
 .mem{color:var(--warm);border-color:var(--warm)}
 #stats{padding:8px 14px;border-top:1px solid var(--line);color:var(--dim);
        font-size:12px;display:flex;gap:18px;flex-wrap:wrap}
 .empty{padding:30px 14px;color:var(--dim)}
</style>
<header>
  <h1>rapp-coop replay</h1>
  <select id="file"></select>
  <select id="view"></select>
  <button id="play">&#9654; play</button>
  <select id="speed">
    <option value="0">instant</option>
    <option value="1" selected>1&times;</option>
    <option value="2">2&times;</option>
    <option value="4">4&times;</option>
    <option value="10">10&times;</option>
  </select>
  <input type="range" id="scrub" min="0" max="0" value="0" step="1">
  <span id="clock">0.00s</span>
</header>
<main>
  <div id="feed"></div>
  <div id="detail" class="empty">Select an event.</div>
</main>
<div id="stats"></div>
<script>
const GLYPH = {"run.start":"|>","run.end":"|.","twin.hatch":"()",
 "lesson.deliver":"\\u2192","agent.response":"\\u2190","memory.write":"[+]",
 "memory.inject":"[:]","exam.question":"??","exam.answer":"!!","exam.grade":"==",
 "graduate":"**","remediate":"~~","promote":"^^","chat":"..","claim.acquire":"#",
 "claim.release":"#/"};
const MEMORY_VIEW = new Set(["memory.write","memory.inject","twin.hatch","graduate","promote"]);
const EXAM_VIEW = new Set(["exam.question","exam.answer","exam.grade","graduate","remediate"]);
const GLOBAL = new Set(["run.start","run.end","note"]);

let all = [], shown = [], idx = -1, timer = null, playing = false;
const $ = id => document.getElementById(id);

function project(events, view){
  if(view === "observer") return events.slice();
  if(view === "memory") return events.filter(e => MEMORY_VIEW.has(e.action) || GLOBAL.has(e.action));
  if(view === "exam") return events.filter(e => EXAM_VIEW.has(e.action) || GLOBAL.has(e.action));
  return events.filter(e => e.actor === view || e.subject === view || GLOBAL.has(e.action));
}
function participants(events){
  const seen = [];
  for(const e of events) for(const n of [e.actor, e.subject])
    if(n && !seen.includes(n)) seen.push(n);
  return seen;
}
function bodyOf(e){
  const p = e.payload || {};
  for(const k of ["text","content","question","answer","message","summary"])
    if(typeof p[k] === "string" && p[k].trim()) return p[k];
  const rest = Object.entries(p).filter(([k]) => !k.startsWith("_"));
  return rest.map(([k,v]) => k+"="+JSON.stringify(v)).join(", ");
}
function pill(e){
  if(e.action === "exam.grade")
    return '<span class="pill '+(e.payload && e.payload.passed ? "pass">PASS" : "fail">FAIL")+'</span>';
  if(e.action === "memory.write") return '<span class="pill mem">kept</span>';
  return "";
}

function renderFeed(){
  const feed = $("feed");
  feed.innerHTML = "";
  shown.forEach((e,i) => {
    const row = document.createElement("div");
    row.className = "row " + (i <= idx ? "past" : "future");
    if(i === idx) row.classList.add("sel");
    const who = e.actor + (e.subject && e.subject !== e.actor ? " \\u203a " + e.subject : "");
    row.innerHTML =
      '<div class="t">'+(e.mono||0).toFixed(2)+'s</div>'+
      '<div class="g">'+(GLYPH[e.action]||"*")+'</div>'+
      '<div class="who">'+esc(who||"-")+'<div class="act">'+esc(e.action)+'</div></div>'+
      '<div class="txt">'+esc(bodyOf(e))+' '+pill(e)+'</div>';
    row.onclick = () => { idx = i; renderFeed(); renderDetail(); syncScrub(); };
    feed.appendChild(row);
  });
  const sel = feed.querySelector(".sel");
  if(sel) sel.scrollIntoView({block:"nearest"});
}
function esc(s){ const d=document.createElement("div"); d.textContent=String(s==null?"":s); return d.innerHTML; }

function renderDetail(){
  const d = $("detail");
  const e = shown[idx];
  if(!e){ d.className="empty"; d.textContent="Select an event."; return; }
  d.className = "";
  const p = e.payload || {};
  let html = '<div class="k">event</div><pre>'+esc(e.action)+'  #'+esc(e.seq)+
             '  +'+(e.mono||0).toFixed(2)+'s\\n'+esc(e.at||"")+'</pre>';
  html += '<div class="k">who</div><pre>actor: '+esc(e.actor||"-")+
          '\\nsubject: '+esc(e.subject||"-")+'\\nrun: '+esc(e.run||"-")+
          '\\nschema: v'+esc(e.v==null?"?":e.v)+'</pre>';
  const body = bodyOf(e);
  if(body){ html += '<div class="k">content (full)</div><pre>'+esc(body)+'</pre>'; }
  const extra = {};
  for(const [k,v] of Object.entries(p))
    if(!["text","content","question","answer","message","summary"].includes(k)) extra[k]=v;
  if(Object.keys(extra).length)
    html += '<div class="k">payload</div><pre>'+esc(JSON.stringify(extra,null,2))+'</pre>';
  d.innerHTML = html;
}

function renderStats(){
  const c = {};
  for(const e of all) c[e.action] = (c[e.action]||0)+1;
  const grades = all.filter(e => e.action === "exam.grade");
  const passed = grades.filter(e => e.payload && e.payload.passed).length;
  const dur = all.length ? Math.max(...all.map(e => e.mono||0)) : 0;
  $("stats").innerHTML =
    '<span>'+all.length+' events</span>'+
    '<span>'+dur.toFixed(1)+'s</span>'+
    '<span>'+(c["lesson.deliver"]||0)+' lessons</span>'+
    '<span>'+(c["memory.write"]||0)+' memories kept</span>'+
    '<span>'+grades.length+' graded &rarr; '+passed+' passed</span>'+
    '<span>showing '+shown.length+' in this view</span>';
}

function syncScrub(){
  $("scrub").max = Math.max(0, shown.length-1);
  $("scrub").value = Math.max(0, idx);
  $("clock").textContent = (shown[idx] ? (shown[idx].mono||0).toFixed(2) : "0.00")+"s";
}
function setView(view){
  shown = project(all, view);
  idx = shown.length ? 0 : -1;
  renderFeed(); renderDetail(); renderStats(); syncScrub();
}

function step(){
  if(idx >= shown.length-1){ stop(); return; }
  const speed = parseFloat($("speed").value);
  const prev = shown[idx] ? (shown[idx].mono||0) : 0;
  idx++;
  renderFeed(); renderDetail(); syncScrub();
  const gap = speed > 0 ? Math.min(((shown[idx].mono||0)-prev)/speed, 4) : 0;
  timer = setTimeout(step, Math.max(gap*1000, speed > 0 ? 120 : 30));
}
function play(){ if(playing) return; playing = true; $("play").classList.add("on");
  $("play").innerHTML = "&#10073;&#10073; pause";
  if(idx >= shown.length-1) idx = -1; step(); }
function stop(){ playing = false; clearTimeout(timer);
  $("play").classList.remove("on"); $("play").innerHTML = "&#9654; play"; }

async function loadFile(name){
  const res = await fetch("/recording?name="+encodeURIComponent(name));
  const data = await res.json();
  all = data.events || [];
  const views = ["observer","memory","exam",...participants(all)];
  $("view").innerHTML = views.map(v => '<option>'+esc(v)+'</option>').join("");
  setView("observer");
}
async function boot(){
  const res = await fetch("/recordings");
  const data = await res.json();
  const items = data.recordings || [];
  if(!items.length){
    $("feed").innerHTML = '<div class="empty">No recordings found.<br><br>'+
      'Record one, then reload:<br><code>python examples/school_and_record.py</code></div>';
    return;
  }
  $("file").innerHTML = items.map(r => '<option>'+esc(r.name)+'</option>').join("");
  await loadFile(items[0].name);
}
$("file").onchange = e => { stop(); loadFile(e.target.value); };
$("view").onchange = e => { stop(); setView(e.target.value); };
$("play").onclick = () => playing ? stop() : play();
$("scrub").oninput = e => { stop(); idx = parseInt(e.target.value,10);
  renderFeed(); renderDetail(); syncScrub(); };
document.addEventListener("keydown", ev => {
  if(ev.target.tagName === "SELECT" || ev.target.tagName === "INPUT") return;
  if(ev.key === " "){ ev.preventDefault(); playing ? stop() : play(); }
  if(ev.key === "ArrowRight" && idx < shown.length-1){ stop(); idx++; renderFeed(); renderDetail(); syncScrub(); }
  if(ev.key === "ArrowLeft" && idx > 0){ stop(); idx--; renderFeed(); renderDetail(); syncScrub(); }
});
boot();
</script>
"""
