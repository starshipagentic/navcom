"""Committed application candidates navigate as saved scopes, never current identities."""
from test_space_action_rail import DOM
from test_space_camera import ROOT, camera_program, js_between, run_js
from test_space_historical_landing import controller


APPLICATION = r"""
const app={id:'historical-app:'+ 'd'.repeat(64)+':'+ 'e'.repeat(24),parent_id:product.id,
 kind:'district',form:'application',label:'Orchard editor',historical_state:'committed',
 identity_basis:'committed_native_application',historical_identity:{kind:'derived_application',
 job_id:'d'.repeat(64),repository:'/fixture/orchard',commit:'old-head',tree:'old-tree',manifest:'LABS/trial/editor/package.json'},
 origin_scope_ids:[product.id],present_day_address:{id:product.id,kind:'moon',label:'Trial'},
 land_command:['navcom','history','land'],files:['LABS/trial/editor/main.js'],file_count:1,
 position:{x:25,y:24}};
"""


def test_moon_application_child_uses_own_landing_and_native_groups_keep_group_route():
    controller(APPLICATION + r"""
(async()=>{
 await land();product.kind='moon';timeData.nodes.push(app);view.nodes.push(app);
 const origin=structuredClone(route.timeLanding.origin);
 let pending=travelTo(app.id),request=requests.at(-1);
 assert.equal(request.url,'/api/history/land');assert.equal(request.body.within,app.id);
 assert.equal(request.body.group,null,'A derived application is not a native token group');
 request.resolve({...landing(),product:app,center:app,nodes:[app],files:[{path:app.files[0],source_ref:{source_id:'revision-id',relative_path:app.files[0],history:'revision-id',snapshot:'artifact-sha',line:1}}]});await pending;
 assert.equal(route.timeLanding.product,app.id);assert.equal(route.timeLanding.group,'');
 assert.deepEqual(route.timeLanding.origin,origin);assert.equal(view.center.label,app.label);
 assert.ok(!JSON.stringify(route).includes('artifact-sha'));
 // Back to the saved moon, then a real native group still uses the moon ID.
 await land();pending=travelTo(groupId);request=requests.at(-1);
 assert.equal(request.body.within,productId);assert.equal(request.body.group,groupId);
 request.resolve(landing(true));await pending;assert.equal(view.center.id,groupId);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_derived_district_is_reachable_from_dated_inventory_and_current_address_is_not_invented():
    controller(APPLICATION + r"""
(async()=>{
 start();timeData.nodes.push(app);let pending=travelTo(app.id),request=requests.at(-1);
 assert.equal(request.body.within,app.id);assert.equal(request.body.group,null);
 request.resolve({...landing(),product:app,center:app,nodes:[app]});await pending;
 assert.equal(view.center.id,app.id);assert.equal(flown.length,0);
 const missing={...app};delete missing.present_day_address;
 assert.equal(historicalPresentAddress(missing),null,'Never fly a historical-only ID in the current catalog');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def display_controller(checks):
    functions = js_between('function historicalApplication(', 'function historicalRequest(')
    functions += js_between('function renderTimeResults(', 'function pageOffset(')
    functions += js_between('function renderLandingSelection(', 'function renderLandingResults(')
    source = (ROOT / 'navcom_space.js').read_text()
    functions += source[source.index('function sourceRef('):].splitlines()[0]
    run_js(DOM + r"""
Object.defineProperty(El.prototype,'classList',{get(){return {add(){},remove(){},toggle(){}}}});
const inspector=el('section'),timeResults=el('section'),opened=[],landed=[],flown=[];
const product={id:'moon:trial',kind:'moon',label:'Trial'},view={center:{id:'system:orchard'}};
let route={timeAt:'2025-04-01',timeQ:'',timeLanding:null},timeBusy=false;
let timeData={nodes:[],repositories:[],coverage:{},result_key:'b'.repeat(64)};
const timeLabel=String,recordedTime=String,evidenceText=JSON.stringify,cliLine=()=>'',setSelection=()=>{},
 landHistorical=(...args)=>landed.push(args),fly=(...args)=>flown.push(args),
 openSource=ref=>opened.push(ref),returnHistoricalSystem=()=>{},input={focus(){}};
""" + APPLICATION + functions + checks)


def test_inventory_and_inspector_use_exact_historical_repository_and_truthful_return():
    display_controller(r"""
timeData.nodes=[app];timeData.repositories=[{job_id:app.historical_identity.job_id,scope_ids:[product.id],data:{repository:'/fixture/orchard',commit:'old-head',tree:'old-tree',snapshot:{id:'old-revision',source_id:'old-source'}}}];
renderTimeResults();assert.match(words(timeResults),/Orchard editor/);assert.match(words(timeResults),/Application candidate/);
assert.match(words(timeResults),/Present navigation address: Trial/);assert.ok(!words(timeResults).includes('undefined'));
renderTimeSelection(app);assert.match(words(inspector),/COMMITTED APPLICATION CANDIDATE/);
press(inspector,app.files[0]);assert.deepEqual(opened,[{source:'old-source',path:app.files[0],line:1,limit:80,focus:1,history:'old-revision',snapshot:'',published:undefined}]);
press(inspector,'Land in this dated application →');assert.deepEqual(landed,[[app.id]]);
press(inspector,'Return to present address →');assert.equal(flown[0][0],product.id);assert.equal(flown[0][5],true);
// An explicit job binding cannot fall through to an unrelated row with the same source path.
timeData.repositories[0].job_id='f'.repeat(64);assert.equal(historicalRepository(app),null);
timeData.repositories[0].job_id=app.historical_identity.job_id;timeData.repositories[0].data.commit='new-head';
inspector.replaceChildren();renderTimeSelection(app);assert.equal(buttons(inspector,app.files[0]).length,0);
// Older saved DTOs can use exact original scope membership, only at the same commit/tree.
delete timeData.repositories[0].job_id;timeData.repositories[0].data.commit='old-head';assert.ok(historicalRepository(app));
timeData.repositories.push(structuredClone(timeData.repositories[0]));assert.equal(historicalRepository(app),null,'Ambiguous receipts cannot supply file links');
""")


def test_landing_application_action_never_uses_group_id():
    display_controller(r"""
route.timeLanding={product:product.id};view.center=product;timeData.commit='old-head';
renderLandingSelection(app);press(inspector,'Land in this dated application →');assert.deepEqual(landed,[[app.id]]);
assert.match(words(inspector),/COMMITTED APPLICATION CANDIDATE/);
""")


def test_first_system_response_and_reload_share_population_without_moving_existing_camera():
    helpers = js_between('function historicalMap(', 'function historicalRequest(')
    helpers += js_between('function applySystemTime(', 'function renderTimeResults(')
    run_js(camera_program(r"""
let timeData=null;const places={children:[]},caption={},mapStatus={},names={};
let renders=0;const timeLabel=String,renderDestinationPager=()=>{},renderCrumbs=()=>{},renderFooter=()=>{};
function updateOverviewLabels(){}function showBeaconName(){}
function renderMap(){renders++;retainMapLayout(projectedNodes(view.nodes));}
""" + helpers + r"""
fixture(3);view.center={id:'system:orchard',kind:'system',position:{x:0,y:0}};view.offset=0;
for(const n of view.nodes)n.parent_id=view.center.id;
route.place=view.center.id;route.timeAt='2025-04-01';route.timeQ='login';route.selected=view.nodes[1].id;
retainMapLayout(projectedNodes(view.nodes));route.cameraReady=true;route.cameraScale=.7;route.zoom=1.6;route.pan={x:43,y:-21};
const old=structuredClone(route),points=structuredClone(route.chartLayout.points);
const derived={id:'historical-app:old',kind:'planet',parent_id:view.center.id,label:'Old console',historical_state:'committed',identity_basis:'committed_native_application',historical_identity:{kind:'derived_application'},position:{x:42,y:-11}};
timeData={center:view.center,nodes:[view.center,...view.nodes,derived]};applySystemTime();
assert.equal(renders,1);assert.ok(view.nodes.some(n=>n.id===derived.id));
for(const p of points)assert.deepEqual(route.chartLayout.points.find(n=>n.id===p.id),p);
assert.deepEqual(route.pan,old.pan);assert.equal(route.zoom,old.zoom);assert.equal(route.selected,old.selected);assert.equal(route.timeQ,old.timeQ);
assert.deepEqual(view.nodes,historicalMap(timeData,route).nodes,'The first response uses the same population as reload');
applySystemTime();assert.equal(renders,1,'Cached rerender cannot rebuild an unchanged map');
"""))


def test_return_to_present_system_forces_undated_route_but_preserves_back_origin():
    source = (ROOT / 'navcom_space.js').read_text()
    fresh = source[source.index('const fresh='):].splitlines()[0]
    functions = js_between('function historicalApplication(', 'function historicalRequest(')
    functions += js_between('function returnToPresent(', 'function renderTimeBar(')
    functions += js_between('function fly(', 'function followEvidence(')
    run_js(fresh + r"""
const assert=require('node:assert/strict');const no=()=>{},saved=[];
const system={id:'system:orchard',kind:'system',label:'Orchard'};
let route={...fresh(),place:'historical-app:old',timeAt:'2025-04-01',timeCursor:'a'.repeat(64)+':0',timeLanding:{product:'historical-app:old'},step:3};
const before=structuredClone(route),timeData={product:{id:route.place,identity_basis:'committed_native_application',historical_identity:{kind:'derived_application'},present_day_address:system}},view={nodes:[],breadcrumbs:[system]};
const carriedState=()=>null,voiceInput={cancel:no},activationEvent=null,document={},beginFlight=()=>null,remember=push=>saved.push({push,route:structuredClone(route)}),input={},scope={},results={classList:{add:no}},loadView=no,message=no;
let lastStep=3,searchResult={},innerWidth=1280;
""" + functions + r"""
returnToPresent();assert.equal(route.place,system.id);assert.equal(route.timeAt,'');assert.equal(route.timeCursor,'');assert.equal(route.timeLanding,null);
assert.deepEqual(saved[0].route,before);assert.equal(saved[1].push,true);assert.equal(route.step,4);
""")
