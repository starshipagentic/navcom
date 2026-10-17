"""Execute the actual carried-context controller with a small DOM fixture."""
from pathlib import Path

import pytest
from test_space_camera import js_between as section, run_js


JS = (Path(__file__).resolve().parents[1] / 'navcom_space.js').read_text()


def run_controller(body, extra=''):
    functions = section('const fresh=', '\nlet route=')
    functions += section('function carriedState(', 'function openFiles(')
    functions += section('function url(){', 'function remember(')
    functions += section('function datedRoute(', 'function timeKey(')
    functions += section('function restore(', 'function setActive(')
    functions += section('function selectedNode(', 'function setSelection(')
    functions += section('function pageOffset(', 'function renderDestinationPager(')
    functions += section('const reads=new Map();', 'function historyPanel(')
    script = "const assert=require('node:assert/strict');\n" + functions + """
class Element {
 constructor(tag, attrs={}, children=[]) {
  this.tag=tag;this.attrs=attrs;this.children=children;this.isConnected=true;
  this.value=attrs.value||'';this.events={};this.focused=false;
 }
 append(...children){this.children.push(...children)}
 replaceChildren(...children){this.children=children}
 addEventListener(name,handler){this.events[name]=handler}
 focus(){this.focused=true;document.activeElement=this}
 scrollIntoView(){this.scrolled=true}
 setAttribute(name,value){this.attrs[name]=value}
 querySelector(selector){return selector==='h3'?walk(this).find(x=>x.tag==='h3')||null:null}
}
const el=(tag,attrs={},...children)=>new Element(tag,attrs,children);
const button=(label,callback,attrs={})=>el('button',{...attrs,onclick:callback},label);
function walk(root){return [root,...(root.children||[]).flatMap(x=>typeof x==='object'?walk(x):[])]}
function findButton(root,label){const found=walk(root).find(x=>x.tag==='button'&&x.children.includes(label));assert.ok(found,'Missing button: '+label);return found}
const click=(root,label)=>findButton(root,label).attrs.onclick();
const pathRow=path=>el('code',{},path);
const copy=()=>{};
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40,STORE='test';
let route=fresh(),active=true,lastStep=0,carriedTicket=0,carriedFocus=false,timeData=null;
const ship={id:'fleet:ship:orchard',kind:'ship',label:'Orchard'},other={id:'fleet:ship:cedar',kind:'ship',label:'Cedar'};
let view={center:{id:'fleet:base:fixture',kind:'starbase'},nodes:[ship,other]};
const inspector=el('aside'),input={value:''},scope={checked:true};
const remembered=[];
const remember=(push=false)=>remembered.push({push,route:JSON.parse(JSON.stringify(route))});
const renderSelection=()=>{carriedTicket++};
const location={href:'http://localhost/?view=space',search:'?view=space'};
const catalog='a'.repeat(64),newCatalog='b'.repeat(64);
function baseState(){return {place:ship.id,action:'inspect',q:'',ref:'',turn:null,offset:0,chars:2000,catalog:''}}
function begin(state={}){route.carriedRead=carriedState({...baseState(),...state});route.selected=ship.id}
const panel=el('section');
const document={body:el('body'),activeElement:null};document.activeElement=document.body;
""" + extra + "\n" + body
    run_js(script)


def test_open_and_close_keep_chart_camera_search_and_scope():
    run_controller("""
route={...route,place:view.center.id,q:'find amber',interpretedQ:'amber',searchWithin:'planet:exact',
 local:false,searchOffset:40,offset:80,zoom:2.5,pan:{x:31,y:-12},cameraReady:true,cameraScale:1.5,
 chartLayout:{key:'stable',points:[{id:ship.id,x:20,y:30}]},relatedPlace:'planet:exact',step:4};
const before=JSON.parse(JSON.stringify(route));
openCarried(ship);
assert.equal(route.step,5);assert.equal(route.selected,ship.id);
assert.equal(remembered.at(-1).push,true);
closeCarried();
assert.equal(route.carriedRead,null);
for(const key of ['place','q','interpretedQ','searchWithin','local','searchOffset','offset','zoom','pan','cameraReady','cameraScale','chartLayout','relatedPlace'])
 assert.deepEqual(route[key],before[key],key);
""")


def test_stored_copy_links_preserve_identity_and_open_catalog_on_return():
    run_controller("""
const link={id:'ship:archive',kind:'ship',form:'archive',label:'Stored orchard',physical:{host:'here',path:'/exact/archive'}};
const galaxy={id:'galaxy:owner',kind:'galaxy',stored_copies:[link]};
renderShipCopies(galaxy);
let detail=inspector.children.at(-1);
assert.ok(walk(detail).some(x=>x.children?.includes('/exact/archive')));
detail.open=true;detail.events.toggle();
assert.equal(route.copiesPlace,galaxy.id);
const previous=JSON.parse(JSON.stringify(route));
click(detail,'Open stored copy: Stored orchard →');assert.deepEqual(flights,['ship:archive']);
restore(previous);assert.equal(route.copiesPlace,galaxy.id);
assert.equal(url().searchParams.get('copies'),galaxy.id);
renderShipCopies(galaxy);detail=inspector.children.at(-1);
assert.ok(Object.hasOwn(detail.attrs,'open'));
detail.open=false;detail.events.toggle();assert.equal(route.copiesPlace,'');
""", extra=section('function renderShipCopies(', 'function renderSelection(')+"\nconst flights=[];const fly=id=>flights.push(id);")


def test_url_only_back_retains_interpreted_scope_and_stored_copy_catalog():
    popstate = next(line for line in JS.splitlines() if line.startswith("window.addEventListener('popstate'"))
    run_controller("""
const saved=baseState();saved.action='open';saved.ref='record';saved.turn=7;saved.catalog=catalog;
const params=new URLSearchParams({view:'space',place:ship.id,q:'find amber in orchard',
 search_within:'planet:orchard',search_terms:'amber',search_pending:'1',copies:ship.id,carried:JSON.stringify(saved)});
location.search='?'+params;popHandler({state:null});
assert.equal(route.searchWithin,'planet:orchard');assert.equal(route.interpretedQ,'amber');
assert.equal(route.searchPending,true);assert.equal(route.q,'find amber in orchard');
assert.equal(route.carriedRead.turn,7);assert.equal(route.carriedRead.catalog,catalog);
assert.equal(route.copiesPlace,ship.id);
""", extra="let popHandler;const window={addEventListener:(_,fn)=>popHandler=fn};const setActive=()=>{};const loadView=()=>{};\n"+popstate)


@pytest.mark.parametrize('change', [
    'closeCarried()',
    "route.selected=other.id;renderSelection()",
    'active=false',
    'panel.isConnected=false',
])
def test_late_success_after_close_switch_or_removal_is_ignored(change):
    run_controller("""
let resolve;const api=()=>new Promise(done=>{resolve=done});
(async()=>{
 begin();const pending=loadCarried(ship,panel);
 CHANGE;
 const before=JSON.stringify(panel.children);
 resolve({state:'available',catalog,sessions:[],total_sessions:0,offset:0,provenance:{}});
 await pending;
 assert.equal(JSON.stringify(panel.children),before);
 assert.ok(!route.carriedRead||route.carriedRead.catalog==='');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE', change))


@pytest.mark.parametrize('change', ['active=false', 'route.selected=other.id'])
def test_late_failure_after_leaving_or_switching_ship_is_ignored(change):
    run_controller("""
let reject;const api=()=>new Promise((_,fail)=>{reject=fail});
(async()=>{
 begin();const pending=loadCarried(ship,panel);
 CHANGE;
 const before=JSON.stringify(panel.children);
 reject(new Error('old request failed'));await pending;
 assert.equal(JSON.stringify(panel.children),before);
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE', change))


def test_new_request_wins_over_older_catalog_response():
    run_controller("""
const pending=[];const api=url=>new Promise(resolve=>pending.push({url,resolve}));
(async()=>{
 begin();const first=loadCarried(ship,panel);
 route.carriedRead={...route.carriedRead,action:'search',q:'amber'};
 const second=loadCarried(ship,panel);
 pending[1].resolve({state:'available',catalog:newCatalog,messages:[],offset:0,provenance:{}});await second;
 const before=JSON.stringify(panel.children);
 pending[0].resolve({state:'available',catalog,sessions:[],offset:0,provenance:{}});await first;
 assert.equal(route.carriedRead.catalog,newCatalog);
 assert.equal(JSON.stringify(panel.children),before);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_search_exact_turn_and_paging_keep_same_catalog_and_ship():
    run_controller("""
const requests=[];let response;
const api=async url=>{requests.push(new URL(url,'http://localhost'));return response};
(async()=>{
 begin();response={state:'available',catalog,sessions:[{id:'session-one',provider:'aider',messages:14}],
  offset:0,total_sessions:1,provenance:{},cli_command:'navcom atlas context fixture'};
 await loadCarried(ship,panel);
 assert.equal(route.carriedRead.catalog,catalog);
 const form=walk(panel).find(x=>x.tag==='form');form.children[0].value=' amber ';
 form.events.submit({preventDefault(){}});
 assert.deepEqual(route.carriedRead,{...baseState(),action:'search',q:'amber',catalog});
 response={state:'available',catalog,offset:0,next_offset:10,provenance:{},messages:[{
  id:'session-one',provider:'aider',role:'assistant',index:7,text:'amber decision',title:'Orchard'
 }]};
 await loadCarried(ship,panel);
 let params=requests.at(-1).searchParams;
 assert.equal(params.get('within'),ship.id);assert.equal(params.get('catalog'),catalog);
 assert.equal(params.get('q'),'amber');assert.equal(params.get('action'),'search');
 click(panel,'More context →');assert.equal(route.carriedRead.offset,10);assert.equal(route.carriedRead.catalog,catalog);
 await loadCarried(ship,panel);
 assert.equal(requests.at(-1).searchParams.get('offset'),'10');
 click(panel,'Read original turn 7');
 assert.equal(route.carriedRead.action,'open');assert.equal(route.carriedRead.ref,'session-one');
 assert.equal(route.carriedRead.turn,7);assert.equal(route.carriedRead.chars,8000);assert.equal(route.carriedRead.offset,0);
 await loadCarried(ship,panel);params=requests.at(-1).searchParams;
 assert.equal(params.get('catalog'),catalog);assert.equal(params.get('turn'),'7');assert.equal(params.get('ref'),'session-one');
 click(panel,'Read carried conversation');
 assert.equal(route.carriedRead.turn,null);assert.equal(route.carriedRead.catalog,catalog);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_handover_clears_catalog_and_pages_characters_without_dialogue_pin():
    run_controller("""
const requests=[];const api=async url=>{requests.push(new URL(url,'http://localhost'));return {
 state:'available',catalog:'',offset:0,text:'handover',text_chars:5000,next_offset:2000,provenance:{}}};
(async()=>{
 begin({catalog});renderCarried(ship,panel,{state:'available',catalog,sessions:[],offset:0,total_sessions:0,provenance:{}});
 click(panel,'Handover');
 assert.equal(route.carriedRead.action,'handover');assert.equal(route.carriedRead.catalog,'');
 await loadCarried(ship,panel);
 assert.equal(requests[0].searchParams.get('catalog'),'');assert.equal(requests[0].searchParams.has('turn'),false);
 click(panel,'More context →');assert.equal(route.carriedRead.offset,2000);assert.equal(route.carriedRead.catalog,'');
 await loadCarried(ship,panel);assert.equal(requests[1].searchParams.get('offset'),'2000');
 click(panel,'← Previous context');assert.equal(route.carriedRead.offset,0);
 assert.equal(carriedState({...baseState(),action:'handover',catalog}).catalog,'');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_history_restores_camera_and_exact_context_request():
    run_controller("""
begin({action:'open',ref:'session-one',turn:7,offset:0,chars:8000,catalog});
route={...route,place:view.center.id,zoom:3,pan:{x:12,y:45},cameraReady:true,cameraScale:1.4,
 chartLayout:{key:'fixed',points:[{id:ship.id,x:21,y:22}]},q:'amber',searchWithin:'planet:exact',step:8};
const saved=JSON.parse(JSON.stringify(route));route=fresh();restore(saved);
assert.deepEqual(route,saved);assert.equal(selectedNode().id,ship.id);
""")


def test_copied_context_route_restores_ship_on_url_only_history_navigation():
    listener = section("window.addEventListener('popstate'", '\nfunction fly(')
    run_controller("""
begin({action:'open',ref:'session-one',turn:7,chars:8000,catalog});
route.place=view.center.id;
const copied=url();assert.equal(copied.searchParams.get('place'),view.center.id);
assert.deepEqual(carriedParam(copied.searchParams),route.carriedRead);
location.href=copied.href;location.search=copied.search;route=fresh();
events.popstate({state:null});
assert.equal(loads,1);assert.equal(selectedNode().id,ship.id);
assert.deepEqual(route.carriedRead,{...baseState(),action:'open',ref:'session-one',turn:7,chars:8000,catalog});
""", extra="""
const events={},window={addEventListener:(name,fn)=>events[name]=fn};
const setActive=value=>active=value;let loads=0;const loadView=()=>loads++;
""" + listener)


def test_invalid_copied_context_does_not_select_or_read_arbitrary_input():
    run_controller("""
for(const value of [{...baseState(),action:'board'}, {...baseState(),catalog:'invalid'},
 {...baseState(),offset:-1},{...baseState(),chars:100000},{...baseState(),q:'x'.repeat(501)}])
 assert.equal(carriedParam(new URLSearchParams({carried:JSON.stringify(value)})),null);
assert.equal(carriedParam(new URLSearchParams({carried:'{' })),null);
""")


@pytest.mark.parametrize(('explicit', 'move_focus', 'expected'), [
    ('true', 'false', 'true'),
    ('false', 'false', 'false'),
    ('true', 'true', 'false'),
])
def test_only_explicit_context_action_can_recover_lost_focus(explicit, move_focus, expected):
    run_controller("""
let resolve;const api=()=>new Promise(done=>{resolve=done});
(async()=>{
 begin();const pending=loadCarried(ship,panel,EXPLICIT);
 const unrelated=el('input');if(MOVE_FOCUS)unrelated.focus();
 resolve({state:'available',catalog,sessions:[],offset:0,total_sessions:0,provenance:{}});await pending;
 const heading=panel.querySelector('h3');
 assert.equal(heading.focused,EXPECTED);
 if(MOVE_FOCUS)assert.equal(document.activeElement,unrelated);
 if(EXPECTED){assert.equal(heading.attrs.tabindex,'-1');assert.equal(panel.scrolled,true)}
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('EXPLICIT', explicit).replace('MOVE_FOCUS', move_focus).replace('EXPECTED', expected))
