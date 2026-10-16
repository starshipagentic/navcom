"""Run the shipped dated-landing controller against deferred native-shaped receipts."""
import pytest
from test_space_camera import ROOT, js_between, run_js


def controller(checks):
    source = (ROOT / 'navcom_space.js').read_text()
    fresh = source[source.index('const fresh='):].splitlines()[0]
    functions = js_between('function datedRoute(', 'function timeLabel(')
    functions += js_between('function url(', '// A tab owns')
    functions += js_between('function restore(value)', 'function setActive(')
    functions += js_between('function pageOffset(', 'function pageRange(')
    functions += js_between('async function loadView(', 'function arrivalSearchMatches(')
    functions += source[source.index('function sourceRef('):].splitlines()[0]
    run_js(fresh + r"""
const assert=require('node:assert/strict');
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40;
class Element {
 constructor(){this.children=[];this.classes=new Set();this.classList={add:(...x)=>x.forEach(y=>this.classes.add(y)),remove:(...x)=>x.forEach(y=>this.classes.delete(y)),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x)};this.attributes={};}
 append(...x){this.children.push(...x)} replaceChildren(...x){this.children=x}
 setAttribute(k,v){this.attributes[k]=v} removeAttribute(k){delete this.attributes[k]}
 querySelectorAll(){return []} focus(){} scrollIntoView(){}
}
const el=(tag,attrs={},...children)=>Object.assign(new Element(),{tag,attrs,children});
const button=(label,fn,attrs={})=>Object.assign(el('button',attrs,label),{label,click:fn});
const timeResults=new Element(),timeBar=new Element(),datedPanel=new Element(),inspector=new Element(),stage=new Element(),
 results=new Element(),searchPanel=new Element(),mapStatus=new Element(),empty=new Element(),places=new Element(),orbit=new Element(),orientation=new Element(),destinationPager=new Element();
const input={value:'old question'},scope={},scopeLabel={},heading={},caption={},navigatorStatus={},location={href:'http://localhost:62811/?view=space'};
const session='a'.repeat(64),result='b'.repeat(64),at='2025-04-01T00:00:00Z',productId='planet:lantern',groupId='historical-district:permissions';
let route={...fresh(),place:'system:orchard',timeAt:at,timeCursor:session+':0',timeQ:'old question',timeOpen:true,step:2,zoom:1.8,pan:{x:47,y:-23},cameraReady:true,cameraScale:.7};
let active=true,timeData=null,timeBusy=false,view=null,searchResult=null,loadTicket=0,searchTicket=0,timeTicket=0,datedTicket=0,lastStep=2;
const systemViews=new Map(),requests=[],saved=[],rendered=[],opened=[],flown=[],notices=[];let readerVisible=false,readerTicket=0;
const copyRoute=()=>structuredClone(route),remember=push=>saved.push({push,route:copyRoute()}),no=()=>{};
const api=(url,body)=>new Promise((resolve,reject)=>requests.push({url,body:structuredClone(body),resolve,reject}));
const voiceInput={cancel:no},cancelFlight=no,beginFlight=()=>null,arrive=no,renderCrumbs=no,renderDestinationPager=no,renderSelection=no,renderFooter=no,applySystemTime=no;
const renderTimeBar=()=>route.timeLanding?renderLandingBar():null,renderTimeResults=()=>route.timeLanding?renderLandingResults():null;
const renderMap=()=>rendered.push(structuredClone(view));
const loadDatedConversations=no,loadSource=()=>opened.push(route.sourceRead),hideSource=()=>{readerVisible=false;readerTicket++;},timeLabel=String,message=x=>notices.push(x),fly=x=>flown.push(x),returnToPresent=no;
const openSource=(ref)=>opened.push(ref),evidenceCard=(hit,title,context)=>({hit,ref:sourceRef(hit,context)});
const galaxy={id:'galaxy:owner',kind:'galaxy',label:'Your galaxy',position:{x:0,y:0}};
const system={id:'system:orchard',parent_id:galaxy.id,kind:'system',label:'Orchard',position:{x:10,y:10}};
const product={id:productId,parent_id:system.id,kind:'planet',label:'Lantern before rename',historical_state:'committed',position:{x:20,y:20},commit:'old-head',files:['src/auth.py'],file_count:1};
const group={id:groupId,parent_id:productId,kind:'district',label:'Authentication',group_id:groupId,historical_state:'committed',position:{x:22,y:21},files:['src/auth.py'],file_count:1};
function systemPage(){return {action:'system',cursor:session+':0',session_id:session,as_of:at,result_key:result,center:system,selected_place:system,nodes:[galaxy,system,product],breadcrumbs:[system],coverage:{}};}
function landing(grouped=false,query=route.timeQ){return {action:'land',cursor:session+':0',session_id:session,as_of:at,result_key:result,commit:'old-head',query,product,center:grouped?group:product,group_id:grouped?groupId:null,nodes:grouped?[group]:[product,group],breadcrumbs:[galaxy,system,product,...(grouped?[group]:[])],coverage:{files:1,native_groups:1,current_catalog_read:false},files:[{path:'src/auth.py',source_ref:{source_id:'revision-id',relative_path:'src/auth.py',line:1,snapshot:'artifact-sha',published:123,history:'revision-id'}}],snapshot:{id:'revision-id'},evidence:{concept_hits:[],text_hits:[]}};}
function start(){timeData=systemPage();view={center:system,nodes:[product],breadcrumbs:[galaxy,system],coverage:{}};}
async function land(){start();const pending=landHistorical(productId);requests.at(-1).resolve(landing());await pending;}
async function tick(){await new Promise(resolve=>setImmediate(resolve));}
""" + functions + checks)


def test_product_and_district_open_only_saved_history_and_keep_reader_pins():
    controller(r"""
(async()=>{
 const original=copyRoute();await land();
 assert.deepEqual(requests.map(r=>r.url),['/api/history/land']);
 assert.deepEqual(requests[0].body,{cursor:session+':0',within:productId,result_key:result,group:null,q:'old question',limit:20});
 assert.equal(view.center.label,'Lantern before rename');assert.deepEqual(view.nodes,[group]);
 assert.equal(mapStatus.textContent,'Committed product ready · saved history held steady');
 assert.equal(route.timeCursor,original.timeCursor);assert.equal(route.timeLanding.origin.pan.x,47);
 const pending=landHistorical(productId,groupId);requests.at(-1).resolve(landing(true));await pending;
 assert.equal(view.center.id,groupId);assert.equal(view.nodes.length,0);
 assert.equal(mapStatus.textContent,'Committed district ready · saved history held steady');
 assert.deepEqual(route.timeLanding.origin.pan,original.pan);
 const ref=sourceRef(timeData.files[0]);assert.deepEqual(ref,{source:'revision-id',path:'src/auth.py',history:'revision-id',snapshot:'artifact-sha',published:123,line:1,limit:80,focus:1});
 assert.ok(saved.every(x=>!JSON.stringify(x.route).includes('artifact-sha')),'Routes contain addresses, never retrieved file evidence');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_query_stays_in_landed_group_and_changed_head_is_never_requested():
    controller(r"""
(async()=>{
 await land();let pending=landHistorical(productId,groupId);requests.at(-1).resolve(landing(true));await pending;
 route.pan={x:81,y:12};route.zoom=2;const before=copyRoute();input.value='password';pending=searchHistoricalLanding('password');
 const request=requests.at(-1);assert.equal(request.url,'/api/history/land');assert.equal(request.body.cursor,session+':0');assert.equal(request.body.group,groupId);assert.equal(request.body.result_key,result);
 request.resolve(landing(true,'password'));await pending;
 assert.equal(timeData.commit,'old-head');assert.equal(route.timeQ,'password');assert.deepEqual(route.pan,before.pan);assert.equal(route.zoom,2);
 assert.equal(route.timeLanding.origin.timeQ,'old question');assert.ok(requests.every(r=>r.url!='/api/space'));
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_copy_link_reload_and_back_need_no_current_chart_even_after_it_is_deleted():
    controller(r"""
(async()=>{
 await land();const savedProduct=copyRoute(),link=url();
 assert.equal(link.searchParams.get('time_product'),productId);assert.equal(link.searchParams.get('time_result'),result);
 restore({place:link.searchParams.get('place'),q:link.searchParams.get('q'),...datedRoute(link.searchParams)});
 view=null;timeData=null;let pending=loadView();assert.equal(requests.at(-1).url,'/api/history/land');requests.at(-1).resolve(landing());await pending;
 assert.equal(view.center.id,productId);assert.equal(route.timeQ,'old question');
 restore(savedProduct);pending=returnHistoricalSystem();assert.equal(requests.at(-1).url,'/api/history/system');requests.at(-1).resolve(systemPage());await pending;
 assert.equal(view.center.id,system.id);assert.deepEqual(view.nodes,[product]);assert.equal(route.pan.x,47);assert.equal(route.zoom,1.8);assert.equal(route.timeLanding,null);
 assert.deepEqual(view.breadcrumbs.map(n=>n.id),[galaxy.id,system.id]);
 const savedSystem=copyRoute();view=null;timeData=null;restore(savedSystem);pending=loadView();requests.at(-1).resolve(systemPage());await pending;
 assert.equal(route.timeCursor,session+':0');assert.equal(view.nodes[0].label,'Lantern before rename');
 assert.ok(requests.every(r=>r.url.startsWith('/api/history/')));
})().catch(e=>{console.error(e);process.exitCode=1});
""")


@pytest.mark.parametrize('change', ['session', 'product', 'group', 'result', 'query', 'date', 'failure'])
def test_failed_or_wrong_landing_preserves_existing_view_and_route(change):
    code = {
        'session': "response.session_id='c'.repeat(64);",
        'product': "response.product={...product,id:'planet:other'};",
        'group': "response.group_id='foreign-group';",
        'result': "response.result_key='c'.repeat(64);",
        'query': "response.query='different';",
        'date': "response.as_of='2026-01-01T00:00:00Z';",
        'failure': '',
    }[change]
    controller(r"""
(async()=>{
 start();const original=copyRoute(),oldView=view,pending=landHistorical(productId),response=landing();CHANGE
 FAIL
 await pending;assert.deepEqual(route,original);assert.equal(view,oldView);assert.equal(timeData.action,'system');assert.equal(saved.length,0);assert.match(navigatorStatus.textContent,/History unavailable/);assert.equal(flown.length,0);assert.equal(mapStatus.textContent,'Historical view unavailable · saved journey retained');
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace('CHANGE', code).replace('FAIL', "requests.at(-1).reject(Error('Saved result missing'));" if change == 'failure' else 'requests.at(-1).resolve(response);'))


@pytest.mark.parametrize('cancel', ['route', 'draft', 'newer', 'inactive'])
def test_stale_landing_cannot_replace_newer_journey_or_draft(cancel):
    code = {
        'route': "route.place='system:elsewhere';",
        'draft': "input.value='unsent new thought';",
        'newer': 'loadTicket++;',
        'inactive': 'active=false;',
    }[cancel]
    controller(r"""
(async()=>{
 start();const oldView=view,pending=landHistorical(productId);CANCEL
 requests.at(-1).resolve(landing());await pending;assert.equal(view,oldView);assert.equal(saved.length,0);assert.equal(route.timeLanding,null);
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace('CANCEL', code))


def test_saved_system_map_preserves_direct_child_pagination_and_rejects_bad_pin():
    controller(r"""
(async()=>{
 const data=systemPage();for(let i=0;i<100;i++)data.nodes.push({...product,id:'planet:'+i});
 data.nodes.push({...group,parent_id:product.id});route.offset=80;
 let pending=loadView();requests.at(-1).resolve(data);await pending;
 assert.equal(view.total,101);assert.equal(view.offset,80);assert.equal(view.nodes.length,21);assert.equal(view.more,false);assert.ok(view.nodes.every(n=>n.parent_id===system.id));
 route.timeCursor='invalid-saved-pin';view=null;timeData=null;pending=loadView();assert.equal(requests.at(-1).body.cursor,'invalid-saved-pin');requests.at(-1).reject(Error('Invalid cursor'));await pending;
 assert.equal(route.timeCursor,'invalid-saved-pin');assert.equal(view,null);assert.match(caption.textContent,/No present-day chart/);assert.ok(requests.every(r=>r.url==='/api/history/system'));
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_failed_back_to_historical_map_closes_reader_before_request_finishes():
    controller(r"""
(async()=>{
 await land();readerVisible=true;const oldTicket=readerTicket;route.sourceRead=null;
 const pending=loadView();assert.equal(readerVisible,false);assert.ok(readerTicket>oldTicket);
 requests.at(-1).reject(Error('Saved history unavailable'));await pending;
 assert.equal(readerVisible,false);assert.equal(route.timeCursor,session+':0');
 assert.ok(requests.every(r=>r.url==='/api/history/land'));
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_home_and_saved_ancestor_never_repin_or_escape_to_present():
    controller(r"""
(async()=>{
 await land();const original=copyRoute(),count=requests.length;
 travelTo('galaxy:owner');assert.deepEqual(route,original);assert.equal(requests.length,count);assert.equal(flown.length,0);assert.match(notices.at(-1),/saved address/);
 const pending=travelTo('system:orchard');requests.at(-1).resolve(systemPage());await pending;
 assert.equal(route.place,'system:orchard');assert.equal(route.timeCursor,session+':0');
 const before=copyRoute();travelTo('galaxy:owner');assert.deepEqual(route,before);assert.equal(flown.length,0);
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    source=(ROOT/'navcom_space.js').read_text()
    assert "button('⌂ Galaxy',()=>travelTo('galaxy:owner')" in source
