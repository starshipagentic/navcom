"""Carried reader Back controls traverse their real in-tab history, not new entries."""
from test_space_action_rail import DOM
from test_space_camera import ROOT, js_between, run_js


def controller(checks):
    source = (ROOT/'navcom_space.js').read_text()
    functions = js_between('const fresh=', '\nlet route=')
    functions += js_between('function url(', 'function saveSoon(')
    functions += js_between('function restore(value)', 'function setActive(')
    functions += js_between('function carriedState(', 'function openFiles(')
    functions += js_between('function datedRoute(', 'function timeKey(')
    functions += js_between('function fly(', 'function followEvidence(')
    functions += js_between('function goBack(', 'function setSelection(')
    functions += js_between('function pageOffset(', 'function renderDestinationPager(')
    functions += js_between('const reads=new Map();', 'function historyPanel(')
    functions += js_between("window.addEventListener('popstate'", '\nfunction fly(')
    run_js(DOM + r"""
Object.defineProperty(El.prototype,'classList',{get(){return {add(){},remove(){},toggle(){}}}});
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40,STORE='carried-journey';
const local=new Map(),session=new Map(),localStorage={getItem:k=>local.get(k),setItem:(k,v)=>local.set(k,v)},sessionStorage={getItem:k=>session.get(k),setItem:(k,v)=>session.set(k,v)};
const location={href:'http://localhost/?view=space',get search(){return new URL(this.href).search}};
const entries=[null];let cursor=0;
const history={get state(){return entries[cursor]?.state||null},replaceState(state,_,url){entries[cursor]={state:structuredClone(state),url:String(url)};location.href=String(url)},pushState(state,_,url){entries.splice(cursor+1);entries.push({state:structuredClone(state),url:String(url)});cursor++;location.href=String(url)},back(){this.go(-1)},forward(){this.go(1)},go(delta){assert.ok(cursor+delta>=0&&cursor+delta<entries.length,'stay inside recorded app history');cursor+=delta;location.href=entries[cursor].url;listeners.popstate({state:history.state});}};
const listeners={},window={addEventListener:(name,fn)=>listeners[name]=fn};
const document={body:el('body'),activeElement:null};document.activeElement=document.body;
const working={id:'fleet:ship:working',kind:'ship',label:'Working'},archive={id:'fleet:ship:archive',kind:'ship',form:'archive',label:'Archive'},catalog='a'.repeat(64);
const inspector=el('aside'),input=el('input'),scope={},back={},forward={},stage=el('div'),results=el('section'),carriedDialog=el('dialog'),activationEvent=null;
let route,view,active=true,lastStep=0,journeyId='',carriedTicket=0,carriedFocus=false,timeData=null,searchResult=null,innerWidth=1280;
const no=()=>{},voiceInput={cancel:no},beginFlight=()=>null,updateRadar=no,showBeaconName=no,copyRoute=()=>structuredClone(route),pathRow=path=>el('code',{},path);
function setActive(value){active=value;hideCarriedReader()}
function loadView(){hideCarriedReader();view={center:route.place===archive.id?archive:working,nodes:[]};renderSelection();remember()}
function renderSelection(){hideCarriedReader();inspector.replaceChildren();const node=selectedNode();if(route.carriedRead?.place===node.id){const panel=el('section',{class:'space-carried-panel'});inspector.append(panel);loadCarried(node,panel)}}
replies['/api/space/context']=path=>{const p=new URL(path,'http://localhost').searchParams;return {state:'available',catalog,offset:Number(p.get('offset')),next_offset:10,provenance:{},total_sessions:1,sessions:[{id:'native-one',provider:'claude',messages:50}],messages:[{id:'native-one',provider:'claude',role:'assistant',index:34,text:'Recorded build decision'}]}};
""" + functions + r"""
route={...fresh(),place:working.id,pan:{x:32,y:-17},zoom:1.8,cameraScale:.7,cameraReady:true};
view={center:working,nodes:[archive]};restoreJourney(null);remember();
async function searchAndRead(){
 fly(archive.id);await tick();openCarried(archive);await tick();
 const form=walk(inspector).find(n=>n.tag==='form');form.children[0].value='build';form.fire('submit');await tick();
 const search=structuredClone(route),index=cursor;
 press(inspector,'Read original turn 34');await tick();assert.equal(carriedDialog.open,true);
 return {search,index};
}
""" + checks)


def test_context_back_close_top_back_and_forward_follow_actual_chronology():
    controller(r"""
(async()=>{
 const initial=structuredClone(route),{search,index}=await searchAndRead(),total=entries.length;
 press(carriedDialog,'← Back to context search');await tick();
 assert.equal(cursor,index,'The labeled Back action returns to its actual search entry');
 assert.equal(entries.length,total,'Back does not append a second search after the reader');
 assert.deepEqual(route,search);assert.equal(carriedDialog.open,false);
 closeCarried();assert.equal(route.carriedRead,null);
 goBack();await tick();assert.equal(route.carriedRead.action,'inspect');assert.equal(carriedDialog.open,false);
 const first=location.href;goBack();await tick();assert.equal(route.place,archive.id);assert.equal(route.carriedRead,null);assert.notEqual(location.href,first);
 goBack();await tick();assert.equal(route.place,working.id);assert.deepEqual(route.pan,initial.pan);assert.equal(route.zoom,initial.zoom);
 history.forward();await tick();assert.equal(route.place,archive.id);history.forward();await tick();assert.equal(route.carriedRead.action,'inspect');
 history.forward();await tick();assert.equal(route.carriedRead,null);history.forward();await tick();assert.equal(route.carriedRead.turn,34);assert.equal(carriedDialog.open,true);
 press(carriedDialog,'← Back to context search');await tick();assert.deepEqual(route.carriedRead,search.carriedRead);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_reader_paging_and_reload_return_to_exact_search_page_with_original_catalog():
    controller(r"""
(async()=>{
 await searchAndRead();history.back();await tick();
 press(inspector,'More context →');await tick();const search=structuredClone(route),index=cursor;
 assert.equal(search.carriedRead.offset,10);
 press(inspector,'Read original turn 34');await tick();
 press(carriedDialog,'More context →');await tick();assert.equal(route.carriedRead.offset,10);
 const copied=location.href,kept=structuredClone(history.state.navcomSpace),total=entries.length;
 hideCarriedReader();restore(kept);restoreJourney(history.state);loadView();await tick();
 assert.equal(carriedDialog.open,true);assert.equal(location.href,copied);
 press(carriedDialog,'← Back to context search');await tick();
 assert.equal(cursor,index);assert.equal(entries.length,total);assert.deepEqual(route,search);
 assert.equal(route.carriedRead.catalog,catalog);assert.equal(route.carriedRead.offset,10);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_copied_reader_returns_in_place_without_cross_tab_history_traversal():
    controller(r"""
(async()=>{
 const {search}=await searchAndRead(),copied=url();
 const read=carriedParam(copied.searchParams);assert.ok(read.backTo);
 // A new tab has no predecessor, even though the URL still records its context.
 entries.splice(0);entries.push(null);cursor=0;route=fresh();restore({place:archive.id,carriedRead:read,step:0});
 restoreJourney(null);remember();loadView();await tick();assert.equal(carriedDialog.open,true);
 const count=entries.length;press(carriedDialog,'← Back to context search');await tick();
 assert.equal(cursor,0);assert.equal(entries.length,count);assert.equal(carriedDialog.open,false);
 assert.deepEqual(route.carriedRead,search.carriedRead);assert.equal(route.place,archive.id);
 assert.equal(carriedState({...read,backTo:{...read.backTo,journey:'invalid\njourney'}}).backTo,undefined);
 assert.equal(carriedState({...read,backTo:{...read.backTo,state:{...read.backTo.state,place:working.id}}}).backTo,undefined);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_bounded_long_reader_link_keeps_search_return_state():
    controller(r"""
(async()=>{
 await searchAndRead();history.back();await tick();
 route.carriedRead.q='long question '.repeat(35);route.carriedRead.place=archive.id='fleet:ship:'+ 'x'.repeat(180);view.center=archive;route.place=archive.id;remember();
 openCarried(archive,{...route.carriedRead,action:'open',ref:'r'.repeat(200),turn:34,chars:8000});await tick();
 const linked=carriedParam(url().searchParams);assert.ok(linked);assert.deepEqual(linked,route.carriedRead);
 assert.equal(linked.backTo.state.q,route.carriedRead.q);
})().catch(e=>{console.error(e);process.exitCode=1});
""")
