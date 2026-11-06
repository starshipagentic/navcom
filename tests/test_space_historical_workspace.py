"""Dated leaf arrivals show only the existing pinned source result in the main space."""
from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


def program(body, *, render_map=False):
    helpers = js_between("function arrivalWorkspace(", "function shipArrivalRecord(")
    helpers += js_between("function sourceRef(", "function sourceShell(")
    helpers += js_between("function historicalApplication(", "function historicalPresentAddress(")
    helpers += js_between("function timeLabel(", "function renderTimeBar(")
    if render_map:
        helpers += js_between("function renderMap(", "function renderFooter(")
    run_js(DOM + helpers + r"""
const art=()=>el('span',{},'Pinned art'),pathRow=path=>el('code',{},path),opened=[];
const openSource=(ref,origin)=>opened.push({ref,origin});
const placeKind=n=>n.kind,placeBriefing=()=>null;
const shipArrivalWorkspace=()=>el('section',{},'Current ship workspace');
const scope={},input={scrollIntoView(){},focus(){}};const remember=()=>{throw Error('Arrival must not write history')};
let route={place:'historical-app:job:app',timeAt:'2026-09-01T12:00:00Z',timeCursor:'a'.repeat(64)+':0',timeQ:'',
 timeLanding:{product:'historical-app:job:app',group:'',resultKey:'saved-result'},q:'old live query',zoom:2,pan:{x:61,y:-40},selected:''};
const sourcePin=(path,line=1)=>({source_id:'revision-id',relative_path:path,line,history:'revision-id',snapshot:'b'.repeat(64),published:1777710000});
const file=i=>({path:'apps/lantern/'+i+'.py',relative_path:'apps/lantern/'+i+'.py',bytes:120+i,source_ref:sourcePin('apps/lantern/'+i+'.py')});
let timeData={action:'land',center:{id:route.place,kind:'planet',label:'Lantern',application_root:'apps/lantern',
 description:'A committed forecasting experiment.',identity_basis:'committed_native_application',historical_identity:{kind:'derived_application'}},
 product:{id:route.place},group_id:null,result_key:'saved-result',cursor:route.timeCursor,session_id:'a'.repeat(64),
 query:'',as_of:route.timeAt,commit:'c'.repeat(40),snapshot:{id:'revision-id',source_id:'revision-id',repository:'/recorded/field-suite'},
 files:Array.from({length:6},(_,i)=>file(i)),allowed_paths:Array.from({length:6},(_,i)=>file(i).path),coverage:{complete:true},evidence:{concept_hits:[],text_hits:[]}};
let view={...timeData,nodes:[],total:0,offset:0};
const byClass=(root,cls)=>walk(root).filter(node=>String(node.attrs.class||'').split(' ').includes(cls));
""" + body)


def test_historical_leaf_shows_all_six_files_and_opens_exact_snapshot_without_requests():
    program(r"""
const before=structuredClone(route),saved=structuredClone(timeData),panel=arrivalWorkspace(view),output=words(panel);
assert.match(output,/APPLICATION CANDIDATE/);assert.match(output,/Lantern/);assert.match(output,/2026-09-01 12:00:00 UTC/);
assert.ok(output.includes(timeData.commit));assert.ok(output.includes('/recorded/field-suite'));assert.match(output,/Application path\s+apps\/lantern/);
const files=byClass(panel,'space-historical-file');assert.equal(files.length,6);assert.match(output,/Committed files · 6/);
assert.equal(buttons(panel,'Ask about this place').length,0);assert.equal(buttons(panel,'Back').length,0);
assert.equal(buttons(panel,'Return to present').length,0,'Existing navigation actions remain in one rail');
files[3].onclick({currentTarget:files[3]});
assert.deepEqual(opened,[{origin:files[3],ref:{source:'revision-id',path:'apps/lantern/3.py',history:'revision-id',snapshot:'b'.repeat(64),published:1777710000,line:1,focus:1,limit:80}}]);
assert.deepEqual(calls,[]);assert.deepEqual(route,before);assert.deepEqual(timeData,saved);
""")


def test_native_query_matches_keep_exact_scope_and_delegate_existing_pinned_reader():
    program(r"""
route.timeQ=timeData.query='DecisionGraph';
const hit={path:'apps/lantern/2.py',line:34,text:'DecisionGraph links retained decisions.',source_ref:sourcePin('apps/lantern/2.py',34)};
timeData.evidence={concept_hits:[hit],text_hits:[{...hit,text:'Native text match.'},
 {...hit,path:'outside.py',text:'Out of scope marker',source_ref:sourcePin('outside.py')},
 {...hit,text:'Wrong snapshot history marker',source_ref:{...hit.source_ref,history:'other-revision'}}]};
const panel=arrivalWorkspace(view),output=words(panel),cards=byClass(panel,'space-result');
assert.match(output,/Matches for “DecisionGraph”/);assert.match(output,/Ranked code clues · 1/);assert.match(output,/Code and documents · 1/);
assert.equal(cards.length,2);assert.ok(!output.includes('Out of scope marker'));assert.ok(!output.includes('Wrong snapshot history marker'));
press(cards[0],'Open source →');assert.deepEqual(opened[0].ref,{source:'revision-id',path:hit.path,history:'revision-id',snapshot:'b'.repeat(64),published:1777710000,line:22,focus:34,limit:80});
assert.deepEqual(calls,[]);
""")


def test_mismatched_saved_landing_never_substitutes_present_description_or_files():
    program(r"""
const original=structuredClone(timeData),checks=[data=>data.center.id='other',data=>data.product.id='other',data=>data.group_id='other',
 data=>data.result_key='new-result',data=>data.cursor='d'.repeat(64)+':0',data=>data.query='later query',data=>data.as_of='2026-10-02'];
for(const alter of checks){timeData=structuredClone(original);alter(timeData);const panel=arrivalWorkspace({...view,center:{...view.center,description:'Forbidden current fallback'}});
 assert.match(words(panel),/Saved committed workspace unavailable/);assert.ok(!words(panel).includes('Forbidden current fallback'));assert.equal(buttons(panel).length,0);}
assert.deepEqual(calls,[]);assert.deepEqual(opened,[]);
""")


def test_native_district_leaf_retains_product_pin_and_only_its_member_files():
    program(r"""
route.timeLanding.group='historical-district:access';timeData.group_id=route.timeLanding.group;
timeData.center={id:timeData.group_id,kind:'district',label:'Permission checks',parent_id:timeData.product.id};
timeData.files=timeData.files.slice(2,4);timeData.allowed_paths=timeData.files.map(file=>file.path);view={...timeData,nodes:[]};
const before=structuredClone(route),panel=arrivalWorkspace(view);assert.match(words(panel),/COMMITTED DISTRICT Permission checks/);
assert.equal(byClass(panel,'space-historical-file').length,2);assert.ok(!words(panel).includes('apps/lantern/0.py'));
byClass(panel,'space-historical-file')[1].onclick({currentTarget:null});assert.equal(opened[0].ref.path,'apps/lantern/3.py');
assert.equal(opened[0].ref.history,'revision-id');assert.deepEqual(route,before);assert.deepEqual(calls,[]);
""")


def test_more_files_are_paged_from_saved_result_and_partial_coverage_remains_explicit():
    program(r"""
timeData.files=Array.from({length:27},(_,i)=>file(i));timeData.allowed_paths=timeData.files.map(f=>f.path);timeData.coverage.complete=false;
const before=structuredClone(route),panel=arrivalWorkspace(view),more=byClass(panel,'space-historical-more')[0];
assert.equal(byClass(panel,'space-historical-file').length,12);assert.equal(more.hidden,false);assert.match(words(panel),/Coverage is partial/);
more.onclick();assert.equal(byClass(panel,'space-historical-file').length,24);assert.equal(more.hidden,false);
more.onclick();assert.equal(byClass(panel,'space-historical-file').length,27);assert.equal(more.hidden,true);
assert.deepEqual(calls,[]);assert.deepEqual(route,before);
""")


def test_render_map_enters_historical_workspace_only_for_leaf_landing():
    program(r"""
function surface(){const node=el('div');node.style={};node.classes=new Set();node.classList={toggle:(name,on)=>on?node.classes.add(name):node.classes.delete(name),add:name=>node.classes.add(name),remove:name=>node.classes.delete(name)};return node;}
const stage=surface(),places=surface(),orbit=surface(),universe=surface(),orientation=surface(),empty=surface();
const geometry={width:800,height:600},fleetMap=null;
const projectedNodes=nodes=>nodes.map(n=>({n,x:200,y:200})),retainMapLayout=p=>p,renderBerths=()=>{},svgEl=(tag,attrs)=>el(tag,attrs);
const destinationQualifier=()=>'',setSelection=()=>{},travelTo=()=>{},showBeaconName=()=>{},selectedNode=()=>{},focusMapNode=()=>{};
const pageRange=()=>'',renderRadar=()=>{},renderOverviewLabels=()=>{},initializeCamera=()=>{},transform=()=>{};
renderMap();assert.ok(stage.classes.has('space-arrival'));assert.equal(byClass(empty,'space-historical-file').length,6);
assert.equal(stage.attrs['aria-label'],'Committed source workspace for Lantern');
route.timeLanding=null;view={center:{id:'system:field',kind:'system',label:'Field'},nodes:[],total:0};renderMap();assert.ok(!stage.classes.has('space-arrival'));
assert.equal(byClass(empty,'space-historical-file').length,0,'A dated system without a landing keeps the chart');
route.timeAt='';view={center:{id:'planet:present',kind:'planet',label:'Present',description:'Current description'},nodes:[],total:0};renderMap();
assert.ok(stage.classes.has('space-arrival'));assert.match(words(empty),/Current description/);assert.equal(byClass(empty,'space-historical-file').length,0);
assert.deepEqual(calls,[]);
""", render_map=True)
