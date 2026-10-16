"""Connections preserve pinned source identities and ignore stale navigation replies."""
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
        pytest.skip("Node required for bridge relationship proof")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_related_source_refs_preserve_snapshot_and_publication_for_exact_reads():
    helper = js_between("function relatedSourceRef(", "async function loadRelated(")
    run_js("const assert=require('node:assert/strict');\n" + helper + r"""
const original={source_id:'orchard',relative_path:'engines/v2/README.md',line:42,
 snapshot:'4d988f-published-artifact',published:1784583001.25};
assert.deepEqual(relatedSourceRef(original),{source:'orchard',path:'engines/v2/README.md',
 line:34,focus:42,limit:80,published:1784583001.25,snapshot:'4d988f-published-artifact'});
assert.equal(relatedSourceRef({...original,line:3}).line,1);
assert.equal(relatedSourceRef(null),null);
assert.equal(relatedSourceRef({source_id:'orchard'}),null);
assert.equal(relatedSourceRef({relative_path:'README.md'}),null);
assert.equal(original.line,42,'Opening a window cannot mutate the returned citation');
""")


def test_related_route_restores_query_source_page_and_camera_without_reinterpretation():
    source = (ROOT / "navcom_space.js").read_text()
    fresh = source[source.index("const fresh="):].splitlines()[0]
    restore = js_between("function restore(value)", "function setActive(")
    page = js_between("function pageOffset(", "function renderDestinationPager(")
    run_js("const assert=require('node:assert/strict');\n" + fresh + page + restore + r"""
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40,input={},scope={};let route=fresh();
const saved={...fresh(),place:'system:coast',selected:'planet:orchard',q:'matrix',local:false,
 relatedPlace:'planet:orchard',relatedQuery:'engine versions',relatedOffset:8,
 zoom:4.9,pan:{x:319,y:-214},cameraReady:true,cameraScale:.82,layoutVersion:2,
 chartLayout:{key:'system:coast|0',width:1530,height:1008,points:[{id:'planet:orchard',x:120,y:130}]},
 sourceRead:{source:'orchard',path:'engines/v2/README.md',snapshot:'pinned',published:123,line:12}};
restore(saved);assert.deepEqual(route,saved);
assert.equal(input.value,'matrix');assert.equal(scope.checked,false);
route.chartLayout.points[0].x=300;assert.equal(saved.chartLayout.points[0].x,120,'History geometry must be copied');
restore(saved);assert.equal(route.relatedQuery,'engine versions');assert.equal(route.relatedOffset,8);
""")


def test_connections_ignore_out_of_order_or_departed_place_responses_and_errors():
    load = js_between("async function loadRelated(", "function renderRelated(")
    run_js("const assert=require('node:assert/strict');\n" + load + r"""
let active=true,relatedTicket=0,route={relatedPlace:'planet:orchard',relatedQuery:'old',relatedOffset:0};
let selected={id:'planet:orchard'},view={published:123};
const relatedViews=new Map(),requests=[],renders=[];
const panel={writes:0,replaceChildren(){this.writes++}},inspector={querySelector:()=>panel};
const el=(...args)=>args,button=(...args)=>args,closeRelated=()=>{},selectedNode=()=>selected;
const renderRelated=(...args)=>renders.push(args);
const api=url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}));
(async()=>{
 const old=loadRelated(selected);route.relatedQuery='new';const current=loadRelated(selected);
 requests[1].resolve({id:'new'});await current;
 requests[0].resolve({id:'old'});await old;
 assert.equal(renders.length,1);assert.equal(renders[0][1].id,'new');
 assert.equal(relatedViews.size,1,'Stale results must not enter the panel cache');
 assert.equal(new URL(requests[1].url,'http://localhost').searchParams.get('q'),'new');
 // A successful response cannot paint into a different selected destination.
 route.relatedQuery='departed';const departing=loadRelated(selected);selected={id:'planet:other'};
 requests[2].resolve({id:'departed'});await departing;assert.equal(renders.length,1);
 // Deactivated panels must also ignore late failures, not replace their previous contents.
 selected={id:'planet:orchard'};route.relatedQuery='failure';const failing=loadRelated(selected);
 const writesBefore=panel.writes;active=false;requests[3].reject(Error('late source failure'));await failing;
 assert.equal(panel.writes,writesBefore,'A late error cannot mutate a deactivated panel');
 // Reopening a new query after returning must still work normally.
 active=true;route.relatedQuery='back';const back=loadRelated(selected);
 requests[4].resolve({id:'back'});await back;assert.equal(renders.length,2);
 assert.equal(renders[1][1].id,'back');
})().catch(error=>{console.error(error);process.exitCode=1});
""")
