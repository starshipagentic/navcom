"""Shipped flight/history controllers preserve keyboard and in-flight searches."""
import pytest

from test_space_camera import js_between as section, run_js


def test_forward_survives_back_reload_and_new_branch_discards_old_tail():
    helpers = section('function restoreJourney(', 'function saveSoon(')
    run_js("const assert=require('node:assert/strict');\n" + helpers + r"""
const STORE='journey-test',storage=new Map();
let journeyId='',route={step:0,place:''},lastStep=0,active=true,view=null;
const sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
const localStorage={setItem(){}},back={},forward={},url=()=>'',copyRoute=()=>structuredClone(route);
const entries=[null];let cursor=0;
const history={get state(){return entries[cursor]},
 replaceState(value){entries[cursor]=structuredClone(value)},
 pushState(value){entries.splice(cursor+1);entries.push(structuredClone(value));cursor++;}};
function backOne(){cursor--;route=structuredClone(history.state.navcomSpace);remember();}
function reload(){journeyId='';lastStep=0;restoreJourney(history.state);remember();}
function push(place){route={step:route.step+1,place};lastStep=route.step;remember(true);}
restoreJourney(history.state);remember();const firstJourney=journeyId;
push('system:one');push('planet:two');push('district:three');
assert.equal(forward.disabled,true);assert.equal(entries.length,4);
backOne();assert.equal(route.step,2);assert.equal(forward.disabled,false);
reload();assert.equal(journeyId,firstJourney);assert.equal(lastStep,3);
assert.equal(forward.disabled,false,'Reload must preserve the actual forward branch');
backOne();reload();assert.equal(route.step,1);assert.equal(forward.disabled,false);
push('planet:new-branch');assert.equal(entries.length,3);assert.equal(cursor,2);
assert.equal(lastStep,2);assert.equal(forward.disabled,true);
backOne();reload();assert.equal(lastStep,2,'The discarded step 3 cannot survive a new branch');
assert.equal(forward.disabled,false);cursor++;route=structuredClone(history.state.navcomSpace);reload();
assert.equal(route.place,'planet:new-branch');assert.equal(forward.disabled,true);
// An unrelated new entry must not inherit another journey's high-water mark.
entries.push(null);cursor++;route={step:0,place:''};restoreJourney(null);assert.notEqual(journeyId,firstJourney);
remember();assert.equal(lastStep,0);assert.equal(forward.disabled,true);
""")


def test_forward_does_not_claim_the_end_when_tab_storage_is_unavailable():
    helpers = section('function restoreJourney(', 'function saveSoon(')
    run_js("const assert=require('node:assert/strict');\n" + helpers + r"""
const STORE='journey-test';let journeyId='',lastStep=0,route={step:1,place:'system:one'},active=true,view=null;
const sessionStorage={getItem(){throw Error('Storage unavailable')},setItem(){throw Error('Storage unavailable')}};
const localStorage={setItem(){}},back={},forward={},url=()=>'',copyRoute=()=>({...route});
const history={state:{navcomJourney:{id:'existing-journey'}},replaceState(value){this.state=value},pushState(value){this.state=value}};
restoreJourney(history.state);remember();
assert.equal(lastStep,null);assert.equal(forward.disabled,false,'Unknown forward availability is not a proved end');
route.step++;remember(true);assert.equal(lastStep,2);assert.equal(forward.disabled,true,'A new push is a known branch end');
""")


def flight_controller(body):
    helpers = section('const fresh=', '\nlet route=')
    helpers += section('function placeKind(', '\nconst roles=')
    helpers += section('const button=', '\nconst svgEl=')
    helpers += section('function fly(', 'function cancelFlight(')
    helpers += section('async function loadView(', '\nlet geometry=')
    helpers += section('async function search(push=', "form.addEventListener('submit'")
    harness = r"""
const assert=require('node:assert/strict');
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40;
const classList={add(){},remove(){},toggle(){}};
function element(tag='DIV'){return {tagName:tag,attrs:{},value:'',isConnected:true,classList,
 append(){},replaceChildren(){},querySelectorAll(){return []},setAttribute(){},removeAttribute(){},
 focus(){document.activeElement=this},scrollIntoView(){}};}
const el=(tag,attrs={})=>Object.assign(element(tag.toUpperCase()),{attrs});
const document={body:element('BODY'),activeElement:null};document.activeElement=document.body;
let route=fresh(),active=true,activationEvent=null,lastStep=0,searchResult=null;
let loadTicket=0,searchTicket=0,timeTicket=0,timeBusy=false,timeData=null;
let bootstrapAttempted=true,layoutNarrow=false,innerWidth=1440;
const origin=element('BUTTON'),other=element('BUTTON');
const input=Object.assign(element('INPUT'),{maxLength:500}),scope={checked:true};
const stage=element(),results=element(),searchPanel=element(),mapStatus=element(),empty=element();
const heading={},caption={},navigatorStatus={},refresh={disabled:true};
const actionDialog={open:false},sourceDialog={open:false},reducedMotion={matches:true};
const destinationPager=element(),places={children:[]},names={galaxy:'Galaxy',planet:'Product'};
const voiceInput={cancel(){},active:()=>false};
const no=()=>{},hideSource=no,loadSource=no,cancelFlight=no,renderCrumbs=no,renderMap=no,
 renderDestinationPager=no,renderFooter=no,renderTimeBar=no,arrive=no,applySystemTime=no,
 loadSystemTime=no,message=no,setTime=no,refreshChart=no,rendered=[];
const fail=error=>{throw error},carriedState=x=>x;
let removeFocusOnRender=false;
const renderSelection=()=>{if(document.activeElement===origin||removeFocusOnRender){
 document.activeElement.isConnected=false;document.activeElement=document.body;}};
const renderSearch=()=>{rendered.push(searchResult);navigatorStatus.textContent='Searched '+route.q;};
const saved=[],remember=(push=false)=>saved.push({push,route:structuredClone(route)}),copyRoute=()=>structuredClone(route);
let movement=null;const beginFlight=()=>movement;
let focusCalls=0;stage.focus=()=>{focusCalls++;document.activeElement=stage};
let view={center:{id:'system:one',kind:'system'},nodes:[{id:'planet:b2b',kind:'planet'}],breadcrumbs:[]};
const map={center:{id:'planet:b2b',kind:'planet',label:'B2B'},nodes:[],total:0,offset:0};
const requests=[];
const api=url=>new Promise(resolve=>requests.push({url:new URL(url,'http://localhost'),resolve}));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function travel(detail=0){document.activeElement=origin;const control=button('Fly',()=>fly('planet:b2b'));
 control.attrs.onclick({detail,currentTarget:origin});assert.equal(activationEvent,null);}
function explore(){return requests.find(r=>r.url.searchParams.get('action')==='explore')}
function navigation(){return requests.find(r=>r.url.pathname==='/api/navigate')}
"""
    run_js(helpers + harness + body)


def test_keyboard_flight_focuses_arrival_after_render_but_pointer_flight_does_not():
    flight_controller(r"""
(async()=>{
 travel(0);assert.equal(focusCalls,0,'Do not move keyboard focus while the new chart is still loading');
 explore().resolve(map);await tick();assert.equal(focusCalls,1);assert.equal(document.activeElement,stage);
 requests.length=0;origin.isConnected=true;focusCalls=0;
 travel(1);explore().resolve(map);await tick();assert.equal(focusCalls,0,'Desktop pointer flight keeps its current behavior');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize('interaction', ['draft', 'other_control', 'other_map_node', 'dialog'])
def test_keyboard_arrival_does_not_steal_newer_focus_or_an_unsent_draft(interaction):
    changes = {
        'draft': "input.value='A newer unsent question';document.activeElement=input;",
        'other_control': 'document.activeElement=other;',
        'other_map_node': 'document.activeElement=other;removeFocusOnRender=true;',
        'dialog': 'actionDialog.open=true;',
    }
    flight_controller(r"""
(async()=>{
 travel();CHANGE
 explore().resolve(map);await tick();assert.equal(focusCalls,0);
 assert.equal(requests.length,1,'Arrival must not submit an unsent draft');
 if(input.value)assert.equal(input.value,'A newer unsent question');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE', changes[interaction]))


@pytest.mark.parametrize('order', ['chart_first', 'search_first', 'animation_last'])
def test_search_submitted_during_flight_keeps_query_scope_and_result_in_every_response_order(order):
    flight_controller(r"""
(async()=>{
 let arriveNow;
 if(ORDER==='animation_last')movement={ready:new Promise(resolve=>arriveNow=resolve)};
 travel();input.value='how do we handle login';document.activeElement=input;
 const searching=search(true);
 assert.equal(route.q,'how do we handle login');assert.equal(navigation().url.searchParams.get('within'),'planet:b2b');
 const found={intent:{action:'search',within:'planet:b2b',query:'how do we handle login'},nodes:[],
  evidence:{sources:[{source_id:'b2b-auth'}]}};
 if(ORDER==='search_first'){navigation().resolve(found);await searching;explore().resolve(map);}
 else {explore().resolve(map);await tick();navigation().resolve(found);await searching;}
 if(arriveNow)arriveNow();await tick();
 assert.equal(route.q,'how do we handle login');assert.equal(route.searchWithin,'planet:b2b');
 assert.equal(input.value,route.q);assert.equal(searchResult,found);assert.deepEqual(rendered,[found]);
 assert.equal(requests.length,2,'Arrival cannot replay or silently replace the submitted search');
 assert.equal(focusCalls,0,'Arrival cannot take focus away from the new Navigator work');
 assert.equal(navigatorStatus.textContent,'Searched how do we handle login');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('ORDER', repr(order)))


def contents_controller(body):
    helpers = section('function renderShipCopies(', 'function renderSelection(')
    helpers += section('function selectedNode(', 'function setSelection(')
    run_js("const assert=require('node:assert/strict');\n" + helpers + r"""
class Element {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children;
  this.events={};this.isConnected=true;this.open=Object.hasOwn(attrs,'open');}
 append(...children){this.children.push(...children)}
 replaceChildren(...children){this.children=children}
 addEventListener(name,handler){this.events[name]=handler}
 focus(){this.focused=true}
 scrollIntoView(){this.scrolled=true}
 querySelector(selector){return walk(this).find(node=>selector==='summary'?node.tag==='summary':
  selector.startsWith('.')&&(node.attrs.class||'').split(' ').includes(selector.slice(1)))||null}
}
const el=(tag,attrs={},...children)=>new Element(tag,attrs,children);
const button=(label,onclick,attrs={})=>el('button',{...attrs,onclick},label);
const pathRow=value=>el('code',{},value);
function walk(root){return [root,...root.children.filter(child=>child instanceof Element).flatMap(walk)]}
function click(root,label){const control=walk(root).find(node=>node.tag==='button'&&node.children.includes(label));
 assert.ok(control,'Missing '+label);control.attrs.onclick();}
let active=true,timeData=null,route={place:'',selected:'',copiesPlace:'',timeAt:'',step:3,q:'matrix',
 local:true,searchWithin:'planet:orchard',offset:80,zoom:2.1,pan:{x:14,y:-27}};
const archives=Array.from({length:22},(_,n)=>({id:'archive:'+n,kind:'ship',form:'archive',label:'Archive '+n}));
const galaxy={id:'galaxy:owner',kind:'galaxy',label:'My galaxy',stored_copies:archives,
 contents:{total:22,groups:[{category:'archives',count:22,places:archives.slice(0,4)}]}};
let view={center:galaxy,nodes:[]};
const inspector=el('aside'),stage=el('div'),remembered=[],flights=[];
const remember=()=>remembered.push(structuredClone(route));
const renderSelection=()=>{inspector.replaceChildren();renderShipCopies(selectedNode());};
const fly=id=>{flights.push(id);route={place:id,selected:'',copiesPlace:'',step:route.step+1};};
""" + body)


def test_contents_archive_more_opens_all_existing_copies_without_new_flight():
    contents_controller(r"""
const before=structuredClone(route),preview=contentsPreview(galaxy);renderShipCopies(galaxy);
assert.equal(walk(preview).filter(node=>node.tag==='button').length,5,'Only four preview links plus the catalog action');
click(preview,'Open stored-copy catalog →');
const catalog=inspector.querySelector('.space-ship-copies');
assert.equal(catalog.open,true);assert.equal(catalog.scrolled,true);
assert.equal(catalog.querySelector('summary').focused,true);
assert.equal(walk(catalog).filter(node=>node.tag==='button').length,22);
assert.deepEqual(flights,[]);assert.equal(route.copiesPlace,galaxy.id);
for(const key of Object.keys(before).filter(key=>key!=='copiesPlace'))assert.deepEqual(route[key],before[key],key);
assert.equal(remembered.at(-1).copiesPlace,galaxy.id);
click(catalog,'Open stored copy: Archive 21 →');assert.deepEqual(flights,['archive:21']);
""")


def test_contents_archive_search_preview_keeps_catalog_open_on_destination_arrival():
    contents_controller(r"""
const preview=contentsPreview(galaxy,true);
view={center:{id:'planet:elsewhere',kind:'planet'},nodes:[]};
click(preview,'Open stored-copy catalog →');
assert.deepEqual(flights,[galaxy.id]);assert.equal(route.copiesPlace,galaxy.id);
view={center:galaxy,nodes:[]};renderSelection();
assert.equal(inspector.querySelector('.space-ship-copies').open,true);
""")


def test_contents_more_returns_to_current_chart_without_changing_search_or_camera():
    contents_controller(r"""
const areas=Array.from({length:8},(_,n)=>({id:'district:'+n,label:'Area '+n,kind:'district'}));
const planet={id:'planet:orchard',label:'Orchard',kind:'planet',
 contents:{total:8,groups:[{category:'areas',count:8,places:areas.slice(0,4)}]}};
view={center:planet,nodes:areas};route.place=planet.id;
const before=structuredClone(route),preview=contentsPreview(planet);
click(preview,'Return to destinations chart ↑');
assert.deepEqual(route,before);assert.deepEqual(flights,[]);assert.equal(stage.focused,true);assert.equal(stage.scrolled,true);
click(preview,'Area 3');assert.deepEqual(flights,['district:3'],'Preview links retain exact destination identity');
""")


def test_contents_more_names_parent_destination_without_claiming_a_category_filter():
    contents_controller(r"""
const planet={id:'planet:orchard',label:'Orchard',kind:'planet',contents:{total:8,groups:[
 {category:'areas',count:8,places:[{id:'district:login',label:'Login',kind:'district'}]}]}};
const preview=contentsPreview(planet,true);
assert.ok(!walk(preview).some(node=>node.tag==='button'&&node.children.some(value=>String(value).startsWith('Explore all'))));
click(preview,'Explore Orchard →');assert.deepEqual(flights,[planet.id]);
""")


def test_contents_count_grammar_uses_singular_without_changing_group_headings():
    contents_controller(r"""
galaxy.contents={total:8,groups:[
 {category:'applications',count:1,places:[]},{category:'experts',count:1,places:[]},
 {category:'starbases',count:1,places:[]},{category:'archives',count:1,places:[]},
 {category:'products',count:2,places:[]},{category:'areas',count:2,places:[]}]};
for(const compact of [false,true]){
 const preview=contentsPreview(galaxy,compact),counts=preview.querySelector('.space-contents-counts');
 assert.equal(counts.children[0],'1 lab application · 1 expert · 1 starbase · 1 stored copy · 2 products · 2 code areas');
 assert.ok(walk(preview).some(node=>node.tag==='h4'&&node.children.includes('Lab applications')));
 assert.equal(galaxy.contents.groups[0].count,1);
}
""")
