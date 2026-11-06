"""Evidence labels use readable pinned paths without changing the source reader pin."""
from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


def program(body):
    helpers = js_between("function sourceRef(", "function sourceShell(")
    helpers += js_between("function pathRow(", "function evidenceText(")
    run_js(DOM + helpers + r"""
const opened=[];const openSource=(ref,origin)=>opened.push({ref,origin});
const hit={file_path:'/private/tmp/history/'+ 'a'.repeat(64)+'/snapshot/apps/weather/graph.py',line:34,
 text:'DecisionGraph connects the recorded evidence.',source_ref:{source_id:'revision',relative_path:'apps/weather/graph.py',line:34,
 history:'revision',snapshot:'b'.repeat(64),published:1777710000}};
""" + body)


def test_pinned_relative_path_is_visible_and_full_location_is_collapsed_copyable_provenance():
    program(r"""
const before=structuredClone(hit),card=evidenceCard(hit,'Committed source'),details=card.children.find(n=>n.tag==='details');
const visible=card.children.filter(n=>n!==details).map(words).join(' ');
assert.match(visible,/apps\/weather\/graph.py:34/);assert.ok(!visible.includes('/private/tmp/'));
assert.match(visible,/DecisionGraph connects/);assert.ok(details);assert.equal(details.hasAttribute('open'),false);
assert.ok(words(details).includes(hit.file_path));press(details,'Copy');assert.deepEqual(copied,[hit.file_path]);
const open=buttons(card,'Open source →')[0];assert.equal(open.attrs['aria-label'],'Open source apps/weather/graph.py at line 34');
open.onclick({currentTarget:open});assert.deepEqual(opened,[{origin:open,ref:{source:'revision',path:'apps/weather/graph.py',history:'revision',snapshot:'b'.repeat(64),published:1777710000,line:22,focus:34,limit:80}}]);
assert.deepEqual(hit,before);assert.deepEqual(calls,[]);
""")


def test_invalid_relative_display_paths_fall_back_without_rewriting_reader_reference():
    program(r"""
for(const path of ['../outside.py','apps/../../outside.py','/absolute.py','C:/absolute.py','apps\\outside.py','./graph.py','apps//graph.py','apps/line\n.py']){
 const item={...hit,source_ref:{...hit.source_ref,relative_path:path}},card=evidenceCard(item,'Source');
 assert.equal(card.children.some(n=>n.tag==='details'),false);assert.ok(words(card).includes(hit.file_path+':34'));
 press(card,'Open source →');assert.equal(opened.at(-1).ref.path,path,'The established source reader still validates the exact supplied ref');
}
assert.deepEqual(calls,[]);
""")


def test_provider_hits_without_pinned_relative_paths_retain_existing_display_and_context():
    program(r"""
const item={source_id:'source',source_path:'src/current.py',lineno:8,snippet:'Current provider excerpt.'},context={published:11,snapshot:'source-snapshot'};
const card=evidenceCard(item,'Source',context);assert.match(words(card),/src\/current.py:8/);assert.match(words(card),/Current provider excerpt/);
assert.equal(card.children.some(n=>n.tag==='details'),false);press(card,'Open source →');
assert.deepEqual(opened[0].ref,{source:'source',path:'src/current.py',history:'',published:11,snapshot:'source-snapshot',line:1,limit:80,focus:8});
assert.deepEqual(calls,[]);
""")
