"""Spatial camera keeps a readable view without changing destination geography."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def js_between(start, end):
    source = (ROOT / "navcom_space.js").read_text()
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


def run_js(script):
    if not shutil.which("node"):
        pytest.skip("Node required for bridge camera proof")
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr


def camera_program(checks):
    """Run the shipped camera/controller against a small DOM surface, not a replica."""
    source = (ROOT / "navcom_space.js").read_text()
    fresh = source[source.index("const fresh="):].splitlines()[0]
    project = js_between("function projectedNodes(", "function renderMap(")
    camera = js_between("function cameraFrame(", "stage.addEventListener('wheel'")
    restore = js_between("function restore(value)", "function setActive(")
    page = js_between("function pageOffset(", "function renderDestinationPager(")
    resize = js_between("function resizeCamera(", "new ResizeObserver(")
    harness = r"""
const assert=require('node:assert/strict');
class Element {
 constructor(){this.children=[];this.attributes={};this.listeners={};this.style={};this.dataset={};
  this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
 setAttribute(key,value){this.attributes[key]=value;if(key==='data-radar-place')this.dataset.radarPlace=value;}
 replaceChildren(...children){this.children=children}append(...children){this.children.push(...children)}
 querySelectorAll(){return this.children.filter(child=>child.dataset.radarPlace)}
 addEventListener(type,callback){(this.listeners[type]??=[]).push(callback)}
 fire(type,event={}){for(const callback of this.listeners[type]||[])callback(event)}
 getBoundingClientRect(){return {left:10,top:20,width:160,height:115}}
 focus(){this.focused=true}setPointerCapture(id){this.pointer=id}
}
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40;
let innerWidth=486,geometry={},layoutNarrow=false,route=fresh(),view={},lastCamera=null,active=true;
const stage=Object.assign(new Element(),{clientWidth:486,clientHeight:420});
const universe=new Element(),radar=new Element(),radarMap=new Element(),radarWindow=new Element();
const beaconName=new Element(),zoomLabel=new Element(),input={},scope={};
const records=[];let cancelled=0,scheduledSaves=0;
const cancelFlight=()=>cancelled++,remember=()=>records.push(JSON.parse(JSON.stringify(route)));
const saveSoon=()=>scheduledSaves++,selectedNode=()=>view.nodes?.find(n=>n.id===route.selected);
const svgEl=(tag,attrs)=>{const node=new Element();for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);return node};
function fixture(count){
 route=fresh();view={center:{position:{x:0,y:0}},total:count,
  nodes:Array.from({length:count},(_,i)=>({id:'planet:'+i,label:'Product '+i,
   position:{x:Math.cos(i*.7)*i*15,y:Math.sin(i*.7)*i*12}}))};
 return projectedNodes(view.nodes);
}
function screenPoint(x,y){const f=cameraFrame();return {x:f.cx+route.pan.x+(x-geometry.width/2)*f.scale,y:f.cy+route.pan.y+(y-geometry.height/2)*f.scale}}
function near(actual,expected,message){assert.ok(Math.abs(actual-expected)<1e-7,message||`${actual} != ${expected}`)}
function context(){const {zoom,pan,cameraReady,cameraScale,...rest}=route;return rest}
"""
    # fresh has no dependencies; the harness provides the actual DOM dependencies.
    return fresh + "\n" + harness + project + page + restore + camera + resize + checks


def test_world_geography_is_identical_on_narrow_and_desktop_and_dated_labels():
    project = js_between("function projectedNodes(", "function renderMap(")
    run_js("const assert=require('node:assert/strict');\n" + project + r"""
const PAGE_SIZE=80;
let innerWidth=1440,geometry={},layoutNarrow=false;
const stage={clientWidth:980,clientHeight:620};
let view={center:{position:{x:15,y:-30}},total:20};
const coordinates=points=>points.map(({n,x,y})=>({id:n.id,x,y}));
for(const count of [20,80]){
 view.total=count;
 const nodes=Array.from({length:count},(_,i)=>({id:'planet:'+i,label:'Product '+i,
  position:{x:Math.cos(i*.7)*i*15,y:Math.sin(i*.7)*i*12}}));
 innerWidth=1440;stage.clientWidth=980;
 const desktop=coordinates(projectedNodes(nodes)),world={...geometry};
 innerWidth=486;stage.clientWidth=486;
 assert.deepEqual(coordinates(projectedNodes(nodes)),desktop,
  'Viewport width must change the camera, not the destination geography');
 assert.deepEqual(geometry,world);
 assert.ok(geometry.height/geometry.width<2,'The map must not become an endless vertical grid');
 const historical=nodes.map(n=>({...n,label:'Earlier product name '+n.id}));
 assert.deepEqual(coordinates(projectedNodes(historical)),desktop,
  'Historical labels must retain current address positions');
 assert.equal(new Set(desktop.map(n=>n.id)).size,count);
}
""")


def test_initial_camera_is_readable_and_fit_is_an_explicit_persistent_overview():
    run_js(camera_program(r"""
for(const count of [20,80]){
 const points=fixture(count);route.selected=points.at(-1).n.id;
 route.q='How does login work?';route.timeAt='2025-09-01';route.timeQ='login';
 const before=context();initializeCamera(points);transform();
 assert.ok(cameraFrame().scale>=.82-1e-10,'Fresh framing must show readable labels');
 assert.ok(16*cameraFrame().scale>=13,'Mobile title text must not shrink to a few pixels');
 const selected=points.at(-1),screen=screenPoint(selected.x,selected.y);
 near(screen.x,stage.clientWidth/2);near(screen.y,stage.clientHeight/2);
 assert.deepEqual(context(),before,'Initial framing cannot clear query, date, or selected place');
 fit();
 const topLeft=screenPoint(0,0),bottomRight=screenPoint(geometry.width,geometry.height);
 assert.ok(topLeft.x>=0&&topLeft.y>=0);
 assert.ok(bottomRight.x<=stage.clientWidth&&bottomRight.y<=stage.clientHeight);
 assert.equal(stage.classes.has('space-overview'),true);
 const fitted=JSON.stringify(route);
 initializeCamera(points);transform();
 assert.equal(JSON.stringify(route),fitted,'Rerender must not undo an explicit Fit choice');
 assert.deepEqual(context(),before);
 scale(1000);near(cameraFrame().scale,2.5,'Zoom must have a bounded visual maximum');
}
"""))


def test_radar_moves_the_camera_to_world_coordinates_and_saves_once_per_gesture():
    run_js(camera_program(r"""
const points=fixture(80);route.selected=points[4].n.id;route.q='matrix';route.offset=80;
initializeCamera(points);renderRadar(points);transform();
const before=context();let prevented=0,stopped=0;
const event={clientX:10+160*.8,clientY:20+115*.2,pointerId:7,
 preventDefault:()=>prevented++,stopPropagation:()=>stopped++};
const recordsBefore=records.length;
radar.fire('pointerdown',event);
assert.equal(prevented,1);assert.equal(stopped,1,'Radar gesture must not also start stage dragging');
assert.equal(radar.focused,true);assert.equal(radar.pointer,7);
const target={x:geometry.width*.8,y:geometry.height*.2},position=screenPoint(target.x,target.y);
near(position.x,stage.clientWidth/2);near(position.y,stage.clientHeight/2);
assert.ok(cameraFrame().scale>=.82-1e-10);
near(Number(radarWindow.attributes.x)+Number(radarWindow.attributes.width)/2,target.x);
near(Number(radarWindow.attributes.y)+Number(radarWindow.attributes.height)/2,target.y);
assert.deepEqual(context(),before);
assert.equal(records.length,recordsBefore,'Do not write history for every pointer move');
radar.fire('pointerup');radar.fire('pointercancel');
assert.equal(records.length,recordsBefore+1,'A completed gesture saves the viewpoint once');
assert.ok(cancelled>0,'Direct camera input must interrupt an in-progress flight');
assert.equal(radarMap.querySelectorAll().filter(dot=>dot.classes.has('selected')).length,1);
// Dragging beyond the radar remains at the edge of the chart.
moveRadar({clientX:-100,clientY:1000});
near(screenPoint(0,geometry.height).x,stage.clientWidth/2);
near(screenPoint(0,geometry.height).y,stage.clientHeight/2);
"""))


def test_keyboard_focus_reveals_an_offscreen_destination_without_selecting_or_flying():
    run_js(camera_program(r"""
const points=fixture(80);initializeCamera(points);
route.q='matrix';route.selected=points[0].n.id;route.timeAt='2025-09-01';
const target=points.at(-1),node={style:{left:target.x+'px',top:target.y+'px'},dataset:{place:target.n.id}};
centerCamera(points[0].x,points[0].y,true);
const before=context(),recordsBefore=records.length;
focusMapNode(node);
const screen=screenPoint(target.x,target.y);
near(screen.x,stage.clientWidth/2);near(screen.y,stage.clientHeight/2);
assert.ok(cameraFrame().scale>=.82-1e-10);
assert.equal(beaconName.textContent,target.n.label,'The focused destination needs an unscaled name');
assert.deepEqual(context(),before,'Revealing a focused node must not select, fly, or alter search');
assert.equal(records.length,recordsBefore+1);
focusMapNode(node);
assert.equal(records.length,recordsBefore+1,'Already-visible focus must not move the camera again');
"""))


def test_back_restores_camera_exactly_and_legacy_layout_migrates_only_the_camera():
    run_js(camera_program(r"""
const points=fixture(80);initializeCamera(points);route.q='matrix';route.local=false;
route.offset=80;route.searchOffset=40;route.timeAt='2025-09-01';route.timeQ='login';
route.sourceRead={source:'fixture',path:'README.md',line:12};
centerCamera(points[10].x,points[10].y,true);scale(1.2);
const saved=JSON.parse(JSON.stringify(route));
route=fresh();restore(saved);initializeCamera(points);transform();
assert.deepEqual(route,saved,'Back must restore the exact pan, zoom, query, date, page, and source reader');
fit();const fitted=JSON.parse(JSON.stringify(route));
restore(fitted);initializeCamera(points);
assert.deepEqual(route,fitted,'Restoring an overview must not apply the new default framing again');
const legacy={...saved};delete legacy.layoutVersion;delete legacy.cameraReady;
restore(legacy);assert.equal(route.cameraReady,false);
const legacyContext=context();initializeCamera(points);
assert.deepEqual(context(),legacyContext,'Legacy layout migration cannot discard the journey');
assert.equal(route.cameraReady,true);assert.ok(cameraFrame().scale>=.82-1e-10);
"""))


def test_resize_preserves_readable_scale_and_world_center_without_reprojecting():
    run_js(camera_program(r"""
innerWidth=1440;stage.clientWidth=980;stage.clientHeight=620;
const points=fixture(80),world={...geometry};initializeCamera(points);
route.q='matrix';route.timeAt='2025-09-01';route.selected=points[13].n.id;
centerCamera(points[13].x,points[13].y,true);scale(1.2);
const before=context(),visualScale=cameraFrame().scale,pan={...route.pan};
const worldCenter=()=>{const f=cameraFrame();return {x:geometry.width/2-route.pan.x/f.scale,y:geometry.height/2-route.pan.y/f.scale}};
const center=worldCenter();
innerWidth=486;stage.clientWidth=486;stage.clientHeight=420;
const savesBefore=scheduledSaves;resizeCamera();
near(cameraFrame().scale,visualScale,'Narrow resizing cannot make the same labels unreadable');
near(worldCenter().x,center.x);near(worldCenter().y,center.y);
assert.deepEqual(geometry,world,'Resizing does not create a new layout');
assert.deepEqual(route.pan,pan);assert.deepEqual(context(),before);
assert.equal(scheduledSaves,savesBefore+1);
resizeCamera();assert.equal(scheduledSaves,savesBefore+1,'Unchanged observer reports must not churn saved state');
innerWidth=1440;stage.clientWidth=980;stage.clientHeight=620;resizeCamera();
near(cameraFrame().scale,visualScale);near(worldCenter().x,center.x);near(worldCenter().y,center.y);
assert.deepEqual(context(),before);
"""))


def test_new_publication_retains_known_addresses_and_screen_anchor_when_world_grows():
    run_js(camera_program(r"""
const initial=fixture(20);view.center.id='system:fixture';view.offset=0;
// A previously saved, full chart forces the new destinations to expand its bounds.
const known=initial.map((p,i)=>({...p,x:120+(i%5)*255,y:130+Math.floor(i/5)*252}));
route.chartLayout={key:'system:fixture|0',width:1275,height:1008,
 points:known.map(p=>({id:p.n.id,x:p.x,y:p.y}))};
const first=retainMapLayout(projectedNodes(view.nodes));initializeCamera(first);transform();
route.q='matrix';route.selected=first[8].n.id;centerCamera(first[8].x,first[8].y,true);
const before=new Map(first.map(p=>[p.n.id,{x:p.x,y:p.y,screen:screenPoint(p.x,p.y)}]));
const scaleBefore=cameraFrame().scale,oldSize={...geometry};
view.nodes.push(...[20,21].map(i=>({id:'planet:'+i,label:'New product '+i,position:{x:i*17,y:i*9}})));
view.total=22;
const updated=retainMapLayout(projectedNodes(view.nodes));initializeCamera(updated);transform();
assert.ok(geometry.width>oldSize.width||geometry.height>oldSize.height,'Fixture must exercise bounds expansion');
near(cameraFrame().scale,scaleBefore);
for(const p of updated){const old=before.get(p.n.id);if(!old)continue;
 near(p.x,old.x);near(p.y,old.y);
 const screen=screenPoint(p.x,p.y);near(screen.x,old.screen.x,'A cached update must not move an existing screen anchor');
 near(screen.y,old.screen.y,'A cached update must not move an existing screen anchor');
}
for(const added of updated.filter(p=>!before.has(p.n.id)))
 for(const other of updated.filter(p=>p.n.id!==added.n.id))
  assert.ok(Math.abs(added.x-other.x)>=234||Math.abs(added.y-other.y)>=242,'New destination overlaps an existing footprint');
assert.equal(route.q,'matrix');assert.equal(route.selected,first[8].n.id);
const saved=JSON.parse(JSON.stringify(route));
restore(saved);const returned=retainMapLayout(projectedNodes(view.nodes));initializeCamera(returned);transform();
assert.deepEqual(returned.map(p=>({id:p.n.id,x:p.x,y:p.y})),updated.map(p=>({id:p.n.id,x:p.x,y:p.y})));
assert.deepEqual(route.pan,saved.pan,'Back restores the expanded chart camera');
"""))
