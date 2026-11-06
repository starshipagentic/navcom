"""Connections preserve pinned source identities and ignore stale navigation replies."""
from pathlib import Path
from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


ROOT = Path(__file__).resolve().parents[1]


def render_program(body):
    source = (ROOT / "navcom_space.js").read_text()
    helpers = js_between("function renderRelated(", "function renderShipCopies(")
    helpers += js_between("function relatedSourceRef(", "async function loadRelated(")
    helpers += source[source.index("function pathRow("):].splitlines()[0]
    helpers += source[source.index("function recordedTime("):].splitlines()[0]
    run_js(DOM + helpers + r"""
const panel=el('section'),node={id:'planet:lantern'},route={relatedQuery:'',relatedOffset:0};
const flights=[],reads=[];const fly=id=>flights.push(id),openSource=(...args)=>reads.push(args);
const closeRelated=()=>{},remember=()=>{},loadRelated=()=>{},cliLine=command=>el('code',{},command);
const data={declared_relations:[{kind:'declared_supersession',status:'declared',
 successor:{id:'planet:lantern',label:'Lantern',declared_id:'orchard.lantern'},
 predecessor:{id:'planet:beacon',label:'Beacon',declared_id:'orchard.beacon'},
 meaning:'Current recorded declaration. No replacement date, deployment state or historical ownership is inferred.',
 evidence:{type:'owner_declaration',declarations:[{path:'/work/lantern/.navcom-space.json',observed_at:1700000000,stale:false}],stale:false}}],
 families:[{label:'Lantern engine',parent_path:'/work/lantern/engines',members:[{label:'v1',relative_path:'engines/v1',retained_files:2,destination_ids:[],
 source_ref:{source_id:'retained',relative_path:'engines/v1/README.md',line:12,snapshot:'a'.repeat(64),published:123}}]}],
 references:[],source_offset:0,source_total:1,source_page_size:8,next_offset:null,cached:true,coverage:[]};
""" + body)


def test_declared_supersession_precedes_suggestions_and_flies_exact_endpoints():
    render_program(r"""
const before=structuredClone(data);renderRelated(panel,data,node);
const shown=words(panel);assert.ok(shown.indexOf('Lantern supersedes Beacon')<shown.indexOf('Lantern engine'));
assert.match(shown,/Current recorded declaration\. No replacement date/);
assert.match(shown,/Version families below are suggestions/);assert.match(shown,/not a replacement date/);
const provenance=walk(panel).find(n=>n.tag==='details'&&words(n.children[0])==='Declaration provenance');
assert.ok(provenance);assert.equal(provenance.hasAttribute('open'),false);assert.match(words(provenance),/\/work\/lantern\/\.navcom-space.json/);
press(panel,'Fly to Lantern →');press(panel,'Fly to Beacon →');assert.deepEqual(flights,['planet:lantern','planet:beacon']);
press(provenance,'Copy');assert.deepEqual(copied,['/work/lantern/.navcom-space.json']);
press(panel,'Read README.md');assert.deepEqual(reads[0][0],{source:'retained',path:'engines/v1/README.md',line:4,focus:12,limit:80,published:123,snapshot:'a'.repeat(64)});
assert.deepEqual(data,before);assert.deepEqual(calls,[]);
""")


def test_declaration_and_source_warnings_are_visible_without_promoting_diagnostics():
    render_program(r"""
data.declared_relations[0].evidence.stale=true;data.families=[];
data.declaration_diagnostics=[{code:'unresolved_target',declared_id:'orchard.lantern',target_declared_id:'orchard.missing',
 reason:'No recorded product owns orchard.missing.',paths:['/work/lantern/.navcom-space.json']}];
data.source_errors=['Retained native sources are unavailable.'];renderRelated(panel,data,node);
const shown=words(panel);assert.match(shown,/Declaration evidence is stale/);assert.match(shown,/unresolved_target: No recorded product owns orchard.missing/);
assert.match(shown,/Retained native sources are unavailable/);assert.equal(buttons(panel).filter(b=>words(b).startsWith('Fly to ')).length,2);
const warnings=walk(panel).filter(n=>n.attrs.class==='space-search-warning');assert.equal(warnings.length,3);
assert.ok(warnings.every(n=>n.tag!=='details'));assert.equal(walk(panel).filter(n=>n.tag==='strong'&&words(n).includes('supersedes')).length,1);
assert.deepEqual(calls,[]);
""")


def test_declaration_only_products_expose_the_existing_connections_action():
    rail = js_between("function placeRail(", "function renderSelection(")
    run_js(DOM + rail + r"""
const route={relatedPlace:''},railLines=[],opened=[];
const cliLine=command=>el('code',{},command.join(' ')),openRelated=node=>opened.push(node.id);
const base={id:'planet:lantern',kind:'planet',label:'Lantern',source_ids:[],
 commands:{related:['navcom','atlas','related','planet:lantern']}};
for(const declaration of [{declared_id:'orchard.lantern'},{product_declarations:[{relation:'supersedes',target:'orchard.beacon'}]},
 {evidence:[{type:'owner_declaration',path:'/work/lantern/.navcom-space.json'}]}]){
 const node={...base,...declaration},{rail:actions,used}=placeRail(node,true);
 assert.equal(buttons(actions,'Connections & versions').length,1);assert.ok(used.has('related'));
 assert.match(words(actions),/navcom atlas related planet:lantern/);press(actions,'Connections & versions');
}
assert.deepEqual(opened,['planet:lantern','planet:lantern','planet:lantern']);
assert.equal(buttons(placeRail(base,true).rail,'Connections & versions').length,0);
assert.deepEqual(calls,[],'Rendering the action does not inspect or harvest a source');
""")


def test_related_source_refs_preserve_snapshot_and_publication_for_exact_reads():
    helper = js_between("function relatedSourceRef(", "async function loadRelated(")
    run_js("const assert=require('node:assert/strict');\n" + helper + r"""
const original={source_id:'orchard',relative_path:'engines/v2/README.md',line:42,
 snapshot:'4d988f-published-artifact',published:1784583001.25};
assert.deepEqual(relatedSourceRef(original),{source:'orchard',path:'engines/v2/README.md',
 line:34,focus:42,limit:80,published:1784583001.25,snapshot:'4d988f-published-artifact'});
assert.equal(relatedSourceRef({...original,line:3}).line,1);
assert.equal(relatedSourceRef(null),null);
assert.equal(relatedSourceRef({source_id:'orchard'}),null);
assert.equal(relatedSourceRef({relative_path:'README.md'}),null);
assert.equal(original.line,42,'Opening a window cannot mutate the returned citation');
""")


def test_related_route_restores_query_source_page_and_camera_without_reinterpretation():
    source = (ROOT / "navcom_space.js").read_text()
    fresh = source[source.index("const fresh="):].splitlines()[0]
    restore = js_between("function restore(value)", "function setActive(")
    page = js_between("function pageOffset(", "function renderDestinationPager(")
    run_js("const assert=require('node:assert/strict');\n" + fresh + page + restore + r"""
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40,input={},scope={};let route=fresh();
const saved={...fresh(),place:'system:coast',selected:'planet:orchard',q:'matrix',local:false,
 relatedPlace:'planet:orchard',relatedQuery:'engine versions',relatedOffset:8,
 zoom:4.9,pan:{x:319,y:-214},cameraReady:true,cameraScale:.82,layoutVersion:2,
 chartLayout:{key:'system:coast|0',width:1530,height:1008,points:[{id:'planet:orchard',x:120,y:130}]},
 sourceRead:{source:'orchard',path:'engines/v2/README.md',snapshot:'pinned',published:123,line:12}};
restore(saved);assert.deepEqual(route,saved);
assert.equal(input.value,'matrix');assert.equal(scope.checked,false);
route.chartLayout.points[0].x=300;assert.equal(saved.chartLayout.points[0].x,120,'History geometry must be copied');
restore(saved);assert.equal(route.relatedQuery,'engine versions');assert.equal(route.relatedOffset,8);
""")


def test_connections_ignore_out_of_order_or_departed_place_responses_and_errors():
    load = js_between("async function loadRelated(", "function renderRelated(")
    reads = js_between("const reads=new Map();", "function historyPanel(")
    run_js("const assert=require('node:assert/strict');\n" + reads + load + r"""
let active=true,relatedTicket=0,route={relatedPlace:'planet:orchard',relatedQuery:'old',relatedOffset:0};
let selected={id:'planet:orchard'},view={published:123};
const requests=[],renders=[];
const panel={writes:0,replaceChildren(){this.writes++}},inspector={querySelector:()=>panel};
const el=(...args)=>args,button=(...args)=>args,closeRelated=()=>{},selectedNode=()=>selected;
const renderRelated=(...args)=>renders.push(args);
const api=url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}));
(async()=>{
 const old=loadRelated(selected);route.relatedQuery='new';const current=loadRelated(selected);
 requests[1].resolve({id:'new'});await current;
 requests[0].resolve({id:'old'});await old;
 assert.equal(renders.length,1);assert.equal(renders[0][1].id,'new','a late reply to an older query is not shown');
 assert.equal(new URL(requests[1].url,'http://localhost').searchParams.get('q'),'new');
 // A successful response cannot paint into a different selected destination.
 route.relatedQuery='departed';const departing=loadRelated(selected);selected={id:'planet:other'};
 requests[2].resolve({id:'departed'});await departing;assert.equal(renders.length,1);
 // Deactivated panels must also ignore late failures, not replace their previous contents.
 selected={id:'planet:orchard'};route.relatedQuery='failure';const failing=loadRelated(selected);
 const writesBefore=panel.writes;active=false;requests[3].reject(Error('late source failure'));await failing;
 assert.equal(panel.writes,writesBefore,'A late error cannot mutate a deactivated panel');
 // Reopening a new query after returning must still work normally.
 active=true;route.relatedQuery='back';const back=loadRelated(selected);
 requests[4].resolve({id:'back'});await back;assert.equal(renders.length,2);
 assert.equal(renders[1][1].id,'back');
 // Any other rail click re-renders the panel: the unchanged request is answered from memory.
 await loadRelated(selected);assert.equal(requests.length,5);assert.equal(renders.at(-1)[1].id,'back');
})().catch(error=>{console.error(error);process.exitCode=1});
""")
