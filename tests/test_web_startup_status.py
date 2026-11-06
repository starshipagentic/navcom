"""Space startup ends the connection placeholder without replacing newer status."""
from pathlib import Path

import pytest
from test_space_camera import run_js


PAGE = (Path(__file__).resolve().parents[1] / 'navcom_web.html').read_text()


def controller(checks):
    helpers = PAGE[PAGE.index('function message('):PAGE.index('function saveState(')]
    helpers += PAGE[PAGE.index('async function stats('):PAGE.index("$('search').addEventListener(")]
    startup = next(line for line in PAGE.splitlines() if line.startswith("window.addEventListener('DOMContentLoaded'"))
    run_js(r"""
const assert=require('node:assert/strict'),TOKEN='fixture';
class Element {
 constructor(text=''){this.textContent=text;this.children=[];this.classes=new Set();this.classList={add:n=>this.classes.add(n),remove:n=>this.classes.delete(n),contains:n=>this.classes.has(n),toggle:(n,on)=>on?this.classes.add(n):this.classes.delete(n)}}
 replaceChildren(...children){this.children=children}
}
const nodes={status:new Element('Connecting to your local archive…'),progress:new Element(),stats:new Element(),upkeep:new Element(),query:new Element()};
nodes.progress.classList.add('busy');const $=id=>nodes[id],el=(tag,attrs,...children)=>({tag,attrs,children});
const document={body:new Element()};document.body.classList.add('space-active');
let pending=0,taskTimer=null,loads=0,state={},startup;
const timers=new Map();let clock=0;const setTimeout=fn=>{const id=++clock;timers.set(id,fn);return id},clearTimeout=id=>timers.delete(id);
const window={addEventListener:(name,fn)=>{if(name==='DOMContentLoaded')startup=fn}};
const load=async()=>{loads++};
const requests=[];const fetch=path=>new Promise((resolve,reject)=>requests.push({path,resolve:data=>resolve({ok:true,json:async()=>data}),reject}));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const receipt=(task={running:false,error:false,message:''})=>({stats:{sessions:35,turns:6007,archive_files:15},task});
async function begin(){const started=startup();assert.equal(requests[0].path,'/api/state');requests[0].resolve({query:''});await tick();assert.equal(requests[1].path,'/api/status');return {started,request:requests[1]}}
""" + helpers + startup + checks)


def test_idle_space_startup_connects_without_loading_library_or_busy_timer():
    controller(r"""
(async()=>{
 const {started,request}=await begin();request.resolve(receipt());await started;
 assert.equal(nodes.status.textContent,'Connected to your local archive.');assert.equal(loads,0);
 assert.equal(nodes.progress.classList.contains('busy'),false);assert.equal(taskTimer,null);assert.equal(pending,0);
 assert.equal(nodes.stats.children.length,3);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


@pytest.mark.parametrize('error', [False, True])
def test_idle_reply_cannot_overwrite_newer_work_or_error_message(error):
    controller(r"""
(async()=>{
 const {started,request}=await begin();message(TEXT,ERROR);request.resolve(receipt());await started;
 assert.equal(nodes.status.textContent,TEXT);assert.equal(nodes.status.classList.contains('error'),ERROR);
 assert.equal(nodes.progress.classList.contains('busy'),false);assert.equal(loads,0);
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace('ERROR', str(error).lower()).replace('TEXT', repr('Saved historical scope unavailable' if error else 'Committed application ready')))


def test_running_native_task_keeps_busy_progress_and_its_actual_status():
    controller(r"""
(async()=>{
 const {started,request}=await begin();request.resolve(receipt({running:true,error:false,message:'Indexing 7 of 35 sessions'}));await started;
 assert.equal(nodes.status.textContent,'Indexing 7 of 35 sessions');assert.ok(taskTimer);
 assert.equal(timers.size,1);assert.equal(nodes.progress.classList.contains('busy'),true);assert.equal(loads,0);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_native_task_failure_is_never_reported_as_connected_success():
    controller(r"""
(async()=>{
 const {started,request}=await begin();request.resolve(receipt({running:false,error:true,message:'Index unavailable'}));await started;
 assert.equal(nodes.status.textContent,'Index unavailable');assert.equal(nodes.status.classList.contains('error'),true);
 assert.equal(nodes.progress.classList.contains('busy'),false);assert.equal(taskTimer,null);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_idle_status_does_not_clear_another_outstanding_request_progress():
    controller(r"""
(async()=>{
 const {started,request}=await begin();const other=api('/api/history/land');message('Opening committed files…');
 request.resolve(receipt());await started;assert.equal(nodes.status.textContent,'Opening committed files…');
 assert.equal(nodes.progress.classList.contains('busy'),true);assert.equal(pending,1);
 requests.at(-1).resolve({});await other;assert.equal(nodes.progress.classList.contains('busy'),false);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_library_startup_still_loads_its_existing_archive_view():
    controller(r"""
(async()=>{
 document.body.classList.remove('space-active');const {started,request}=await begin();request.resolve(receipt());await started;
 assert.equal(loads,1);assert.equal(nodes.progress.classList.contains('busy'),false);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


@pytest.mark.parametrize('space', [True, False])
def test_completed_background_task_refreshes_stats_but_only_loads_visible_library(space):
    controller(r"""
(async()=>{
 if(!SPACE)document.body.classList.remove('space-active');
 const {started,request}=await begin();request.resolve(receipt({running:true,error:false,message:'Indexing sessions'}));await started;
 const before=loads,callback=timers.get(taskTimer);assert.equal(typeof callback,'function');
 const finishing=callback();assert.equal(requests.at(-1).path,'/api/task');
 requests.at(-1).resolve({running:false,error:false,message:'Complete: 3 indexed'});await finishing;
 assert.equal(loads,before+(SPACE?0:1),'Only the visible Library loads on task completion');
 assert.equal(requests.at(-1).path,'/api/status');requests.at(-1).resolve(receipt());await tick();
 assert.equal(nodes.status.textContent,'Complete: 3 indexed');assert.equal(taskTimer,null);
 assert.equal(nodes.progress.classList.contains('busy'),false);assert.equal(pending,0);
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace('SPACE', str(space).lower()))
