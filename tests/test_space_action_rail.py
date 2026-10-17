"""The inspector's action rail: one existing route per action, beside the service's own command.

These run the shipped navcom_space.js functions under Node against a small fake DOM.
Commands come from navcom_space.commands(), the service the chart uses, so the rail is
checked against what the CLI really offers for every kind.
"""
import json

import navcom_space
from test_space_camera import js_between, run_js

# A fake DOM just big enough for the controller: elements, attributes, listeners, text.
DOM = r"""
const assert=require('node:assert/strict');
class El{constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs={};for(const[k,v]of Object.entries(attrs))this.attrs[k]=String(v);
  this.children=[];this.listeners={};this.value=attrs.value??'';this.textContent='';this.disabled=!!attrs.disabled;this.open=false;this.append(...children);}
 append(...xs){for(const x of xs)if(x!==''&&x!=null)this.children.push(x);} prepend(...xs){this.children.unshift(...xs);}
 replaceChildren(...xs){this.children=[];this.append(...xs);}
 setAttribute(k,v){this.attrs[k]=String(v);} getAttribute(k){return k in this.attrs?this.attrs[k]:null;}
 removeAttribute(k){delete this.attrs[k];} hasAttribute(k){return k in this.attrs;}
 addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);} fire(type,event={}){for(const fn of this.listeners[type]||[])fn({preventDefault(){},currentTarget:this,...event});}
 get textContent(){return this._text||'';} set textContent(value){this._text=String(value);this.children=[];}
 get isConnected(){return true;} remove(){} focus(){} scrollIntoView(){} checkValidity(){return true;} showModal(){this.open=true;} close(){this.open=false;}
 querySelectorAll(selector){return walk(this).slice(1).filter(n=>n.tag===selector);} querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
const el=(tag,attrs={},...children)=>new El(tag,attrs,children);
function walk(n){return n&&typeof n==='object'?[n,...n.children.flatMap(walk)]:[];}
function words(n){return n&&typeof n==='object'?[n.textContent,...n.children.map(words)].filter(Boolean).join(' '):String(n);}
function buttons(root,label){return walk(root).filter(n=>n.tag==='button'&&(label===undefined||words(n).trim()===label));}
function press(root,label){const found=buttons(root,label);assert.equal(found.length,1,'one button '+label+' (found '+found.length+')');return found[0].onclick({currentTarget:found[0]});}
const button=(label,fn,attrs={})=>{const b=el('button',Object.fromEntries(Object.entries(attrs).filter(([,v])=>v!==false&&v!=null)),label);b.onclick=fn;return b;};
const text=value=>typeof value==='string'?value:typeof value==='number'?String(value):'';
const copied=[];async function copy(value){copied.push(value);}
const calls=[];let replies={};
const api=async(path,body)=>{calls.push(body?{path,body}:{path});const route=path.split('?')[0];const reply=replies[route];if(reply instanceof Error)throw reply;return typeof reply==='function'?reply(path,body):structuredClone(reply??{});};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
"""


def helpers(*names):
    """Slices of the shipped controller, by the function that starts each one and the one after it."""
    spans = {
        "commands": ("function shellQuote(", "async function copy("),
        "cli": ("function cliLine(", "function pathRow("),
        "rail": ("function placeRail(", "function renderSelection("),
        "panels": ("function openRailPanel(", "function carriedState("),
        "conversations": ("function conversationCard(", "function renderSearch("),
        "art": ("function art(", "function evidenceText("),
        "reader": ("function readerStatus(", "// Find words in the open harvested file"),
        "landing": ("function keptLanding(", "function historicalMap("),
        "rail_state": ("function railPanelState(", "function setActive("),
        "page": ("function pageOffset(", "function renderDestinationPager("),
        "refresh": ("function refreshProgress(", "async function refreshChart("),
        "history": ("function historyPanel(", "function renderHistoricalRevision("),
        "reads": ("const reads=new Map();", "function historyPanel("),
        "focus": ("function renderSelection(", "function drawSelection("),
    }
    return "\n".join(js_between(*spans[name]) for name in names)


def node(identity, kind, parent, **extra):
    return dict(dict(id=identity, kind=kind, label=identity.split(":")[-1].title(), parent_id=parent,
                     locations=[], source_ids=[], source_scopes=[], conversation_collections=[]), **extra)


SCOPE = [dict(source_id="src1", paths=["apps/web"]), dict(source_id="src2", paths=["."])]
PLACES = {
    "galaxy": node("galaxy:owner", "galaxy", None, source_ids=["src1", "src2"], source_scopes=SCOPE,
                   conversation_collections=["projects:a"], stored_copies=[dict(id="fleet:ship:copy")]),
    "system": node("system:coast", "system", "galaxy:owner", source_ids=["src1"], source_scopes=SCOPE[:1],
                   conversation_collections=["projects:a", "projects:b"]),
    "planet": node("planet:harbor", "planet", "system:coast", locations=[dict(path="/w/harbor")], source_ids=["src1"],
                   source_scopes=SCOPE[:1], conversation_collections=["projects:a"]),
    "moon": node("moon:exp1", "moon", "planet:harbor", locations=[dict(path="/w/exp1")], source_ids=["src1"], source_scopes=SCOPE[:1]),
    "district": node("district:login", "district", "planet:harbor", source_ids=["src1"],
                     source_scopes=[dict(source_id="src1", paths=["apps/web/login.ts"])], suggested_query="login policy",
                     conversation_collections=["projects:a"]),
    "lab": node("planet:labapp", "district", "moon:exp1", form="application", locations=[dict(path="/w/exp1/app")],
                source_ids=["src1"], source_scopes=SCOPE[:1]),
    "star": node("star-candidate:tides", "star", "galaxy:owner", locations=[dict(path="/w/tides")], source_ids=["src1"],
                 source_scopes=SCOPE[:1]),
    "starbase": node("fleet:starbase:dock", "starbase", "galaxy:owner"),
    "ship": node("fleet:ship:working", "ship", "fleet:starbase:dock", ship_links=[dict(id="fleet:ship:copy", form="archive", label="Copy")]),
    "archive": node("fleet:ship:copy", "ship", "galaxy:owner", form="archive"),
}
for place in PLACES.values():
    place["commands"] = navcom_space.commands(place)

# What the rail offers per kind (selected = not the current center), in order.
EXPECTED = {
    "galaxy": ["Search this place", "Connections & versions", "Search harvested sources", "Conversations here",
               "Conversations by date", "List places", "Harvested sources"],
    "system": ["Fly to Coast →", "Connections & versions", "Search harvested sources", "Conversations here",
               "Conversations by date", "List places"],
    "planet": ["Fly to Harbor →", "Inspect code locations", "Browse saved files", "Check history", "Connections & versions",
               "Search harvested sources", "Conversations here", "Conversations by date", "List places"],
    "moon": ["Fly to Exp1 →", "Inspect code locations", "Browse saved files", "Check history", "Connections & versions",
             "Search harvested sources", "Conversations by date", "List places"],
    "district": ["Land in district →", "Browse saved files", "Check history", "Connections & versions",
                 "Search harvested sources", "Conversations here", "Conversations by date"],
    "lab": ["Enter lab application →", "Inspect code locations", "Browse saved files", "Check history",
            "Connections & versions", "Search harvested sources", "Conversations by date"],
    "star": ["Fly to Tides →", "Ask expert", "Inspect expert", "Check history", "Connections & versions",
             "Search harvested sources", "Conversations by date"],
    "starbase": ["Fly to Dock →", "List places"],
    "ship": ["Fly to Working →", "Board ship", "Inspect ship", "Read carried context"],
    "archive": ["Fly to Copy →", "Inspect archive", "Read carried context"],
}
# Commands the rail leaves to "More CLI commands": the inspector itself (show), the evidence
# replay of a search, the center's own explore (the chart on screen), its in-place search when it
# is not the center (fly there first), and the dated-system verb: Explore time lives in the time
# bar above the chart, not twice.
LEFT = {"show", "search", "explore", "navigate", "history_system"}


def test_every_kind_gets_one_rail_whose_lines_are_the_service_commands():
    script = DOM + helpers("commands", "cli", "rail") + r"""
const places=PLACES,expected=EXPECTED,left=new Set(LEFT);
let route={dossier:'',carriedRead:null,filesPlace:'',historyPlace:'',relatedPlace:'',railPanel:null,timeOpen:false,q:''},railLines=[];
const input={value:''},scope={},historyTimelines=new Map(),timeBar=el('div'),clicked=[];
const remember=()=>{},renderTimeBar=()=>{};
for(const name of ['fly','nativeAction','inspectShip','openCarried','openFiles','openHistory','openRelated','openRailPanel'])globalThis[name]=(...args)=>clicked.push([name,...args]);
const flat=value=>Array.isArray(value)&&Array.isArray(value[0])?value[0]:value;
for(const [kind,n] of Object.entries(places)){
 const center=kind==='galaxy',{rail,used}=placeRail(n,center);
 const items=rail.children.map(item=>({label:words(item.children[0]).trim(),cli:item.children[1]?.children[0]?.textContent,action:item.children[0].attrs['data-rail-action']}));
 assert.deepEqual(items.map(i=>i.label),expected[kind],kind);
 for(const item of items)assert.ok(item.action in n.commands,kind+': '+item.label+' names its verb for focus return');
 assert.equal(new Set(items.map(i=>i.label)).size,items.length,kind+': no duplicate actions');
 for(const item of items)assert.ok(item.cli&&item.cli.startsWith('navcom '),kind+': '+item.label+' shows its command');
 // Every service command is either on the rail (or inside the panel a rail action opens) or left for "More CLI commands".
 const rest=Object.keys(n.commands).filter(key=>!used.has(key)&&n.commands[key]?.length);
 assert.ok(rest.every(key=>left.has(key)),kind+' leaves '+rest.join(','));
 for(const key of used)assert.ok(key in n.commands,kind+' claims '+key);
 // The line is the service argv, unchanged apart from unfilled <placeholders> left visible.
 const first=rail.children[0].children[1].children[0].textContent,key=center?'navigate':'explore';
 assert.equal(first,commandText(flat(n.commands[key])),kind);
 assert.ok(!/'</.test(items.map(i=>i.cli).join(' ')),kind+': placeholders are never quoted as if filled');
}
// The primary action keeps its behavior; consequential ones only open their review dialogs.
const ship=places.ship,star=places.star;clicked.length=0;
press(placeRail(ship,false).rail,'Board ship');press(placeRail(star,false).rail,'Ask expert');press(placeRail(star,false).rail,'Fly to Tides →');
assert.deepEqual(clicked.map(c=>c[0]),['nativeAction','nativeAction','fly']);assert.equal(calls.length,0,'the rail itself never calls a route');
// Copy copies the exact command; the center's search line echoes the Navigator's words.
press(placeRail(ship,false).rail.children[1],'Copy');assert.equal(copied.at(-1),commandText(ship.commands.board_validate));
railLines=[];const galaxy=placeRail(places.galaxy,true).rail;input.value='login flow';for(const update of railLines)update();
assert.match(galaxy.children[0].children[1].children[0].textContent,/^navcom atlas navigate 'login flow' --within galaxy:owner$/);
""".replace("PLACES", json.dumps(PLACES)).replace("EXPECTED", json.dumps(EXPECTED)).replace("LEFT", json.dumps(sorted(LEFT)))
    run_js(script)


def test_placeholders_are_filled_only_with_user_input():
    run_js(DOM + helpers("commands") + r"""
const argv=['navcom','atlas','ask','star:x','<question>','--space-cache','/a b/c.json'];
assert.equal(commandText(argv),"navcom atlas ask star:x <question> --space-cache '/a b/c.json'");
assert.equal(commandText(argv,{'<question>':"What's new?"}),"navcom atlas ask star:x 'What'\\''s new?' --space-cache '/a b/c.json'");
assert.equal(commandText(argv,{'<question>':'   '}),"navcom atlas ask star:x <question> --space-cache '/a b/c.json'",'blank input leaves the placeholder');
assert.equal(commandText(['navcom','history','system','g','--at','<YYYY-MM-DD>'],{'<YYYY-MM-DD>':'2026-10-01','--at':'x','g':'y'}),'navcom history system g --at 2026-10-01','only placeholder words are filled');
assert.equal(commandText('navcom --open ref:4'),'navcom --open ref:4','a service string is shown as given');
""")


def rail_panel(body):
    """Run railPanel() for one place with a recording api(); each panel request is one existing route."""
    return run_js(DOM + helpers("cli", "commands", "reads", "panels", "page") + r"""
let active=true,railTicket=0,route={railPanel:null},view=null;const remember=()=>{},renderSelection=()=>{},inspector=el('aside');
const evidenceCard=(hit,kind)=>el('article',{},kind+':'+hit.relative_path),conversationCard=n=>el('article',{},'conversation '+n.key);
const datedCard=item=>el('article',{},'dated '+item.key),datedNotes=()=>el('details'),pathRow=path=>el('code',{},path);
const placeKind=n=>n.kind,recordedTime=String,timeLabel=String,fly=()=>{};
function railPanelState(value){return {choice:0,q:'',at:'',offset:0,...value};}
function open(n,panel,state={}){route.railPanel=railPanelState({place:n.id,panel,...state});return railPanel(n);}
const places=PLACES;
""".replace("PLACES", json.dumps(PLACES)) + body)


def test_sources_panel_searches_the_exact_source_and_paths_of_the_service_command():
    rail_panel(r"""
(async()=>{
 replies['/api/sources/search']={published:7,concept_hits:[{relative_path:'apps/web/a.py',source_id:'src1'}],text_hits:[{relative_path:'apps/web/b.md',source_id:'src1'}]};
 const box=open(places.galaxy,'sources');assert.equal(calls.length,0,'nothing runs before words are typed');
 const form=walk(box).find(n=>n.tag==='form'),select=walk(box).find(n=>n.tag==='select'),field=walk(box).find(n=>n.tag==='input');
 assert.equal(select.children.length,2,'one choice per source the service lists');
 field.value='login';field.fire('input');
 assert.match(walk(box).find(n=>n.tag==='code').textContent,/^navcom sources search login --within src1 --path apps\/web/);
 form.fire('submit');await tick();await tick();
 assert.equal(calls.length,1);const url=new URL(calls[0].path,'http://x');
 assert.equal(url.pathname,'/api/sources/search');assert.deepEqual([...url.searchParams],[['q','login'],['within','src1'],['path','apps/web']]);
 assert.equal(route.railPanel.q,'login');
 assert.ok(words(box).includes('Ranked code clue:apps/web/a.py')&&words(box).includes('Code and documents:apps/web/b.md'));
 select.value='1';select.fire('change');assert.match(walk(box).find(n=>n.tag==='code').textContent,/ --within src2$/);
 form.fire('submit');await tick();await tick();const second=new URL(calls[1].path,'http://x');
 assert.deepEqual([...second.searchParams],[['q','login'],['within','src2']],'a whole-source command has no --path');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_conversation_panel_explores_then_searches_the_listed_collection():
    rail_panel(r"""
(async()=>{
 replies['/api/atlas']=(path)=>{const q=new URL(path,'http://x').searchParams;return {nodes:[{key:'/k1'},{id:'group'}],total:1,offset:0,query:q.get('q')||'',cli_command:'navcom atlas exact',effective_scope:{collection:q.get('within'),label:'~/w/'+q.get('within').slice(9)}};};
 const box=open({...places.system,conversation_count:1400},'conversations');await tick();await tick();
 assert.deepEqual([...new URL(calls[0].path,'http://x').searchParams],[['action','explore'],['within','projects:a'],['limit','12']]);
 assert.ok(words(box).includes('conversation /k1'));assert.ok(!words(box).includes('group'),'only conversations become cards');
 assert.equal(walk(box).filter(n=>n.tag==='code').at(-1).textContent,'navcom atlas exact','the response command replaces the template');
 // The read names its collection and where it sits among the place's collections; the place total is not implied.
 assert.match(words(box),/~\/w\/a +· collection 1 of 2/,'the loaded collection is named, with its position');
 assert.ok(words(box).includes('1–1 of 1 conversations in this collection'));
 assert.ok(words(box).includes('This place counts 1,400 conversations across 2 collections. This list reads one collection at a time'));
 const form=walk(box).find(n=>n.tag==='form'),input=walk(box).find(n=>n.tag==='input'),select=walk(box).find(n=>n.tag==='select');
 assert.deepEqual(select.children.map(words),['~/w/a · projects:a','projects:b'],'only a read collection has a name');
 // Typed words show in the line before Search runs them (they fill the service's <query>).
 input.value='drill';input.fire('input');
 assert.equal(walk(box).filter(n=>n.tag==='code').at(-1).textContent,'navcom atlas search drill --within projects:a');
 // A re-render (any other rail click) reads the same collection from memory, not from the route again.
 const before=calls.length,again=open({...places.system,conversation_count:1400},'conversations');await tick();await tick();
 assert.equal(calls.length,before,'an unchanged panel request is not repeated');assert.ok(words(again).includes('conversation /k1'));
 const form2=walk(again).find(n=>n.tag==='form'),input2=walk(again).find(n=>n.tag==='input'),select2=walk(again).find(n=>n.tag==='select');
 select2.value='1';input2.value='matrix';form2.fire('submit');await tick();await tick();
 assert.deepEqual([...new URL(calls[1].path,'http://x').searchParams],[['action','search'],['within','projects:b'],['q','matrix']]);
 assert.match(words(again),/~\/w\/b +· collection 2 of 2/);assert.equal(words(select2.children[1]),'~/w/b · projects:b');
 // A district's command carries the product's suggested query; that query is what runs, and no words are asked for.
 calls.length=0;const district=open(places.district,'conversations');await tick();
 assert.deepEqual([...new URL(calls[0].path,'http://x').searchParams],[['action','search'],['within','projects:a'],['q','login policy']]);
 assert.equal(walk(district).filter(n=>n.tag==='input').length,0,'no words box when the command takes no <query>');
 assert.equal(buttons(district,'Search conversations').length,0);
 assert.ok(words(district).includes('Searched with this place’s own words: “login policy”.'));
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_dated_list_and_harvest_panels_each_call_their_one_route():
    rail_panel(r"""
(async()=>{
 replies['/api/history/conversations']={as_of:'2026-01-02T00:00:00Z',conversations:[{key:'/d1'}],cli_command:'navcom history conversations exact'};
 replies['/api/space']={nodes:[{id:'planet:x',kind:'planet',label:'X'}],total:41,offset:0,more:true,cli_command:'navcom atlas list exact'};
 replies['/api/sources']={sources:[{id:'src1',label:'Web',root:'/w',coverage:{files:3}}],published:5};
 const dated=open(places.planet,'dated',{at:'2026-01-02',q:'login'});
 assert.match(walk(dated).find(n=>n.tag==='code').textContent,/^navcom history conversations planet:harbor --at 2026-01-02$/,'the template previews the date before the read');
 await tick();await tick();
 assert.deepEqual([...new URL(calls[0].path,'http://x').searchParams],[['within','planet:harbor'],['at','2026-01-02'],['q','login'],['limit','20']]);
 assert.equal(walk(dated).find(n=>n.tag==='code').textContent,'navcom history conversations exact','after the read the line is its exact command (with --query)');
 const date=walk(dated).find(n=>n.attrs?.type==='date');date.value='2026-03-04';date.fire('input');
 assert.equal(walk(dated).find(n=>n.tag==='code').textContent,'navcom history conversations exact','editing the date keeps the command of the results on screen');
 assert.ok(words(dated).includes('dated /d1'));
 const list=open(places.galaxy,'list',{choice:3});await tick();await tick();
 assert.deepEqual([...new URL(calls[1].path,'http://x').searchParams],[['action','list'],['kind','cities'],['within','galaxy:owner'],['limit','40'],['offset','0']]);
 assert.ok(walk(list).find(n=>n.tag==='select').children.map(o=>words(o)).includes('Districts'));
 press(list,'More →');await tick();await tick();assert.equal(new URL(calls[2].path,'http://x').searchParams.get('offset'),'40');assert.equal(route.railPanel.offset,40);
 const harvest=open(places.galaxy,'harvest');await tick();await tick();assert.equal(calls[3].path,'/api/sources');assert.ok(words(harvest).includes('Web'));
 assert.equal(open(places.moon,'conversations'),null,'a restored panel whose verb the place does not list stays closed');
 assert.equal(open(places.starbase,'sources'),null);assert.equal(calls.length,4);
 assert.match(walk(harvest).find(n=>n.tag==='code').textContent,/^navcom sources list$/);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def conversation_controller(body):
    run_js(DOM + helpers("cli", "commands", "conversations") + r"""
let actionTicket=0;const actionDialog=el('dialog'),opened=[];
function closeAction(){actionTicket++;actionDialog.open=false;}
const readConversation=(key,start)=>opened.push({key,start}),pathRow=path=>el('code',{},path);
""" + body)


def test_conversation_cards_open_recap_and_search_inside_with_one_route_each():
    conversation_controller(r"""
(async()=>{
 const card=conversationCard({key:'/k',ref:'abc',provider:'codex',label:'Login work',start:9,open_command:'navcom --open abc:9',next_command:'navcom atlas show abc'});
 assert.ok(words(card).includes('navcom --open abc:9'),'open shows the service open_command');
 assert.ok(words(card).includes('Nearest terminal read · a shorter window around this turn'),'GET /api/session has no CLI twin; the line says so');
 press(card,'Read conversation →');assert.deepEqual(opened.pop(),{key:'/k',start:9});
 replies['/api/recap']={key:'/k',recap:'navcom --recap · codex · ref abc'};
 await press(card,'Recap');assert.equal(calls.at(-1).path,'/api/recap?key=%2Fk');assert.ok(actionDialog.open);
 press(actionDialog,'Copy recap');assert.equal(copied.at(-1),'navcom --recap · codex · ref abc');
 replies['/api/session/search']={query:'login',sessions:[{recap:'navcom --recap abc',hits:[{msg_index:4,role:'user',snippet:'fix «login»'}]}]};
 press(card,'Search inside');const form=walk(card).find(n=>n.tag==='form'),input=walk(form).find(n=>n.tag==='input');
 input.value='login';form.fire('submit');await tick();await tick();
 assert.equal(calls.at(-1).path,'/api/session/search?key=%2Fk&q=login');
 walk(card).find(n=>n.attrs?.['aria-label']==='Read turn 4').onclick();assert.deepEqual(opened.pop(),{key:'/k',start:4});
 assert.ok(words(card).includes('navcom --recap abc'),'the search result carries its own recap command');
 replies['/api/atlas']=(path)=>new URL(path,'http://x').searchParams.get('action')==='show'?{nodes:[{label:'Login work',parent_ref:null,child_refs:['c1'],resume_plan:{line:'codex resume x'}}]}:{nodes:[{key:'/k',label:'Login work',depth:0}],cli_command:'navcom atlas tree abc'};
 await press(card,'Family');assert.equal(calls.at(-1).path,'/api/atlas?action=show&ref=abc');
 assert.ok(words(actionDialog).includes('navcom atlas show abc'));assert.ok(words(actionDialog).includes('1 recorded child task: c1'));
 await press(actionDialog,'Show the whole family tree');assert.equal(calls.at(-1).path,'/api/atlas?action=tree&ref=abc');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_resume_and_fresh_agent_review_before_any_launch():
    conversation_controller(r"""
(async()=>{
 const t={key:'/k',ref:'abc',provider:'codex',label:'Login work',start:9};
 replies['/api/plan']=(path)=>({line:'cd ~/w && codex resume x'+(path.includes('harness')?' (fresh)':''),gone:false,archived:false});
 replies['/api/launch']={ok:true,message:'opened in a new tmux window',command:'codex resume x'};
 replies['/api/harnesses']=['claude','gemini'];
 await launchReview(t,false);
 assert.deepEqual(calls.map(c=>c.path),['/api/plan?key=%2Fk'],'opening the review reads the plan only');
 assert.ok(words(actionDialog).includes('cd ~/w && codex resume x'));
 await press(actionDialog,'Resume in a new tab →');
 assert.deepEqual(calls.at(-1),{path:'/api/launch',body:{key:'/k',harness:null}});assert.ok(words(actionDialog).includes('Terminal tab opened'));
 calls.length=0;await launchReview(t,true);
 assert.deepEqual(calls.map(c=>c.path),['/api/harnesses?provider=codex','/api/plan?key=%2Fk&harness=claude&turn=9']);
 const select=walk(actionDialog).find(n=>n.tag==='select');select.value='gemini';select.fire('change');await tick();
 assert.equal(calls.at(-1).path,'/api/plan?key=%2Fk&harness=gemini&turn=9');
 await press(actionDialog,'Start fresh gemini in a new tab →');
 assert.deepEqual(calls.at(-1),{path:'/api/launch',body:{key:'/k',harness:'gemini',turn:9}});
 // A gone transcript with no archived copy is never offered a launch.
 replies['/api/plan']={line:'x',gone:true,archived:false};calls.length=0;await launchReview(t,false);
 assert.equal(buttons(actionDialog,'Resume in a new tab →').length,0);assert.ok(calls.every(c=>c.path!=='/api/launch'));
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_sprites_come_from_kind_and_form_and_places_take_their_systems_hue():
    run_js(DOM + helpers("art") + r"""
const roles={district:'city',moon:'lab',starbase:'starbase',ship:'ship'},systemViews=new Map();
let view={breadcrumbs:[{id:'galaxy:owner',kind:'galaxy'}],nodes:[]},route={},timeData=null;
const src=n=>walk(art(n)).find(x=>x.tag==='img')?.attrs.src;
assert.equal(src({id:'fleet:ship:a',kind:'ship',form:'archive'}),'/assets/starship/archive.png','archives draw the archive, not a ship');
assert.equal(src({id:'fleet:ship:b',kind:'ship'}),'/assets/starship/ship.png');
assert.equal(src({id:'planet:x',kind:'district',form:'application'}),'/assets/starship/lab.png');
assert.equal(src({id:'d',kind:'district'}),'/assets/starship/city.png');
assert.equal(src({id:'fleet:starbase:c',kind:'starbase',art_role:'ship'}),'/assets/starship/starbase.png','a stale art_role is ignored');
const hue=style=>Number(/--hue:(\d+)/.exec(style)[1]),sat=style=>/--sat:(\d+)%/.exec(style)[1];
// Galaxy view: every system keeps tint(id), unchanged.
const legacy=id=>{let h=2166136261;for(const c of String(id))h=Math.imul(h^c.charCodeAt(0),16777619);h>>>=0;return `--hue:${h%360};--sat:${32+(h>>>9)%34}%;--light:${36+(h>>>15)%22}%;--band:${(h>>>21)%120-60}deg;--stripe:${(h>>>27)%4}`;};
for(const id of ['system:9b1f5d1b7914f7de9de3','system:independent'])assert.equal(art({id,kind:'system'}).attrs.style,legacy(id));
// Inside a system: planets within 14° of its hue and the same saturation; moons and districts in-family.
view={breadcrumbs:[{id:'galaxy:owner',kind:'galaxy'},{id:'system:9b1f5d1b7914f7de9de3',kind:'system'}],nodes:[]};
const family=tint('system:9b1f5d1b7914f7de9de3');
for(const id of ['planet:a','planet:b','planet:ace3e3d93a9b103549f8']){const style=art({id,kind:'planet'}).attrs.style,d=Math.abs(hue(style)-hue(family));
 assert.ok(Math.min(d,360-d)<=24,id);assert.equal(sat(style),sat(family));}
// Siblings differ in more than hue: lightness, ring tilt and stripes come from their own IDs.
const syra=['planet:066e6a50a90b99714d6e','planet:ace3e3d93a9b103549f8','planet:b6605a3c45bcf0e7a3ce','planet:83edb10baabea503b0e9'].map(id=>art({id,kind:'planet'}).attrs.style);
assert.equal(new Set(syra).size,4);assert.deepEqual(syra.map(x=>/--light:(\d+)%/.exec(x)[1]),['58','35','57','42']);assert.deepEqual(syra.map(hue),[100,137,107,120],'±24° spreads the family');
assert.ok(art({id:'moon:m',kind:'moon'}).attrs.class.includes('in-family'));
assert.ok(art({id:'district:d',kind:'district'}).attrs.class.includes('in-family'));
for(const n of [{id:'s',kind:'star'},{id:'f',kind:'ship'},{id:'g',kind:'ship',form:'archive'},{id:'b',kind:'starbase'}]){const a=art(n);
 assert.ok(!(a.attrs.class||'').includes('in-family'),n.kind);assert.ok(!('style' in a.attrs),n.kind);}
// A dated landing of a moon under a planet finds its system through the saved origin page.
view={breadcrumbs:[{id:'moon:m',kind:'moon'}],nodes:[]};route={timeLanding:{origin:{place:'',timeAt:'t',timeQ:'',timeCursor:'c'}}};
systemViews.set(['','t','','c'].join('|'),{nodes:[{id:'moon:m',kind:'moon',parent_id:'planet:p'},{id:'planet:p',kind:'planet',parent_id:'system:s'},{id:'system:s',kind:'system'}]});
assert.equal(systemOf({id:'moon:m',kind:'moon',parent_id:'planet:p'}),'system:s');
systemViews.clear();assert.equal(systemOf({id:'moon:m',kind:'moon',parent_id:'planet:p'}),'','a cold load claims no family');
""")


def test_reader_names_the_commit_date_only_when_the_response_has_one():
    run_js(DOM + helpers("reader") + r"""
const recordedTime=value=>'T'+value;
const pinned={provenance:{kind:'git_revision',commit:'1325eaa77fed0521f5',captured_at:'2026-10-16T01:00:00Z'},published:99};
assert.equal(readerStatus(pinned),'Pinned Git revision 1325eaa77fed · captured T2026-10-16T01:00:00Z · current working files were not read');
assert.equal(readerStatus({...pinned,provenance:{...pinned.provenance,captured_at:null}}),'Pinned Git revision 1325eaa77fed · captured T99 · current working files were not read');
assert.equal(readerStatus({...pinned,provenance:{...pinned.provenance,committed_at:'2025-06-01T00:00:00Z'}}),'Pinned Git revision 1325eaa77fed · committed T2025-06-01T00:00:00Z · current working files were not read');
assert.equal(readerStatus({provenance:{kind:'published_harvest'},published:5}),'Published harvest · T5 · current working files were not read');
""")


def test_reload_keeps_the_history_landing_and_its_origin_camera():
    run_js(DOM + helpers("landing") + r"""
const origin={place:'system:s',timeAt:'2026-10-01T12:00:00Z',timeCursor:'c:0',timeQ:'',offset:0,selected:'planet:p',zoom:.8,pan:{x:45,y:0},cameraReady:true,cameraScale:.4};
const kept={product:'planet:p',group:'',resultKey:'r',origin};
const linked={product:'planet:p',group:'',resultKey:'r',origin:{place:'system:s',timeAt:'2026-10-01T12:00:00.000Z',timeCursor:'c:0',timeQ:'',offset:0,selected:'',zoom:1,pan:{x:0,y:0},cameraReady:false}};
assert.equal(keptLanding(kept,linked),kept,'same landing: keep the origin selection and camera from history.state');
for(const change of [{product:'planet:q'},{group:'d'},{resultKey:'x'},{origin:{...linked.origin,timeCursor:'c:4'}},{origin:{...linked.origin,place:'system:t'}},{origin:{...linked.origin,timeAt:'2026-10-02T00:00:00Z'}}])
 {const other={...linked,...change};assert.equal(keptLanding(kept,other),other,JSON.stringify(change));}
assert.equal(keptLanding(null,linked),linked,'no saved landing: the URL decides');
""")


def test_rail_panel_state_is_validated_when_history_restores_it():
    run_js(DOM + helpers("rail_state", "page") + r"""
assert.deepEqual(railPanelState({place:'planet:p',panel:'list',choice:2,q:'x',at:'2026-01-02',offset:45}),{place:'planet:p',panel:'list',choice:2,q:'x',at:'2026-01-02',offset:40});
for(const bad of [null,{place:'',panel:'list'},{place:'p',panel:'launch'},{place:'x'.repeat(201),panel:'list'}])assert.equal(railPanelState(bad),null);
assert.deepEqual(railPanelState({place:'p',panel:'dated',choice:-1,at:'2026-1-2',q:7}),{place:'p',panel:'dated',choice:0,q:'',at:'',offset:0});
""")


def test_a_failed_refresh_relabels_only_the_first_chart_state_not_an_arrival():
    run_js(DOM + helpers("refresh") + r"""
const classList={add(){},remove(){},toggle(){}},pauseRefresh={classList},intakeProgress={classList},refresh={dataset:{},textContent:''};
const mapStatus=Object.assign(el('div'),{classList}),stage=el('div');let layoutNarrow=false,view={center:{id:'district:d'}};
let empty=el('div',{},el('h2',{},'You’ve arrived.'),el('p',{},'Search this place, or use its actions, to inspect its source evidence and conversations.'));
refreshFinished(Error('Failed to fetch'));
assert.deepEqual(walk(empty).filter(n=>['h2','p','button'].includes(n.tag)).map(words),['You’ve arrived.','Search this place, or use its actions, to inspect its source evidence and conversations.']);
view=null;empty=el('div',{},el('h2',{},'Charting your galaxy…'),button('Charting…',()=>{},{disabled:true}));
refreshFinished(Error('Failed to fetch'));
assert.deepEqual(walk(empty).filter(n=>['h2','button'].includes(n.tag)).map(words),['Your chart needs another pass.','Build / refresh the chart']);
assert.equal(buttons(empty,'Build / refresh the chart')[0].disabled,false);
""")


def test_a_chosen_git_copy_opens_its_commits_with_the_copy_in_the_explore_body():
    # POST /api/history/explore forwards repo like GET /api/history (navcom history explore PLACE COMMIT --repo ROOT).
    run_js(DOM + helpers("cli", "commands", "reads", "history") + r"""
El.prototype.querySelectorAll=function(selector){return walk(this).slice(1).filter(n=>typeof n==='object'&&selector.split(',').some(one=>{one=one.trim();
 if(one.startsWith('.'))return (n.attrs.class||'').split(' ').includes(one.slice(1));const m=/^\[([^\]=]+)\]$/.exec(one);return m?m[1] in n.attrs:n.tag===one;}));};
Object.defineProperty(El.prototype,'classList',{get(){return {toggle(){},add(){},remove(){}};}});
Object.defineProperty(El.prototype,'dataset',{get(){return Object.fromEntries(Object.entries(this.attrs).filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5).replace(/-./g,m=>m[1].toUpperCase()),v]));}});
let active=true,historyTicket=0,lastStep=0,view=null;const historyTimelines=new Map(),remember=()=>{},renderSelection=()=>{};
const node={id:'planet:awali',kind:'planet'},selectedNode=()=>node,recordedTime=String,pathRow=path=>el('code',{},path),renderHistoricalRevision=(detail,data)=>detail.append('opened '+data.commit+' in '+data.repo);
const panel=el('section',{class:'space-repository-history'}),inspector=el('aside',{},panel);
const trail=repo=>({repository:repo,include:['.'],cli_command:'navcom history timeline planet:awali --repo '+repo,commits:[{commit:'c0ffee1234567890',subject:'Fix login',committed_at:'2026-01-01'}]});
replies['/api/history']=(path)=>{const repo=new URL(path,'http://x').searchParams.get('repo');if(!repo)throw Object.assign(Error('This place has multiple Git copies; select one with --repo ROOT'),{coverage:{repositories:['/w/a','/w/b']}});return trail(repo);};
replies['/api/history/explore']=(path,body)=>({commit:body.revision,repo:body.repo});
const paths=()=>calls.map(c=>c.path+(c.body?' '+JSON.stringify(c.body):''));
let route={historyPlace:node.id,historyRepo:'',revision:'',historyQ:''};
(async()=>{
 // The place refuses without a copy and lists its copies; choosing one reads that copy's trail.
 await loadHistory(node);
 assert.deepEqual(panel.querySelectorAll('.space-history-copy').map(words),['/w/a','/w/b']);
 press(panel,'/w/b');await tick();await tick();
 assert.equal(route.historyRepo,'/w/b');
 assert.match(words(panel),/navcom history timeline planet:awali --repo \/w\/b/,'the trail shows its own exact command');
 const commits=panel.querySelectorAll('[data-history-commit]');assert.equal(commits.length,1,'a chosen copy offers its commits');
 calls.length=0;await commits[0].onclick();
 assert.deepEqual(calls.at(-1).body,{within:'planet:awali',revision:'c0ffee1234567890',q:'',limit:30,repo:'/w/b'});
 assert.match(words(panel),/opened c0ffee1234567890 in \/w\/b/);assert.match(historyIdentity(node),/#\/w\/b@c0ffee/);
 // Reload: history.state keeps the copy and revision; with an empty memo both reads carry the copy.
 reads.clear();calls.length=0;route={historyPlace:node.id,historyRepo:'/w/b',revision:'c0ffee1234567890',historyQ:''};
 await loadHistory(node);await tick();await tick();
 assert.deepEqual(paths(),['/api/history?action=timeline&within=planet%3Aawali&limit=60&repo=%2Fw%2Fb',
  '/api/history/explore {"within":"planet:awali","revision":"c0ffee1234567890","q":"","limit":30,"repo":"/w/b"}']);
 assert.match(words(panel),/opened c0ffee1234567890 in \/w\/b/,'the saved revision of the chosen copy reopens');
 // Any other rail click re-renders the panel from memory: no request is repeated.
 calls.length=0;await loadHistory(node);await tick();await tick();assert.deepEqual(paths(),[]);
 // Another copy: the chooser comes back from the place's own refusal (read once since the reload)...
 press(panel,'Choose another Git copy');await tick();await tick();
 assert.deepEqual(paths(),['/api/history?action=timeline&within=planet%3Aawali&limit=60']);
 assert.deepEqual(panel.querySelectorAll('.space-history-copy').map(words),['/w/a','/w/b']);assert.equal(route.revision,'','a revision belongs to its copy');
 // ...and switching back and forth is answered from memory.
 press(panel,'/w/b');await tick();await tick();assert.equal(panel.querySelectorAll('[data-history-commit]').length,1);
 press(panel,'Choose another Git copy');await tick();await tick();assert.equal(calls.length,1,'no request is repeated');
 // One Git copy: no repo field in either body.
 route={historyPlace:node.id,historyRepo:'',revision:'',historyQ:''};replies['/api/history']=trail('/w/only');reads.clear();calls.length=0;
 await loadHistory(node);await tick();await panel.querySelectorAll('[data-history-commit]')[0].onclick();
 assert.deepEqual(calls.at(-1).body,{within:'planet:awali',revision:'c0ffee1234567890',q:'',limit:30},'one copy: no repo field');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_a_failed_timeline_is_not_requested_again_until_check_again():
    run_js(DOM + helpers("cli", "commands", "reads", "history") + r"""
El.prototype.querySelectorAll=function(selector){return walk(this).slice(1).filter(n=>typeof n==='object'&&(selector.startsWith('.')?(n.attrs.class||'').split(' ').includes(selector.slice(1)):n.tag===selector));};
let active=true,historyTicket=0,view={published:7};const historyTimelines=new Map(),remember=()=>{},renderSelection=()=>{},recordedTime=String,pathRow=p=>el('code',{},p);
const node={id:'planet:care',kind:'planet'},selectedNode=()=>node,panel=el('section',{class:'space-repository-history'}),inspector=el('aside',{},panel);
let route={historyPlace:node.id,historyRepo:'',revision:'',historyQ:''};
replies['/api/history']=Error('Git history unavailable: fatal: Needed a single revision');
(async()=>{
 await loadHistory(node);await loadHistory(node);await loadHistory(node);
 assert.equal(calls.length,1,'re-renders show the remembered failure (no repeated 400s)');
 assert.match(words(panel),/History unavailable: Git history unavailable/);
 press(panel,'Check again');await tick();assert.equal(calls.length,2,'Check again asks the route again');
 view={published:8};await loadHistory(node);assert.equal(calls.length,3,'a newly published chart reads again');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_keyboard_focus_returns_to_the_same_rail_action_after_the_inspector_is_rebuilt():
    run_js(DOM + helpers("focus") + r"""
const document={activeElement:null,body:{}};
class Node2{constructor(action){this.action=action;this.isConnected=true;}closest(){return this.action?this:null;}get dataset(){return {railAction:this.action};}focus(){document.activeElement=this;}}
let items=[];const inspector={contains:n=>items.includes(n),querySelector:sel=>items.find(n=>sel===`[data-rail-action="${n.action}"]`)||null};
function drawSelection(){for(const n of items)n.isConnected=false;items=[new Node2('files'),new Node2('history_timeline')];}
drawSelection();document.activeElement=items[0];renderSelection();
assert.equal(document.activeElement,items[0],'the rebuilt Browse saved files button has focus');assert.equal(items[0].isConnected,true);
document.activeElement=items[1];renderSelection();assert.equal(document.activeElement.action,'history_timeline');
document.activeElement=document.body;renderSelection();assert.equal(document.activeElement,document.body,'focus elsewhere is left alone');
""")


def test_reading_from_the_bridge_leaves_the_library_selection_and_saved_state_alone():
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "navcom_web.html").read_text()
    select = page[page.index("async function select("):page.index("function renderDetail(")]
    run_js("const assert=require('node:assert/strict');\n" + select + r"""
const classes=new Set(),document={body:{classList:{contains:name=>classes.has(name)}}};
let detailSeq=0,currentDetail=null,saves=0,renders=0;const state={selected:'/library/own',start:3};
const saveState=()=>saves++,renderList=()=>renders++,renderDetail=()=>{},fail=()=>{},el=()=>({});
const box={replaceChildren(){},scrollTop:0},$=()=>box,requests=[];
const api=async path=>{requests.push(path);return {key:'/bridge/read'}};
(async()=>{
 classes.add('space-active');await select('/bridge/read',9);
 assert.deepEqual(requests,['/api/session?key=%2Fbridge%2Fread&start=9'],'the same read route');
 assert.deepEqual(state,{selected:'/library/own',start:3},'the Library selection is untouched');
 assert.equal(saves,0,'no POST /api/state');assert.equal(renders,0);
 classes.delete('space-active');await select('/library/next',1);
 assert.deepEqual(state,{selected:'/library/next',start:1});assert.equal(saves,1,'a Library read still saves its view');
})().catch(e=>{console.error(e);process.exitCode=1});
""")
