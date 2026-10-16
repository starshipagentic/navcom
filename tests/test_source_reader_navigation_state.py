"""Returning from a source reader cannot replay over a newer search intent."""
from test_scoped_navigator_state import run_controller, section


HELPERS = section('async function loadView(', '\nlet geometry=')
HELPERS += section('function hideSource(', 'async function loadSource(')
HELPERS += section("window.addEventListener('popstate'", '\nfunction fly(')

SETUP = """
const PAGE_SIZE=80;
let loadTicket=0,sourceTicket=0,timeTicket=0,timeBusy=false,timeData=null,view=null;
let bootstrapAttempted=true,layoutNarrow=false,sourceReturn=null;
const voiceInput={cancel(){}},sourceDialog={open:true,close(){this.open=false}};
const hide=()=>{};
const cancelFlight=hide,renderCrumbs=hide,renderMap=hide,renderDestinationPager=hide,
 renderSelection=hide,renderFooter=hide,renderTimeBar=hide,arrive=hide,
 applySystemTime=hide,loadSystemTime=hide,message=hide,loadSource=hide;
const refresh={disabled:true};
const stage={setAttribute:hide,removeAttribute:hide},mapStatus={classList},empty={classList};
const heading={},caption={},names={galaxy:'Galaxy'};
const destinationPager={classList};
const before={...route,place:'',q:'find amber in Orchard',interpretedQ:'amber',
 searchWithin:'moon:orchard',searchPending:false,local:true,sourceRead:null,step:1};
route={...before,step:2,sourceRead:{source:'source:orchard',path:'core.py',openedStep:2}};
input.value=route.q;
let queuedBack=false;
const history={back(){queuedBack=true}};
const location={search:'?view=space'};
const restore=value=>{route={...value};input.value=route.q;scope.checked=route.local};
const setActive=value=>{active=value};
const events={};
const requests=[];let resolveExplore,resolveNavigate;
const api=url=>{
 const request=new URL(url,'http://localhost');requests.push(request);
 if(request.pathname==='/api/navigate')return new Promise(resolve=>{resolveNavigate=resolve});
 if(request.searchParams.get('action')==='explore')return new Promise(resolve=>{resolveExplore=resolve});
 return Promise.resolve({published:123,center:{id:'galaxy:owner',label:'Owner'},nodes:[],
  evidence:{sources:[{source_id:'global-unwanted'}],conversations:[{key:'unrelated'}]}});
};
const map={published:123,center:{id:'galaxy:owner',label:'Owner',kind:'galaxy'},nodes:[],offset:0,total:0};
const scoped={published:123,scope_status:'resolved',center:{id:'moon:orchard',label:'Orchard'},nodes:[],
 intent:{action:'search',within:'moon:orchard',query:'primitive'},
 evidence:{sources:[{source_id:'orchard-only'}],conversations:[]}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function startReturn(){
 closeSource();assert.equal(queuedBack,true);assert.equal(sourceDialog.open,false);
 events.popstate({state:{navcomSpace:before}});
 assert.equal(requests[0].searchParams.get('action'),'explore');
}
"""


def controller(body):
    # Register the actual event callback after the surrounding fixture exists.
    callback = HELPERS[HELPERS.index("window.addEventListener('popstate'"):]
    functions = HELPERS[:HELPERS.index("window.addEventListener('popstate'")]
    run_controller(SETUP + "\nconst window={addEventListener:(name,fn)=>events[name]=fn};\n" + callback + body,
                   helpers=functions)


def test_close_reader_then_submit_while_view_restores_keeps_new_scoped_request():
    controller("""
(async()=>{
 startReturn();
 input.value='find primitive in Orchard';const searching=search(true);
 assert.equal(requests[1].pathname,'/api/navigate');
 resolveExplore(map);await tick();
 assert.equal(requests.length,2,'Old map response must not start an unscoped evidence replay');
 resolveNavigate(scoped);await searching;
 assert.equal(route.searchWithin,'moon:orchard');assert.equal(route.interpretedQ,'primitive');
 assert.equal(searchResult,scoped);assert.equal(rendered,1);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_close_reader_then_clear_while_view_restores_does_not_revive_evidence():
    controller("""
(async()=>{
 startReturn();input.value='';await search(true);
 resolveExplore(map);await tick();
 assert.equal(requests.length,1);assert.equal(route.q,'');assert.equal(searchResult,null);
 assert.equal(rendered,0);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_restoring_view_does_not_submit_new_unsent_draft_as_literal_global_search():
    controller("""
(async()=>{
 startReturn();input.value='find primitive in Orchard';
 resolveExplore(map);await tick();
 assert.equal(requests.length,1,'Typing alone must not submit a replacement search');
 assert.equal(input.value,'find primitive in Orchard');
 assert.equal(route.q,'find amber in Orchard');assert.equal(route.searchWithin,'moon:orchard');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_settled_return_replays_original_scoped_search_without_reinterpreting():
    controller("""
(async()=>{
 startReturn();resolveExplore(map);await tick();
 assert.equal(requests.length,2);
 const request=requests[1];assert.equal(request.pathname,'/api/space');
 assert.equal(request.searchParams.get('within'),'moon:orchard');
 assert.equal(request.searchParams.get('q'),'amber');assert.equal(request.searchParams.get('evidence'),'1');
})().catch(error=>{console.error(error);process.exitCode=1});
""")
