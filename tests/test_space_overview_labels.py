"""The shipped label planner keeps Fit legible without changing world geography."""
import re

from test_space_camera import ROOT, camera_program, js_between, run_js


PLAN = js_between('function overviewLabelPlan(', 'function renderOverviewLabels(')


def test_visible_empty_or_error_state_hides_old_interactive_overview_labels():
    # A rejected chart request clears world nodes while retaining the stage DOM.
    # This higher-specificity state rule must suppress its old overlay too.
    css = (ROOT / 'navcom_space.css').read_text()
    selector = '.space-stage:has(> .space-empty:not(.hidden)) .space-overview-labels'
    rule = re.search(re.escape(selector) + r'\s*\{([^}]+)\}', css)
    assert rule, 'The visible empty/error state must override the Fit label layer'
    declarations = dict(item.strip().split(':', 1) for item in rule[1].split(';') if item.strip())
    assert declarations['visibility'].strip() == 'hidden'
    assert declarations['pointer-events'].strip() == 'none'


def test_overview_names_fit_without_overlapping_each_other_art_or_controls():
    run_js("const assert=require('node:assert/strict');\n" + PLAN + r"""
for(const [width,height] of [[486,387],[390,300]]){
 const items=Array.from({length:10},(_,i)=>{
  const x=width*(.15+(i%4)*.23),y=height*(.32+Math.floor(i/4)*.24);
  return {id:'place:'+i,label:i===0?'An unfamiliar long product name':'Product '+i,
   x,y,width:i===0?105:72,height:i===0?40:24,
   icon:{left:x-12,top:y-12,width:24,height:24},priority:false};
 });
 const controls=[{left:8,top:8,width:145,height:54},
  {left:width-110,top:8,width:102,height:67},
  {left:width-140,top:height-42,width:132,height:34}];
 const before=JSON.stringify(items),result=overviewLabelPlan(items,width,height,controls);
 assert.equal(result.placements.length,10,'A small overview should name every destination');
 const intersects=(a,b)=>a.left<b.left+b.width&&a.left+a.width>b.left&&a.top<b.top+b.height&&a.top+a.height>b.top;
 for(const [i,label]of result.placements.entries()){
  assert.ok(label.left>=8&&label.top>=8&&label.left+label.width<=width-8&&label.top+label.height<=height-8);
  assert.ok(![...controls,...items.map(item=>item.icon),...result.placements.slice(0,i)].some(other=>intersects(label,other)));
 }
 assert.equal(JSON.stringify(items),before,'Label planning cannot move or rewrite destinations');
 assert.deepEqual(overviewLabelPlan([...items].reverse(),width,height,controls),result,
  'Input order cannot scramble labels between equivalent chart responses');
}
""")


def test_dense_overview_declutters_instead_of_shrinking_or_truncating_names():
    run_js("const assert=require('node:assert/strict');\n" + PLAN + r"""
const items=Array.from({length:80},(_,i)=>({id:'place:'+i,label:'Exact unabridged product '+i,
 x:28+i%10*44,y:88+Math.floor(i/10)*34,width:120,height:40,
 icon:{left:20+i%10*44,top:80+Math.floor(i/10)*34,width:16,height:16},priority:i===55}));
const before=JSON.stringify(items),result=overviewLabelPlan(items,486,387);
assert.ok(result.placements.length<80,'Crowded names must not all be forced into the same space');
assert.ok(result.placements.length>0);
assert.equal(result.placements[0].id,'place:55','Selection gets the first valid name position');
for(const label of result.placements){assert.equal(label.width,120);assert.equal(label.height,40);}
assert.equal(JSON.stringify(items),before,'The exact name and measured text dimensions are never shortened');
""")


def test_selected_name_updates_without_camera_or_query_changes():
    run_js(camera_program(overview_harness() + r"""
const points=fixture(3);labels(points);initializeCamera(points);transform();
route.q='existing scoped evidence';const original=universe.style.transform;
route.selected=points[1].n.id;showBeaconName(points[1].n);
assert.equal(overviewItems[1].label.classes.has('selected'),true);
assert.equal(beaconName.textContent,points[1].n.label);
route.selected=points[2].n.id;showBeaconName(points[2].n);
assert.equal(overviewItems[1].label.classes.has('selected'),false);
assert.equal(overviewItems[2].label.classes.has('selected'),true);
route.selected='';showBeaconName(null);
assert.ok(overviewItems.every(item=>!item.label.classes.has('selected')));
assert.equal(universe.style.transform,original);
assert.equal(route.q,'existing scoped evidence');
"""))


def overview_harness():
    return r"""
const document={activeElement:null},orientation=new Element(),zoomTools=new Element(),mapStatus=new Element();
const overviewLabels=new Element(),overviewLeaders=new Element();
stage.getBoundingClientRect=()=>({left:0,top:0,width:stage.clientWidth,height:stage.clientHeight});
for(const control of [orientation,radar,zoomTools,mapStatus])control.getBoundingClientRect=()=>({left:0,top:0,width:0,height:0});
function labels(points,width=78,height=24){overviewItems=points.map(point=>{
 const label=new Element();label.getBoundingClientRect=()=>({width,height});
 const button={offsetWidth:200,offsetHeight:210,
  firstElementChild:{offsetLeft:80,offsetTop:50,offsetWidth:40,offsetHeight:40}};
 return {...point,label,button,line:new Element()};
});}
"""


def test_fresh_small_chart_uses_fit_only_when_actual_measured_names_all_fit():
    run_js(camera_program(overview_harness() + r"""
const points=fixture(3);labels(points);
const before=JSON.stringify(points);initializeCamera(points);transform();
assert.equal(route.zoom,1,'First entry should reveal the whole small chart when every full name fits');
assert.equal(overviewLabels.dataset.visible,'3');
assert.equal(JSON.stringify(points),before);
assert.ok(overviewItems.every(item=>item.label.hidden===false));
// Text too large to fit is not clipped or scaled down to force an overview.
const crowded=fixture(20);labels(crowded,600,70);initializeCamera(crowded);transform();
assert.ok(cameraFrame().scale>=.82-1e-10);
"""))


def test_saved_camera_bypasses_first_entry_framing_and_explicit_fit_stays_saved():
    run_js(camera_program(overview_harness() + r"""
const points=fixture(3);labels(points);initializeCamera(points);transform();
route.pan={x:23,y:-17};route.zoom=1.4;transform();
route.q='an existing question';route.selected='planet:1';const saved=JSON.stringify(route);
for(const item of overviewItems)item.label.getBoundingClientRect=()=>assert.fail('Saved camera was reevaluated as first entry');
initializeCamera(points);assert.equal(JSON.stringify(route),saved);
labels(points);fit();const fitted=JSON.stringify(route);initializeCamera(points);
assert.equal(JSON.stringify(route),fitted);assert.equal(route.q,'an existing question');
assert.equal(route.selected,'planet:1');
"""))


def test_historical_overview_and_beacon_use_the_active_name_then_restore_present():
    historical = js_between('function applySystemTime(', 'function renderTimeResults(')
    run_js(camera_program(overview_harness() + historical + r"""
const points=fixture(3);points[0].n.label='Modern Orchard';points[0].n.kind='planet';labels(points);
const places=new Element(),caption=new Element(),names={planet:'Product'},timeLabel=value=>value;
let timeData=null;
for(const item of overviewItems){
 const worldName={textContent:item.n.label},clue={textContent:''};
 Object.assign(item.button,{dataset:{place:item.n.id},classList:new Element().classList,
  querySelector:selector=>selector==='strong'?worldName:clue,
  attributes:{'aria-label':'Product: '+item.n.label+'. Inspect destination.'},
  setAttribute(key,value){this.attributes[key]=value},getAttribute(key){return this.attributes[key]}});
 places.append(item.button);
 // Real layout reads happen after the active text is synchronized.
 item.label.getBoundingClientRect=()=>({width:Math.min(132,(item.label.textContent||'').length*5),height:item.label.textContent?.length>25?40:24});
}
initializeCamera(points);transform();route.selected=points[0].n.id;
const camera={zoom:route.zoom,pan:{...route.pan},transform:universe.style.transform},coordinates=JSON.stringify(points);
route.timeAt='2025-04-01T00:00:00Z';
timeData={nodes:[{id:points[0].n.id,label:'Original Orchard Research Laboratory',current_label:'Modern Orchard',historical_state:'committed',committed_at:'2025-03-01',description:'Dated repository name'}]};
applySystemTime();
assert.equal(overviewItems[0].label.textContent,'Original Orchard Research Laboratory');
assert.match(overviewItems[0].label.attributes['aria-label'],/Original Orchard Research Laboratory.*Committed historical state/);
assert.match(overviewItems[0].label.title,/Dated repository name/);
showBeaconName(points[0].n);assert.equal(beaconName.textContent,'Original Orchard Research Laboratory');
assert.equal(overviewItems[0].label.getBoundingClientRect().height,40,'Longer historical names are remeasured');
assert.match(overviewItems[1].label.attributes['aria-label'],/Current address; historical content not established/);
// Returning to present rebuilds the world buttons from the live chart.
route.timeAt='';timeData=null;
for(const item of overviewItems){item.button.querySelector('strong').textContent=item.n.label;item.button.setAttribute('aria-label','Product: '+item.n.label+'. Inspect destination.');item.button.title=item.n.label;}
transform();
assert.equal(overviewItems[0].label.textContent,'Modern Orchard');
assert.equal(beaconName.textContent,'Modern Orchard');
assert.doesNotMatch(overviewItems[0].label.attributes['aria-label'],/historical/);
assert.deepEqual({zoom:route.zoom,pan:route.pan,transform:universe.style.transform},camera);
assert.equal(JSON.stringify(points),coordinates,'Names must not mutate the current catalog or world positions');
"""))
