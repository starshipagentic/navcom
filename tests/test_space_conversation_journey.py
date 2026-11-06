"""An indexed passage is part of the bridge journey, not Library view state."""
from pathlib import Path
from test_space_camera import js_between, run_js

ROOT = Path(__file__).resolve().parents[1]


def reader_controller(body):
    page = (ROOT/'navcom_web.html').read_text()
    native = page[page.index('function cancelDetail('):page.index('async function stats(')]
    helpers = js_between('const fresh=', '\nlet route=')
    helpers += js_between('function url(', '// A tab owns')
    helpers += js_between('function restoreJourney(', 'function saveSoon(')
    helpers += js_between('function restore(value)', 'function setActive(')
    helpers += js_between('let readerOrigin=', 'const voiceInput=')
    pop = js_between("window.addEventListener('popstate'", '\nfunction fly(')
    setup = r"""
const assert=require('node:assert/strict');
class El {
 constructor(tag,attrs={},children=[]){this.tagName=tag.toUpperCase();this.children=[];this.attrs=attrs;this.listeners={};this.parent=null;this.connected=true;this.scrollTop=0;this.value=attrs.value||'';Object.assign(this,Object.fromEntries(Object.entries(attrs).filter(([k])=>k.startsWith('on'))));this.classes=new Set((attrs.class||'').split(' ').filter(Boolean));this.classList={contains:n=>this.classes.has(n),add:n=>this.classes.add(n),remove:n=>this.classes.delete(n)};this.append(...children)}
 append(...children){for(const n of children){this.children.push(n);if(n instanceof El)n.parent=this}}
 prepend(n){this.children.unshift(n);n.parent=this}
 replaceChildren(...children){for(const n of this.children)if(n instanceof El)n.connected=false;this.children=[];this.append(...children)}
 querySelectorAll(selector){const selectors=selector.split(',');return walk(this).slice(1).filter(n=>selectors.some(s=>s[0]==='.'?n.classes.has(s.slice(1)):n.tagName===s.toUpperCase()))}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null}
 remove(){this.parent.children=this.parent.children.filter(n=>n!==this);this.connected=false}
 get isConnected(){return this.connected}
 focus(){document.activeElement=this;for(const fn of detail.listeners.focusin||[])fn({target:this})}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn)}
 setAttribute(k,v){this.attrs[k]=v}
 get options(){return this.children.filter(n=>n instanceof El&&n.tagName==='OPTION')}
}
function walk(n){return n instanceof El?[n,...n.children.flatMap(walk)]:[]}
function words(n){return n instanceof El?[n.textContent||'',...n.children.map(words)].join(' '):String(n)}
const el=(tag,attrs={},...children)=>new El(tag,attrs,children);
const button=(label,fn,attrs={})=>el('button',{...attrs,onclick:fn},label);
function press(root,label){const found=walk(root).find(n=>n.tagName==='BUTTON'&&words(n).trim()===label);assert.ok(found,'button '+label);return found.onclick({currentTarget:found})}
const document={body:new El('body'),activeElement:null};document.body.classList.add('space-active');document.activeElement=document.body;
const detail=el('section'),input=el('input'),scope={},$=()=>detail;
const listeners={},window={addEventListener:(name,fn)=>listeners[name]=fn};
let observerCallback,observing=false;class MutationObserver {constructor(fn){observerCallback=fn}observe(){observing=true}disconnect(){observing=false}}
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40,STORE='reader-test';let route,active=true,view=null,lastStep=0,journeyId='';
const back={},forward={},copyRoute=()=>structuredClone(route),updateRadar=()=>{},showBeaconName=()=>{};
const local=new Map(),session=new Map();const localStorage={getItem:k=>local.get(k),setItem:(k,v)=>local.set(k,v)},sessionStorage={getItem:k=>session.get(k),setItem:(k,v)=>session.set(k,v)};
const location={href:'http://localhost/?view=space',get search(){return new URL(this.href).search}};
const entries=[null];let cursor=0;
const history={get state(){return entries[cursor]?.state||null},replaceState(state,_,url){entries[cursor]={state:structuredClone(state),url:String(url)};location.href=String(url)},pushState(state,_,url){entries.splice(cursor+1);entries.push({state:structuredClone(state),url:String(url)});cursor++;location.href=String(url)},back(){assert.ok(cursor>0,'must not leave the app');cursor--;pop()},forward(){assert.ok(cursor+1<entries.length);cursor++;pop()}};
function pop(){location.href=entries[cursor].url;listeners.popstate({state:history.state})}
const pageOffset=(x,n)=>Math.max(0,Math.floor((Number(x)||0)/n)*n),carriedState=x=>x,landingState=x=>x;
const carriedParam=()=>null,datedRoute=()=>({}),linkCamera=()=>({});
function setActive(value){closeReader(false,false);active=value}
function loadView(){return globalThis.NavcomConversationReader.restore()}
let detailSeq=0,currentDetail=null,detailOwner='library',saves=0,listRenders=0;
const state={selected:'library-original',start:3},renderList=()=>listRenders++,saveState=()=>saves++;
const errors=[],fail=error=>errors.push(error.message),message=()=>{},annotate=()=>{},navigator={clipboard:{writeText:async()=>{}}};
const timeLabel=x=>x;
const requests=[];function api(path){return new Promise((resolve,reject)=>requests.push({url:new URL(path,'http://localhost'),resolve,reject}))}
function complete(request=requests.at(-1),extra={}){const key=request.url.searchParams.get('key'),start=Number(request.url.searchParams.get('start'));request.resolve({key,start,last:681,title:'Indexed '+key,provider:'codex',project:'/fixture',annotation:{},plan:{line:'native preview'},preview:'Resume preview',last_reply:'recorded',turns:[[start,'user','passage '+start]],...extra})}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
"""
    run_js(setup+helpers+native+pop+r"""
route={...fresh(),place:'moon:orchard',q:'find calibration in Orchard',interpretedQ:'calibration',searchWithin:'moon:orchard',local:false,searchOffset:40,selected:'district:engine',pan:{x:19,y:-31},zoom:2,cameraScale:.6,cameraReady:true,railPanel:{place:'moon:orchard',panel:'conversations',q:'solve2',offset:40,children:true,choice:0,at:''}};
input.value=route.q;scope.checked=route.local;restoreJourney(null);remember();
"""+body)


def test_exact_child_reader_paging_back_forward_reload_and_copied_link():
    reader_controller(r"""
(async()=>{
 const before=structuredClone(route),key='/archive/child.jsonl#native-child';
 const opening=readConversation(key,77);assert.equal(entries.length,2);assert.equal(route.conversationRead.key,key);complete();await opening;
 assert.equal(new URL(location.href).searchParams.get('conversation'),key);assert.equal(new URL(location.href).searchParams.get('turn'),'77');
 assert.deepEqual(state,{selected:'library-original',start:3});assert.equal(saves,0);
 await press(detail,'Next 80 →');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace(" await press(detail,'Next 80 →');", r"""
 const paging=press(detail,'Next 80 →');assert.equal(requests.at(-1).url.searchParams.get('start'),'157');complete();await paging;
 assert.equal(route.conversationRead.start,157);assert.equal(entries.length,2,'paging replaces one reader step');
 assert.equal(new URL(location.href).searchParams.get('turn'),'157');assert.equal(saves,0);
 history.back();await tick();assert.equal(document.body.classList.contains('space-reading'),false);assert.deepEqual(route,before);
 history.forward();complete();await tick();assert.equal(currentDetail.key,key);assert.equal(currentDetail.start,157);
 const saved=structuredClone(history.state.navcomSpace),link=location.href;
 closeReader(false,false);restore(saved);loadView();complete();await tick();assert.equal(currentDetail.start,157);assert.equal(route.conversationRead.openedStep,1);
 // A copied URL has no known predecessor. Its compact panel survives too.
 const p=new URL(link).searchParams;closeReader(false,false);restore({...before,...conversationRoute(p),step:0});remember();loadView();complete();await tick();
 assert.equal(route.railPanel.q,'solve2');assert.equal(route.railPanel.children,true);assert.equal(route.railPanel.offset,40);
 const copiedCursor=cursor;closeReader();assert.equal(cursor,copiedCursor,'copied links close in place');assert.equal(route.conversationRead,null);assert.ok(!new URL(location.href).searchParams.has('conversation'));
 assert.deepEqual(route.railPanel,before.railPanel);assert.deepEqual(route.pan,before.pan);assert.equal(route.q,before.q);
"""))


def test_close_and_newer_read_reject_late_success_and_failure_and_keep_retry():
    reader_controller(r"""
(async()=>{
 const one=readConversation('child-one',9),first=requests.at(-1);closeReader();complete(first);await one;
 assert.equal(currentDetail,null,'closed request cannot replace shared Library detail');assert.equal(route.conversationRead,null);
 const two=readConversation('child-two',81),second=requests.at(-1);
 const three=readConversation('child-three',161),third=requests.at(-1);complete(third);await three;
 second.reject(Error('old failure'));await two;assert.equal(currentDetail.key,'child-three');assert.deepEqual(errors,[]);
 const newer=readConversation('gone-child',77),bad=requests.at(-1);bad.reject(Error('Not indexed'));await newer;
 assert.ok(detail.querySelector('.space-reader-close'));assert.ok(words(detail).includes('Not indexed'));
 const retry=press(detail,'Retry');assert.equal(requests.at(-1).url.searchParams.get('key'),'gone-child');complete();await retry;
 assert.equal(currentDetail.key,'gone-child');assert.equal(currentDetail.start,77);assert.equal(saves,0);
 // Native Library selection still saves normally; pending bridge reads cannot commit.
 const late=readConversation('late-child',2),last=requests.at(-1);setActive(false);document.body.classList.remove('space-active');
 const library=select('library-new',5);complete();await library;complete(last);await late;
 assert.equal(currentDetail.key,'library-new');assert.equal(currentDetail.start,5);assert.deepEqual(state,{selected:'library-new',start:5});assert.equal(saves,1);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_dated_journey_reader_is_explicitly_current_and_bad_links_stay_closed():
    reader_controller(r"""
(async()=>{
 route.timeAt='2026-10-01T12:00:00Z';route.timeCursor='a'.repeat(64)+':0';const dated=structuredClone(route);remember();
 const pending=readConversation('current-child',77);complete();await pending;
 assert.ok(words(detail).includes('Current conversation'));assert.ok(words(detail).includes('not limited to the chart’s date'));
 assert.equal(route.timeCursor,dated.timeCursor);assert.equal(route.timeAt,dated.timeAt);
 closeReader();assert.equal(route.timeCursor,dated.timeCursor);assert.equal(route.conversationRead,null);
 assert.equal(conversationState({key:'bad\nkey',start:1}),null);assert.equal(conversationState({key:'ok',start:0}),null);assert.equal(conversationState({key:'ok',start:1.5}),null);
 const count=requests.length;await readConversation('',1);assert.equal(requests.length,count);assert.equal(document.body.classList.contains('space-reading'),false);
 assert.equal(conversationRoute(new URLSearchParams('conversation=ok&turn=-1')).conversationRead,null);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_local_saved_reader_in_new_tab_cannot_go_back_out_of_the_app():
    reader_controller(r"""
(async()=>{
 const opening=readConversation('saved-child',77);complete();await opening;const saved=JSON.parse(localStorage.getItem(STORE));
 closeReader(false,false);entries.splice(0);entries.push(null);cursor=0;location.href='http://localhost/';
 restore(saved);restoreJourney(null);remember();loadView();complete();await tick();
 assert.notEqual(route.conversationRead.openedJourney,journeyId,'new tab owns a new history branch');
 closeReader();assert.equal(cursor,0);assert.equal(route.conversationRead,null);assert.ok(!new URL(location.href).searchParams.has('conversation'));
})().catch(error=>{console.error(error);process.exitCode=1});
""")
