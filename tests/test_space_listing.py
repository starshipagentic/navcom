"""Navigator lists preserve their kind/scope and never become phrase searches."""
from pathlib import Path

import pytest

from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


def program(body):
    code = (Path(__file__).resolve().parents[1] / "navcom_space.js").read_text()
    helpers = js_between("const fresh=", "\nlet route=")
    helpers += code[code.index("const GROUPINGS="):].splitlines()[0]
    helpers += js_between("function pageOffset(", "function renderDestinationPager(")
    helpers += js_between("function renderListing(", "form.addEventListener('submit'")
    helpers += js_between("function restore(value)", "function setActive(")
    helpers += js_between("function url(){", "// A tab owns")
    # Execute the actual URL fallback object shared by popstate, not a test copy.
    start = code.index("restore(event.state?.navcomSpace||{") + len("restore(event.state?.navcomSpace||")
    linked = code[start:code.index(");", start)]
    helpers += "\nfunction linkedRoute(p){return " + linked + ";}\n"
    run_js(DOM + helpers + r"""
Object.defineProperty(El.prototype,'classList',{get(){if(!this._classes){const set=this._classes=new Set();this._classList={add:n=>set.add(n),remove:n=>set.delete(n),toggle:(n,on)=>on?set.add(n):set.delete(n),contains:n=>set.has(n)};}return this._classList;}});
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40;let active=true,searchTicket=0,lastStep=0,searchResult=null;
let route={...fresh(),place:'system:orchard',zoom:2,pan:{x:60,y:-28},cameraReady:true,cameraScale:1.4};
const input=Object.assign(el('input'),{value:'list planets',maxLength:500}),scope={checked:true};
const results=el('section'),searchPanel=el('section'),navigatorStatus=el('p'),places=el('div');
let view={center:{id:'system:orchard',label:'Orchard'},nodes:[{id:'moon:existing',position:{x:33,y:77}}]};
const saved=[],errors=[],flights=[],dated=[];
const copyRoute=()=>structuredClone(route),remember=(push=false)=>saved.push({push,route:copyRoute()}),fail=e=>errors.push(e.message);
const placeKind=n=>n.kind,contentsPreview=()=>null,placeBriefing=()=>null,briefingHasEvidence=()=>false;
const cliLine=(command,label)=>el('code',{'aria-label':label},command),pathRow=path=>el('code',{},path),evidenceText=String;
const fly=(...args)=>flights.push(args),goBack=()=>false,carriedParam=()=>null,datedRoute=()=>({}),linkCamera=()=>({});
const searchHistoricalLanding=q=>dated.push({land:q}),setTime=(at,q,options)=>dated.push({at,q,options});
const location={href:'http://localhost/?view=space'},landingState=x=>x,carriedState=x=>x;
const first=()=>({action:'list',listing_kind:'planets',published:123,center:{id:'system:orchard',label:'Orchard'},
 nodes:[{id:'planet:amber',kind:'planet',label:'Amber',description:'Saved product description',position:{x:45,y:90}}],
 total:42,offset:0,limit:40,more:true,list_command:'navcom atlas list planets --within system:orchard',
 cli_command:'navcom atlas navigate "list planets" --within system:orchard',
 intent:{action:'list',kind:'planets',query:'',within:'system:orchard'}});
const page=()=>({...first(),intent:undefined,offset:40,nodes:[{id:'planet:cobalt',kind:'planet',label:'Cobalt'}],more:false,
 cli_command:'navcom atlas list planets --within system:orchard --offset 40',list_command:'navcom atlas list planets --within system:orchard --offset 40'});
""" + body)


def test_navigator_list_is_not_evidence_and_only_fly_changes_location():
    program(r"""
(async()=>{
 replies['/api/navigate']=first();const before=structuredClone(view),camera={zoom:route.zoom,pan:{...route.pan}};
 await search(true);assert.equal(calls.length,1);assert.equal(new URL(calls[0].path,'http://localhost').pathname,'/api/navigate');
 assert.equal(route.q,'list planets');assert.equal(route.interpretedQ,'');assert.equal(route.listingKind,'planets');assert.equal(route.searchWithin,'system:orchard');
 assert.match(words(results),/Products in Orchard/);assert.ok(!words(results).includes('Place listing'));assert.ok(!words(results).includes('Listed in Orchard'));
 assert.equal(words(results).split(first().list_command).length-1,1);assert.ok(!words(results).includes(first().cli_command));assert.match(words(results),/Saved product description/);
 assert.ok(!words(results).includes('No evidence'));assert.ok(!words(results).includes('source hits'));assert.match(navigatorStatus.textContent,/Listed 1–1 of 42 products in Orchard/);
 assert.deepEqual(view,before);assert.equal(route.place,'system:orchard');assert.deepEqual({zoom:route.zoom,pan:route.pan},camera);assert.deepEqual(flights,[]);
 press(results,'Fly to Amber →');assert.deepEqual(flights,[['planet:amber']]);assert.equal(calls.length,1);assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_list_paging_reload_url_and_back_preserve_kind_scope_and_camera():
    program(r"""
(async()=>{
 replies['/api/navigate']=first();replies['/api/space']=page();await search(true);const firstState=copyRoute(),chart=structuredClone(view);
 scope.checked=false;route.local=false;await changeSearchPage(40);
 const paging=new URL(calls[1].path,'http://localhost').searchParams;
 assert.equal(paging.get('action'),'list');assert.equal(paging.get('kind'),'planets');assert.equal(paging.get('within'),'system:orchard');
 assert.equal(paging.get('offset'),'40');assert.equal(paging.get('limit'),'40');assert.equal(paging.has('q'),false);assert.equal(paging.has('evidence'),false);
 assert.match(words(results),/Cobalt/);assert.equal(route.searchOffset,40);const secondState=copyRoute(),link=url();
 assert.equal(link.searchParams.get('listing_kind'),'planets');assert.equal(link.searchParams.get('search_within'),'system:orchard');
 assert.equal(link.searchParams.get('search_offset'),'40');assert.equal(link.searchParams.get('q'),'list planets');
 restore(linkedRoute(link.searchParams));await search(false);
 const reload=new URL(calls.at(-1).path,'http://localhost').searchParams;
 assert.equal(reload.get('action'),'list');assert.equal(reload.get('kind'),'planets');assert.equal(reload.get('offset'),'40');assert.equal(reload.has('q'),false);
 replies['/api/space']={...first(),intent:undefined};restore(firstState);await search(false);assert.equal(route.searchOffset,0);assert.match(words(results),/Amber/);
 replies['/api/space']=page();restore(secondState);await search(false);assert.equal(route.searchOffset,40);assert.match(words(results),/Cobalt/);
 assert.equal(route.place,'system:orchard');assert.deepEqual(route.pan,{x:60,y:-28});assert.equal(route.cameraScale,1.4);assert.deepEqual(view,chart);assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_empty_listing_uses_count_and_scope_instead_of_failed_evidence_text():
    program(r"""
(async()=>{
 replies['/api/navigate']={...first(),listing_kind:'moons',nodes:[],total:0,more:false,intent:{action:'list',kind:'moons',query:'',within:'system:orchard'}};
 await search(true);assert.match(words(results),/Experiments in Orchard/);assert.match(words(results),/No experiments are listed in Orchard/);
 assert.ok(!words(results).includes('No evidence'));assert.ok(!words(results).includes('Conversations'));assert.match(navigatorStatus.textContent,/0 of 0 experiments in Orchard/);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


@pytest.mark.parametrize("change", ["publication", "kind", "scope"])
def test_changed_page_rejects_new_generation_or_scope_without_losing_previous_list(change):
    program(r"""
(async()=>{
 replies['/api/navigate']=first();await search(true);const previous=searchResult,before=copyRoute(),changed=page();
 CHANGE
 replies['/api/space']=changed;await changeSearchPage(40);assert.equal(searchResult,previous);assert.deepEqual(route,before);
 assert.equal(errors.length,1);assert.match(words(results),/Amber/);assert.ok(!words(results).includes('Cobalt'));
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace("CHANGE", {"publication": "changed.published=456;", "kind": "changed.listing_kind='ships';",
                           "scope": "changed.center={id:'system:other',label:'Other'};"}[change]))


def test_clear_cancels_late_page_and_new_typed_search_discards_list_mode():
    program(r"""
(async()=>{
 replies['/api/navigate']=first();await search(true);let done;replies['/api/space']=()=>new Promise(resolve=>done=resolve);
 const pending=changeSearchPage(40);press(results,'Clear');done(page());await pending;
 assert.equal(route.listingKind,'');assert.equal(route.q,'');assert.equal(searchResult,null);assert.ok(results.classList.contains('hidden'));
 input.value='find matrix';replies['/api/navigate']={intent:{action:'search',query:'matrix',within:'system:orchard'},nodes:[],center:first().center};
 await search(true);assert.equal(route.listingKind,'');assert.equal(route.interpretedQ,'matrix');assert.match(navigatorStatus.textContent,/Searched/);
 assert.equal(new URL(calls.at(-1).path,'http://localhost').pathname,'/api/navigate');assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_historical_queries_keep_existing_handlers_and_do_not_dispatch_listing():
    program(r"""
(async()=>{
 route.timeAt='2026-09-01';await search(true);assert.deepEqual(dated,[{at:'2026-09-01',q:'list planets',options:{keepSession:true}}]);
 route.timeLanding={product:'planet:old'};await search(true);assert.deepEqual(dated.at(-1),{land:'list planets'});assert.deepEqual(calls,[]);
})().catch(e=>{console.error(e);process.exitCode=1});
""")
