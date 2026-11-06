"""Following evidence preserves the question and narrows only its replay scope."""
from test_space_action_rail import DOM
from test_space_camera import js_between, run_js
from test_space_journey_continuity import flight_controller


def test_evidence_by_place_control_keeps_original_question_and_retrieval_terms():
    renderer = js_between('function renderSearch(', 'async function changeSearchPage(')
    helper = js_between('function followEvidence(', '// Check before')
    run_js(DOM + helper + renderer + r"""
const classes={add(){},remove(){},toggle(){}};
Object.defineProperty(El.prototype,'classList',{get(){return classes}});
const results=el('section'),places={children:[]},navigatorStatus={};
const route={place:'system:one',q:'find calibration in this system',interpretedQ:'calibration',searchWithin:'system:one',local:true};
const flights=[],fly=(...args)=>flights.push(args);
const placeBriefing=()=>null,briefingHasEvidence=()=>false,cliLine=()=>'',pageRange=()=>'',renderCarriedMatches=()=>0;
const contentsPreview=()=>null,conversationCard=()=>'',evidenceCard=()=>'',pathRow=()=>'';
let searchResult={center:{id:'system:one',label:'One'},nodes:[],
 evidence:{sources:[],conversations:[],places:[{id:'district:calibration',label:'Calibration lab',has_evidence:true,concept_hits:2,text_hits:3,conversation_hits:1}]}};
renderSearch();press(results,'Calibration lab · 5 source matches · 1 conversations');
assert.equal(flights.length,1);
assert.equal(flights[0][0],'district:calibration');
assert.equal(flights[0][1],route.q,'Following matched evidence must keep the original question');
assert.equal(flights[0][4],'calibration','Replay terms remain separate from command-language input');
assert.equal(navigatorStatus.textContent,'Flying to Calibration lab with this search…');
route.searchWithin='district:calibration';
searchResult={center:{id:'district:calibration',label:'Calibration lab'},nodes:[],evidence:{sources:[],conversations:[]}};
renderSearch();assert.match(navigatorStatus.textContent,/Searched Calibration lab · 0 places, 0 source hits, 0 conversations/);
assert.ok(!navigatorStatus.textContent.includes('Searched One'));
""")


def test_evidence_flight_replays_in_exact_destination_and_back_retains_origin():
    flight_controller(r"""
(async()=>{
 route={...fresh(),place:'system:one',q:'find calibration in this system',interpretedQ:'calibration',searchWithin:'system:one',
  local:false,step:4,selected:'planet:b2b',searchOffset:40,zoom:2.1,pan:{x:31,y:-24},cameraReady:true,cameraScale:1.1};
 input.value=route.q;scope.checked=false;const before=structuredClone(route);
 navigatorStatus.textContent='Searched old scope · 72 source hits';
 followEvidence({id:'planet:b2b',label:'B2B'});
 assert.deepEqual(saved[0],{push:false,route:before},'Back must retain the complete origin before flight');
 assert.equal(route.place,'planet:b2b');assert.equal(route.q,before.q);assert.equal(input.value,before.q);
 assert.equal(route.interpretedQ,'calibration');assert.equal(route.searchWithin,'planet:b2b');
 assert.equal(route.local,true);assert.equal(scope.checked,true);assert.equal(route.searchOffset,0);
 assert.equal(route.step,5);assert.match(navigatorStatus.textContent,/Flying to B2B with this search/);
 explore().resolve(map);await tick();
 assert.equal(requests.length,2);const replay=requests[1];
 assert.equal(replay.url.pathname,'/api/space');assert.equal(replay.url.searchParams.get('action'),'search');
 assert.equal(replay.url.searchParams.get('within'),'planet:b2b');assert.equal(replay.url.searchParams.get('q'),'calibration');
 assert.equal(replay.url.searchParams.get('evidence'),'1');assert.equal(replay.url.searchParams.get('offset'),'0');
 const found={center:map.center,query:'calibration',nodes:[],evidence:{sources:[],conversations:[]}};
 replay.resolve(found);await tick();assert.equal(searchResult,found);assert.deepEqual(rendered,[found]);
 assert.ok(!navigatorStatus.textContent.includes('72 source hits'),'Finished replay cannot keep old scope counts');
 // Browser history restores the origin route saved by the shipped controller.
 route=structuredClone(saved[0].route);input.value=route.q;scope.checked=route.local;
 const returning=loadView();requests[2].resolve({center:{id:'system:one',kind:'system',label:'One'},nodes:[],total:0,offset:0});
 await returning;await tick();const originReplay=requests[3].url;
 assert.equal(originReplay.searchParams.get('within'),'system:one');assert.equal(originReplay.searchParams.get('q'),'calibration');
 assert.equal(originReplay.searchParams.get('offset'),'40');
 assert.equal(route.q,before.q);assert.equal(route.local,before.local);assert.deepEqual(route.pan,before.pan);
 assert.equal(route.zoom,before.zoom);assert.equal(route.selected,before.selected);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_plain_flight_still_starts_without_a_search():
    flight_controller(r"""
route={...fresh(),q:'calibration',interpretedQ:'calibration',searchWithin:'system:one'};
fly('planet:b2b');
assert.equal(route.q,'');assert.equal(route.interpretedQ,'');assert.equal(route.searchWithin,null);
""")
