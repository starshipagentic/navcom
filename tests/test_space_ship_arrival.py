"""Ship landings reuse chart/dossier records and existing actions, without probes."""
from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


def program(body):
    helpers = js_between("function evidenceText(", "function inspectionPanel(")
    helpers += js_between("function renderInspection(", "function renderPlaceInspection(")
    helpers += js_between("function renderShipCopies(", "function openStoredCopies(")
    helpers += js_between("function shipArrivalRecord(", "function renderMap(")
    run_js(DOM + helpers + r"""
const art=()=>el('span',{},'Recorded ship art'),pathRow=(path,label='Location')=>el('div',{class:'space-path'},label,el('code',{},path),button('Copy path',()=>copy(path)));
const cliLine=()=>el('code',{},'existing native command'),fly=id=>calls.push({fly:id}),remember=()=>calls.push('remember');
const closeInspection=()=>calls.push('close'),inspectShip=()=>calls.push('inspect');
const shipRecords=new Map();let active=true;
let route={place:'ship:working',q:'prior research',local:true,zoom:2,pan:{x:41,y:23},timeAt:'',selected:'',copiesPlace:''};
const n={id:'ship:working',kind:'ship',form:'working',label:'Northwind recovery',description:'Restore the paired weather notebook; historical runtime check remains incomplete.',
 physical:{host:'remote-fixture',path:'/Volumes/Field work/ships/northwind',availability:'unobserved'},source_roots:['/clients/coast/forecast'],
 readiness:{status:'unknown',recorded_state:'capture-passed',as_of:'2026-05-01T00:00:00Z',message:'Current readiness has not been checked.'},
 provenance:{basis:'Commission receipt',snapshot:'/fleet/record.json'},gaps:['Human takeover is unverified.'],
 commands:{inspect:['navcom','atlas','inspect','ship:working'],carried_context:['navcom','atlas','context','ship:working'],board_validate:['navcom','atlas','board','ship:working','--validate']},
 ship_links:[{id:'ship:archive',kind:'ship',form:'archive',label:'Northwind sealed copy',physical:{host:'local-fixture',path:'/archives/northwind'}}]};
let view={center:n,nodes:[]};const empty=el('div'),inspector=el('section');
const action=button('Read carried context',()=>{});action.focus=opts=>calls.push({focus:opts});
inspector.querySelector=()=>action;inspector.scrollIntoView=opts=>calls.push({scroll:opts});
const find=(node,cls)=>walk(node).find(x=>String(x.attrs.class||'').split(' ').includes(cls))||null;
empty.querySelector=selector=>find(empty,selector.slice(1));
const observed={center:{id:n.id},inspection:{ship_id:n.id,observed_at:1777680000,cached:true,
 physical:{host:n.physical.host,path:n.physical.path,availability:'unobserved',locality:'remote'},
 receiving:{mission:'A recorded recovery mission.',recorded_at:'2026-04-28T00:00:00Z',status:'historical',current_ready:null},
 captain:{status:'unobserved',route_recorded:true,route_validated:false,takeover_verified:false,viewpoint:{cwd:n.physical.path,thread:'native-fixture'}},
 context:{sessions:15,messages:220,providers:['claude'],recorded_at:'2026-04-26T00:00:00Z',receipt_path:'/fleet/context-receipt.json'},
 gaps:['Receiving must be checked separately.'],provenance:{receipt:{path:'/fleet/captain-receipt.json',identity_match:true}}}};
""" + body)


def test_working_ship_arrival_exposes_recorded_mission_full_location_and_linked_archive_without_io():
    program(r"""
const before=structuredClone(route),panel=shipArrivalWorkspace(view),output=words(panel);
assert.match(output,/Restore the paired weather notebook/);assert.match(output,/Current readiness unknown/);
assert.match(output,/capture-passed/);assert.match(output,/Human takeover is unverified/);
assert.match(output,/remote-fixture/);assert.ok(output.includes(n.physical.path));assert.ok(output.includes('/clients/coast/forecast'));
assert.match(output,/Contents and availability have not been read on arrival/);
assert.equal(buttons(panel,'Board ship').length,0,'Consequential actions remain in the existing review rail');
assert.deepEqual(calls,[]);assert.deepEqual(route,before);
press(panel,'Open stored copy: Northwind sealed copy →');assert.deepEqual(calls,[{fly:'ship:archive'}]);
assert.deepEqual(route,before,'The link delegates to existing fly rather than changing route fields itself');
press(panel,'Open ship actions ↓');assert.deepEqual(calls.slice(1),[{scroll:{block:'start',behavior:'instant'}},{focus:{preventScroll:true}}]);
""")


def test_archive_arrival_does_not_invent_inventory_or_make_unknown_location_copyable():
    program(r"""
const archive={id:'ship:archive',kind:'ship',form:'archive',label:'Northwind copy',physical:{host:'local-fixture'},commands:{carried_context:['navcom','atlas','context','ship:archive']}};
const panel=shipArrivalWorkspace({center:archive,nodes:[]}),output=words(panel);
assert.match(output,/STORED CONTEXT · SHIP ARCHIVE/);assert.match(output,/Captain boarding Not supported for archives/);
assert.match(output,/mission has not been recorded/);assert.match(output,/Location not recorded/);
assert.equal(buttons(panel,'Copy path').length,0);assert.ok(!output.includes('Sessions 0'));
assert.equal(buttons(panel).length,1,'Only the jump to existing ship actions is introduced');assert.deepEqual(calls,[]);
""")


def test_cached_dossier_shows_exact_historical_context_and_separate_readiness_without_refresh():
    program(r"""
shipRecords.set(n.id,observed);const before=structuredClone(route),panel=shipArrivalWorkspace(view),output=words(panel);
assert.match(output,/A recorded recovery mission/);assert.match(output,/Sessions 15/);assert.match(output,/Messages 220/);
assert.ok(output.includes(recordedTime('2026-04-26T00:00:00Z')));assert.ok(output.includes('/fleet/context-receipt.json'));
assert.match(output,/Current application ready Not checked/);assert.match(output,/Resume route validated Not verified/);
assert.match(output,/Takeover verified Not verified/);assert.equal(buttons(panel,'↻ Refresh observation').length,0);
assert.equal(buttons(panel,'Close').length,0);assert.deepEqual(calls,[]);assert.deepEqual(route,before);
shipRecords.set(n.id,{...observed,center:{id:'ship:other'}});assert.ok(!words(shipArrivalWorkspace(view)).includes('Sessions 15'));
shipRecords.set(n.id,{...observed,inspection:{...observed.inspection,ship_id:'ship:other'}});assert.ok(!words(shipArrivalWorkspace(view)).includes('Sessions 15'));
""")


def test_explicit_inspection_updates_only_the_current_matching_undated_ship_workspace():
    program(r"""
empty.append(shipArrivalWorkspace(view));const panel=find(empty,'space-arrival-dossier'),before=structuredClone(route);
updateShipArrival(n,observed);assert.match(words(panel),/Sessions 15/);assert.deepEqual(route,before);assert.deepEqual(calls,[]);
const stable=words(panel),changed={...observed,inspection:{...observed.inspection,context:{sessions:999}}};
route.timeAt='2026-01-01';updateShipArrival(n,changed);assert.equal(words(panel),stable);route.timeAt='';
view={center:{id:'ship:other'},nodes:[]};updateShipArrival(n,changed);assert.equal(words(panel),stable);
view={center:n,nodes:[{id:'ship:child'}]};updateShipArrival(n,changed);assert.equal(words(panel),stable);
view={center:n,nodes:[]};active=false;updateShipArrival(n,changed);assert.equal(words(panel),stable);active=true;
updateShipArrival(n,{...changed,center:{id:'ship:other'}});assert.equal(words(panel),stable);
updateShipArrival(n,{...changed,inspection:{...changed.inspection,ship_id:'ship:other'}});assert.equal(words(panel),stable);
assert.deepEqual(calls,[]);
""")
