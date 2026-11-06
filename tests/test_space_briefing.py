"""Leaf arrivals and local questions render the shared, cited place briefing."""
import json

from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


BRIEFING = {
    "schema_version": 1,
    "place": {"id": "planet:harbor", "label": "Harbor pairing", "kind": "planet"},
    "summary": {"text": "A paired review workspace for analysts.", "basis": "attributed_excerpts", "evidence_ids": ["c1"]},
    "evidence": [
        {"id": "s1", "kind": "source", "label": "README purpose", "text": "Compare forecasts with recorded observations.",
         "source_ref": {"source_id": "source:harbor", "relative_path": "README.md", "line": 24, "published": 1700, "snapshot": "receipt-one"}},
        *[{"id": f"c{i}", "kind": "conversation", "label": f"Recorded review {i}", "text": f"Review experiment {i} with paired evidence.",
           "conversation_ref": {"key": f"codex:session-{i}", "ref": f"ref-{i}", "turn": i + 7, "project": "/work/harbor"}} for i in range(1, 4)],
    ],
    "coverage": {"indexed_conversations": 3, "selected_conversations": 3, "excerpted_conversations": 3, "source_available": True,
                 "complete": False, "limitations": ["Only retained snapshots and selected conversation excerpts are included."]},
}


def program(body):
    helpers = js_between("function placeBriefing(", "function renderMap(")
    helpers += js_between("function sourceRef(", "function evidenceCard(")
    setup = r"""
const opened=[],readTurns=[];const openSource=(ref)=>opened.push(ref),readConversation=(key,turn)=>readTurns.push({key,turn});
const placeKind=node=>node.kind,art=()=>el('span',{},'planet art');
let route={place:'planet:harbor',local:true,pan:{x:41,y:23},zoom:2,selected:'',timeAt:''};
const scope={checked:true},input={focus(){},scrollIntoView(){}},remember=()=>calls.push('remember');
const openFiles=node=>calls.push({files:node.id}),openRailPanel=(node,panel)=>calls.push({place:node.id,panel});
const center={id:'planet:harbor',kind:'planet',label:'Harbor pairing',commands:{files:['navcom','atlas','files','planet:harbor'],conversation_search:[['navcom','atlas','explore','projects:harbor']]},source_scopes:[{source_id:'source:harbor',paths:['.']}]};
const response={center,nodes:[],briefing:BRIEFING};
const shipRecords=new Map(),renderShipCopies=()=>{},shipFact=(label,value)=>el('div',{},label,value),recordedTime=value=>value||'Date not recorded';
const pathRow=path=>el('code',{},path);
function classList(){const set=new Set();return {add(...names){for(const n of names)set.add(n)},remove(...names){for(const n of names)set.delete(n)},contains:n=>set.has(n),toggle(n,on){if(on??!set.has(n))set.add(n);else set.delete(n)}};}
Object.defineProperty(El.prototype,'classList',{get(){return this._classes??=classList();}});
Object.defineProperty(El.prototype,'style',{get(){return this._style??={};}});
""".replace("BRIEFING", json.dumps(BRIEFING))
    run_js(DOM + helpers + setup + body)


def test_arrival_shows_all_three_recorded_conversations_and_exact_source_reader_links():
    program(r"""
const before=structuredClone(route),panel=arrivalWorkspace(response);
assert.match(words(panel),/A paired review workspace for analysts/);
assert.match(words(panel),/3 indexed conversations · 3 excerpted/);
assert.equal(buttons(panel,'Read conversation →').length,3);
buttons(panel,'Read conversation →')[1].onclick();assert.deepEqual(readTurns,[{key:'codex:session-2',turn:9}]);
press(panel,'Read source →');assert.deepEqual(opened,[{source:'source:harbor',path:'README.md',history:'',published:1700,snapshot:'receipt-one',line:12,limit:80,focus:24}]);
press(panel,'Browse saved files');press(panel,'Browse conversations');
assert.deepEqual(calls,[{files:'planet:harbor'},{place:'planet:harbor',panel:'conversations'}]);
assert.deepEqual(route,before,'Reading briefing content does not mutate the chart camera, date or selected place');
assert.ok(!words(panel).includes('You’ve arrived.'));
""")


def test_briefing_belongs_only_to_its_response_and_plain_text_never_creates_places():
    program(r"""
assert.equal(placeBriefing({...response,center:{id:'planet:other'}}),null);
assert.equal(placeBriefing({...response,briefing:{...response.briefing,schema_version:2}}),null);
assert.equal(placeBriefing({...response,briefing:{...response.briefing,place:{...response.briefing.place,kind:'ship'}}}),null);
const b=structuredClone(response.briefing);b.evidence[0].text='<script>fly("planet:other")</script>';
const panel=briefingPanel(b);assert.match(words(panel),/<script>fly/);
assert.equal(walk(panel).filter(n=>n.tag==='script').length,0);
assert.deepEqual(calls,[]);assert.equal(route.place,'planet:harbor');
const unavailable={...b,summary:{basis:'unavailable',text:''},evidence:[],coverage:{source_available:false,limitations:['Working location unavailable; retained history may still exist.']}};
assert.equal(briefingHasEvidence(unavailable),false);assert.match(words(briefingPanel(unavailable)),/description has not been recorded/);
assert.match(words(briefingPanel(unavailable)),/Working location unavailable/);
""")


def test_optional_answer_is_labeled_and_citations_open_only_recorded_receipts():
    program(r"""
const b=structuredClone(response.briefing);b.answer={available:true,text:'It compares forecast evidence with a reviewer.',model:'local-reviewer',cached:true,citations:['s1','c2','not-recorded']};
const panel=briefingPanel(b,{heading:'Your question'});assert.match(words(panel),/Answer from the cited local evidence · local-reviewer · cached/);
press(panel,'README purpose');press(panel,'Recorded review 2');assert.equal(opened[0].snapshot,'receipt-one');assert.deepEqual(readTurns,[{key:'codex:session-2',turn:9}]);
b.answer={available:false,message:'No configured model is currently available.'};const fallback=words(briefingPanel(b));
assert.match(fallback,/A paired review workspace for analysts/);assert.match(fallback,/No configured model/);assert.ok(!fallback.includes('Answer from the cited'));
b.answer={available:true,text:'Two claims',claims:[{text:'Source describes comparison.',citations:['s1']},{text:'A review was recorded.',citations:['c2']}]};
const attributed=briefingPanel(b),claims=walk(attributed).filter(n=>n.attrs.class==='space-briefing-claim');
assert.equal(claims.length,2);assert.deepEqual(buttons(claims[0]).map(words),['README purpose']);assert.deepEqual(buttons(claims[1]).map(words),['Recorded review 2']);
b.evidence.push({id:'d1',kind:'description',label:'Recorded project description',text:'A historical project description.'});
b.answer.claims=[{text:'The description records an analyst project.',citations:['d1']}];
const described=walk(briefingPanel(b)).find(n=>n.attrs.class==='space-briefing-claim');
assert.match(words(described),/Recorded clue: Recorded project description/);assert.equal(buttons(described).length,0,'Description attribution must not invent a source link');
""")


def test_markdown_titles_and_links_are_readable_plain_text_with_full_evidence_retained():
    program(r"""
const native='A very long native session title '.repeat(8);
const raw='# Paired observation notebook\n\nRead [the design notes](https://example.test/very/long/(draft)/path) before comparing observations.\n'+('A recorded detail. '.repeat(40));
const item={...response.briefing.evidence[1],label:native,text:raw},display=briefingDisplay(item),card=briefingCard(item);
assert.equal(display.title,'Paired observation notebook');assert.equal(display.native,native);assert.equal(display.raw,raw);
const title=walk(card).find(n=>n.tag==='h4'),preview=walk(card).find(n=>n.attrs.class==='space-briefing-excerpt');
assert.equal(title.attrs.title,native);assert.ok(words(preview).includes('Read the design notes before comparing observations.'));
assert.ok(!words(preview).includes('https://'));assert.ok(!words(preview).includes('# Paired'));assert.ok(display.excerpt.length<=420);
assert.equal(walk(card).filter(n=>n.tag==='a').length,0,'Formatting never introduces external or inferred links');
assert.equal(walk(card).find(n=>n.tag==='pre').textContent,'');assert.equal(words(walk(card).find(n=>n.tag==='pre')),raw);
press(card,'Read conversation →');assert.deepEqual(readTurns,[{key:'codex:session-1',turn:8}]);
const withoutH1=briefingDisplay({label:native,text:'## A subsection\nSome recorded text.'});assert.ok(withoutH1.title.length<=88);assert.ok(withoutH1.citation.length<=52);assert.ok(withoutH1.title.startsWith('A very long native'));
const fenced=briefingDisplay({label:'Actual recorded title',text:String.fromCharCode(96).repeat(3)+'\n# Code, not a document title\n'+String.fromCharCode(96).repeat(3)+'\n\nPlain content.'});
assert.equal(fenced.title,'Actual recorded title');
""")


def test_question_with_briefing_is_useful_even_when_native_keyword_matches_are_empty():
    renderer = js_between("function renderSearch(", "async function changeSearchPage(")
    program(renderer + r"""
const results=el('section'),places={children:[]},navigatorStatus={},searchPanel=el('section');let searchTicket=0;
const cliLine=()=>el('code',{},'native command'),pageRange=()=>'',renderCarriedMatches=()=>0;
const contentsPreview=()=>null,conversationCard=()=>el('article'),evidenceCard=()=>el('article'),fly=()=>{},search=()=>{};
let searchResult={...response,query:'What happens here?',intent:{action:'search'},evidence:{query_plan:{style:'question',text_terms:[]},sources:[],conversations:[]},steps:['Read selected local evidence'],cli_command:['navcom','atlas','navigate','What happens here?']};
renderSearch();const output=words(results);
assert.match(output,/About Harbor pairing/);assert.match(output,/A paired review workspace for analysts/);
assert.ok(!output.includes('No evidence found'));assert.ok(!output.includes('Following terms:'));
assert.match(navigatorStatus.textContent,/Project briefing from the recorded evidence/);
assert.ok(output.indexOf('A paired review')<output.indexOf('native command'));
searchResult={center:response.center,nodes:[],evidence:{query_plan:{style:'question',text_terms:[]}}};renderSearch();
assert.match(words(results),/No evidence found/);assert.ok(!words(results).includes('Following terms:'));
""")


def test_only_empty_current_products_and_ships_become_arrival_workspaces_without_moving_camera():
    renderer = js_between("function renderMap(", "function renderFooter(")
    program(renderer + r"""
const places=el('div'),orbit=el('svg'),universe={style:{}},orientation=el('div'),empty=el('div'),stage=el('div');
let view=response,geometry={width:1100,height:740},fleetMap=null,initialized=0;
const retainMapLayout=x=>x,projectedNodes=nodes=>nodes.map((n,i)=>({n,x:100+i*100,y:100})),renderBerths=()=>{},svgEl=el;
const renderRadar=()=>{},renderOverviewLabels=()=>{},initializeCamera=()=>initialized++,transform=()=>{},pageRange=()=>'',destinationQualifier=()=>'',setSelection=()=>{};
const before=structuredClone(route);renderMap();assert.ok(stage.classList.contains('space-arrival'));assert.match(words(empty),/What happens here/);assert.deepEqual(route,before);
route.timeAt='2026-01-01';renderMap();assert.ok(!stage.classList.contains('space-arrival'));
route.timeAt='';view={...response,center:{id:'ship:one',kind:'ship',label:'Working ship'}};renderMap();assert.ok(stage.classList.contains('space-arrival'));assert.match(words(empty),/mission has not been recorded/);assert.match(words(empty),/No carried-context reader/);
view={...response,nodes:[{id:'district:code',kind:'district',label:'Code'}]};renderMap();assert.ok(!stage.classList.contains('space-arrival'));assert.ok(empty.classList.contains('hidden'));
assert.equal(initialized,4,'Existing map camera initialization remains in place');
""")
