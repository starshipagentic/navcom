"""Starbase berths are a stable presentation of the complete recorded fleet."""
from pathlib import Path

from test_space_camera import camera_program, js_between, run_js
from test_space_journey_continuity import flight_controller


FLEET = r"""
function fleetFixture(){
 const groups=[],assignments={},nodes=[];
 for(const [g,count]of [44,27,23,13].entries()){
  const members=[];
  for(let i=0;i<count;i++){
   const id='ship:'+g+':'+String(i).padStart(3,'0');members.unshift(id);
   assignments[id]={id:'berth:'+g,label:'Recorded group '+g,basis:'exact source',status:'recorded',family_key:'family:'+g+':'+Math.floor(i/5)};
   nodes.push({id,kind:'ship',label:'Vessel '+i,position:{x:i*3,y:i*5},berth:assignments[id]});
  }
  groups.push({id:'berth:'+g,label:g===3?'Unassigned context':'Recorded group '+g,basis:g===3?'no_grouped_context':'exact source',status:'recorded',members,count});
 }
 return {center:{id:'starbase:fixture',kind:'starbase',label:'Fixture dock',position:{x:17,y:31}},nodes,total:nodes.length,offset:0,
  fleet_layout:{version:1,base_id:'starbase:fixture',groups,assignments}};
}
const coords=points=>Object.fromEntries(points.map(p=>[p.n.id,{x:p.x,y:p.y}]));
"""


def test_full_member_geometry_survives_pages_filters_and_viewport_changes():
    project = js_between('function projectedNodes(', 'function renderMap(')
    run_js("const assert=require('node:assert/strict');\n" + project + FLEET + r"""
const PAGE_SIZE=80;let innerWidth=1440,geometry={},layoutNarrow=false;
const complete=fleetFixture(),original=JSON.stringify(complete);let view=complete;
const all=coords(projectedNodes(view.nodes)),world={...geometry};
for(const selected of [complete.nodes.slice(0,80),complete.nodes.slice(80),complete.nodes.filter((_,i)=>i%7===0)]){
 for(const width of [486,1440]){
  innerWidth=width;view={...complete,nodes:selected,offset:80};
  const positions=coords(projectedNodes(selected));assert.deepEqual(geometry,world);
  for(const [id,position]of Object.entries(positions))assert.deepEqual(position,all[id]);
  assert.equal(fleetMap.groups.reduce((sum,g)=>sum+g.visible,0),selected.length);
  assert.equal(fleetMap.groups.reduce((sum,g)=>sum+g.total,0),107);
 }
}
view={...complete,fleet_layout:{...complete.fleet_layout,groups:[...complete.fleet_layout.groups].reverse()}};
assert.deepEqual(coords(projectedNodes(complete.nodes.map(n=>({...n,label:'Renamed'})))),all);
assert.equal(JSON.stringify(complete),original,'Presentation must not mutate semantic positions, IDs, or assignments');
assert.equal(fleetMap.hub.x,geometry.width/2);assert.equal(fleetMap.hub.y,geometry.height/2);
""")


def test_berths_have_no_ship_region_or_hub_collisions_and_families_are_adjacent():
    project = js_between('function projectedNodes(', 'function renderMap(')
    run_js("const assert=require('node:assert/strict');\n" + project + FLEET + r"""
const PAGE_SIZE=80;let innerWidth=1440,geometry={},layoutNarrow=false,view=fleetFixture();
const points=projectedNodes(view.nodes),lookup=coords(points);
for(const [i,p]of points.entries())for(const q of points.slice(0,i))
 assert.ok(Math.abs(p.x-q.x)>=234||Math.abs(p.y-q.y)>=242,`${p.n.id} overlaps ${q.n.id}`);
for(const [i,g]of fleetMap.groups.entries()){
 for(const h of fleetMap.groups.slice(0,i))assert.ok(g.left+g.width<h.left||h.left+h.width<g.left||g.top+g.height<h.top||h.top+h.height<g.top);
 assert.ok(g.left+g.width<fleetMap.hub.x-220||g.left>fleetMap.hub.x+220||g.top+g.height<fleetMap.hub.y-180||g.top>fleetMap.hub.y+180);
 for(const [j,id]of g.members.entries()){
  const p=lookup[id];assert.ok(p.x-117>g.left&&p.x+117<g.left+g.width);assert.ok(p.y-121>g.top&&p.y+121<g.top+g.height);
  const previous=g.members[j-1];if(previous&&view.fleet_layout.assignments[previous].family_key===view.fleet_layout.assignments[id].family_key){
   const q=lookup[previous];assert.ok(Math.hypot(p.x-q.x,p.y-q.y)<=255+1e-8,'Related ships should occupy neighboring docking slots');
  }
 }
}
""")


def test_legacy_fleet_camera_migrates_once_and_back_reload_link_keep_the_journey():
    link = js_between('function url(){', '// A tab owns') + js_between('function linkCamera(', 'function timeKey(')
    run_js(camera_program(FLEET + link + r"""
const location={href:'http://127.0.0.1:9/?view=space'};
view=fleetFixture();route={...fresh(),place:view.center.id,q:'calibration',selected:view.nodes[18].id,
 timeAt:'2025-09-01',timeQ:'past question',cameraReady:true,cameraScale:.9,pan:{x:23,y:72},
 chartLayout:{key:view.center.id+'|0',width:1000,height:800,points:[]}};
const journey=()=>({place:route.place,q:route.q,selected:route.selected,timeAt:route.timeAt,timeQ:route.timeQ});
const before=journey(),points=retainMapLayout(projectedNodes(view.nodes));
assert.equal(route.cameraReady,false);assert.equal(route.cameraScale,null);assert.deepEqual(journey(),before);
initializeCamera(points);transform();assert.equal(route.zoom,1,'A fresh berth scene starts at the labeled fleet overview');
centerCamera(points[18].x,points[18].y,true);scale(1.2);const saved=structuredClone(route);
restore(saved);retainMapLayout(projectedNodes(view.nodes));initializeCamera(points);transform();
assert.deepEqual(route,saved,'Back/reload cannot migrate an already grouped saved camera a second time');
const copied=url();assert.equal(copied.searchParams.get('berths'),'fleet-berths-v1|starbase:fixture');
restore({...fresh(),place:view.center.id,...linkCamera(copied.searchParams)});
assert.equal(route.cameraReady,true);retainMapLayout(projectedNodes(view.nodes));initializeCamera(points);transform();
assert.ok(Math.abs(route.cameraScale/saved.cameraScale-1)<1e-4);assert.ok(Math.abs(route.pan.x-saved.pan.x)<=.5);
"""))


def test_region_controls_explain_basis_and_partial_counts_without_changing_selection():
    run_js(camera_program(FLEET + r"""
const el=(tag,attrs={},...children)=>{const e=new Element();e.attrs=attrs;e.children=children;return e;};
const button=(label,fn,attrs={})=>Object.assign(el('button',attrs,label),{click:fn});
const art=()=>new Element(),places=new Element(),orbit=new Element(),berthLabels=new Element(),berthDirectory=new Element();
const setSelection=()=>assert.fail('Focusing a berth must not select a ship');
view=fleetFixture();view.nodes=view.nodes.slice(80);route.q='calibration';route.selected=view.nodes[0].id;
const points=retainMapLayout(projectedNodes(view.nodes));renderBerths();initializeCamera(points);
assert.equal(places.children.length,1,'The actual starbase artwork is centered once');
assert.equal(places.children[0].style.left,geometry.width/2+'px');
assert.equal(berthItems.length,4);assert.equal(berthDirectory.children.length,5);
assert.ok(berthDirectory.children.at(-1).children[0].startsWith('Unassigned context'));
assert.deepEqual(berthDirectory.children.slice(1,-1).map(b=>b.children[0]),[...berthDirectory.children.slice(1,-1).map(b=>b.children[0])].sort());
const partial=fleetMap.groups.find(g=>g.visible<g.total),item=berthItems.find(i=>i.group.id===partial.id);
assert.ok(item.label.attrs.title.includes(partial.visible+' / '+partial.total+' ships shown'));
assert.ok(item.label.attrs['aria-label'].includes('exact source'));
// Suggestions expose exact context evidence, never an invented topic classifier.
assert.match(berthTitle({...partial,status:'suggested',basis:'cached_system_context'}),/Suggested grouping.*Recorded system or client-folder context/s);
assert.match(berthTitle({...partial,basis:'no_grouped_context'}),/general anchorage/);
assert.equal(berthCaption({visible:1,total:1}),'1 ship');
assert.equal(berthCaption({visible:0,total:1}),'0 / 1 ship shown');
berthItems=[];const selected=route.selected,query=route.q;focusBerth(partial.id);
assert.equal(route.selected,selected);assert.equal(route.q,query);assert.equal(route.cameraReady,true);
"""))
    css = (Path(__file__).resolve().parents[1] / 'navcom_space.css').read_text()
    assert '.space-berth-label strong{font:16px/' in css
    assert '.space-berth-label strong{font-size:14px}' in css


def test_starbase_artwork_stays_recognizable_at_overview_without_changing_world_geometry():
    run_js(camera_program(FLEET + r"""
view=fleetFixture();projectedNodes(view.nodes);
const before=structuredClone(fleetMap.groups),hub=new Element();fleetMap.hubElement=hub;
const orientation=new Element(),zoomTools=new Element(),mapStatus=new Element();
berthItems=fleetMap.groups.map(group=>({group,label:new Element()}));
const factor=()=>Number(hub.style.transform.match(/scale\(([^)]+)\)/)[1]);
updateBerthLabels({...cameraFrame(),scale:.08});assert.ok(320*.08*factor()>=90-1e-8);
updateBerthLabels({...cameraFrame(),scale:.82});assert.equal(factor(),1,'Readable zoom retains the artwork size');
updateBerthLabels({...cameraFrame(),scale:.001});assert.equal(factor(),8,'Compensation is bounded at extreme zoom');
assert.deepEqual(fleetMap.groups,before,'Artwork emphasis must not move ships or berth regions');
"""))


def test_focusing_a_two_ship_berth_keeps_both_readable_on_mobile():
    run_js(camera_program(FLEET + r"""
view=fleetFixture();view.nodes=view.nodes.slice(0,2);view.total=2;
view.fleet_layout.groups=[{...view.fleet_layout.groups[0],members:view.nodes.map(n=>n.id),count:2}];
const points=retainMapLayout(projectedNodes(view.nodes));initializeCamera(points);
focusBerth(fleetMap.groups[0].id);
for(const point of points){const screen=screenPoint(point.x,point.y),scale=cameraFrame().scale;
 assert.ok(scale>=.82-1e-8);assert.ok(screen.x-117*scale>0&&screen.x+117*scale<stage.clientWidth);
 assert.ok(screen.y-121*scale>0&&screen.y+121*scale<stage.clientHeight);
}
"""))


def test_new_berth_keeps_selected_or_nearest_retained_ship_on_its_screen_anchor():
    run_js(camera_program(FLEET + r"""
for(const selected of [true,false]){
 route=fresh();view=fleetFixture();let points=retainMapLayout(projectedNodes(view.nodes));initializeCamera(points);transform();
 const old=points[10];centerCamera(old.x,old.y,true);scale(1.2);
 route.selected=selected?old.n.id:'';route.q='calibration';route.timeAt='2025-09-01';route.timeQ='past';
 const before=screenPoint(old.x,old.y),scaleBefore=cameraFrame().scale;
 view.nodes.push({id:'ship:new',kind:'ship',label:'New vessel'});
 view.fleet_layout.groups.push({id:'berth:new',label:'New recorded group',members:['ship:new'],basis:'cached_system_context',status:'suggested',count:1});
 view.fleet_layout.assignments['ship:new']={family_key:'new'};view.total++;
 points=retainMapLayout(projectedNodes(view.nodes));initializeCamera(points);transform();
 const current=points.find(p=>p.n.id===old.n.id),after=screenPoint(current.x,current.y);
 near(after.x,before.x);near(after.y,before.y);near(cameraFrame().scale,scaleBefore);
 assert.equal(route.q,'calibration');assert.equal(route.timeAt,'2025-09-01');assert.equal(route.timeQ,'past');
 const saved=structuredClone(route);restore(saved);points=retainMapLayout(projectedNodes(view.nodes));initializeCamera(points);transform();
 assert.deepEqual(route,saved,'The new membership signature must make later restore a no-op');
}
"""))


def test_full_starbase_refetch_is_bounded_and_preserves_query_selection_and_date():
    flight_controller(FLEET + r"""
(async()=>{
 const complete=fleetFixture();route.place=complete.center.id;route.offset=80;route.q='calibration';route.timeAt='2025-09-01';route.timeQ='past';route.selected=complete.nodes[90].id;
 const before={...route},pending=loadView();
 requests[0].resolve({...complete,nodes:complete.nodes.slice(80),offset:80,more:false});await tick();
 assert.equal(requests.length,2);assert.equal(requests[1].url.searchParams.get('limit'),'1000');assert.equal(requests[1].url.searchParams.get('offset'),'0');
 requests[1].resolve({...complete,more:false,limit:1000});await pending;
 assert.equal(view.nodes.length,107);assert.equal(route.offset,0);
 for(const key of ['place','q','selected','timeAt','timeQ'])assert.equal(route[key],before[key]);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_superseded_full_fleet_fetch_cannot_replace_another_destination():
    flight_controller(FLEET + r"""
(async()=>{
 const complete=fleetFixture();route.place=complete.center.id;route.offset=80;
 const pending=loadView();requests[0].resolve({...complete,nodes:complete.nodes.slice(80),offset:80});await tick();
 const fleetRequest=requests[1];assert.equal(fleetRequest.url.searchParams.get('limit'),'1000');
 fly('planet:other');route.offset=160;route.q='new draft';input.value='new draft';
 fleetRequest.resolve(complete);await pending;
 assert.equal(route.place,'planet:other');assert.equal(route.offset,160);assert.equal(route.q,'new draft');
 assert.notEqual(view.center.id,complete.center.id);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_large_starbase_and_generic_place_keep_the_existing_pager():
    flight_controller(FLEET + r"""
(async()=>{
 const complete=fleetFixture();route.place=complete.center.id;
 let pending=loadView();requests[0].resolve({...complete,total:1001,nodes:complete.nodes.slice(0,80),more:true});await pending;
 assert.equal(requests.length,1);assert.equal(view.nodes.length,80);
 pending=loadView();requests[1].resolve({...complete,center:{...complete.center,kind:'system'},nodes:complete.nodes.slice(0,80),more:true});await pending;
 assert.equal(requests.length,2);assert.equal(view.nodes.length,80);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_invalid_or_foreign_fleet_layout_uses_generic_geography():
    project = js_between('function projectedNodes(', 'function renderMap(')
    run_js("const assert=require('node:assert/strict');\n" + project + FLEET + r"""
const PAGE_SIZE=80;let innerWidth=1440,geometry={},layoutNarrow=false,view=fleetFixture();
view.nodes=view.nodes.slice(0,20);view.fleet_layout.base_id='different-base';
const invalid=coords(projectedNodes(view.nodes));assert.equal(fleetMap,null);
delete view.fleet_layout;assert.deepEqual(coords(projectedNodes(view.nodes)),invalid);
for(const groups of [[null],[{id:'x',members:null}],[{id:'x',members:['ship:missing']}],[{id:'x',members:['same','same']}]] ){
 view={...fleetFixture(),fleet_layout:{version:1,base_id:'starbase:fixture',groups}};
 const points=projectedNodes(view.nodes);assert.equal(fleetMap,null);
 assert.ok(points.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
}
view=fleetFixture();delete view.fleet_layout.assignments;
assert.ok(projectedNodes(view.nodes).every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
""")
