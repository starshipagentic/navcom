"""The browser retains one search boundary and ignores cancelled responses."""
from pathlib import Path
import shutil
import subprocess

import pytest


JS = (Path(__file__).resolve().parents[1] / 'navcom_space.js').read_text()


def section(start, end):
    return JS[JS.index(start):JS.index(end, JS.index(start))]


def run_controller(body, helpers=''):
    if not shutil.which('node'):
        pytest.skip('Node required for bridge controller proof')
    script = "const assert=require('node:assert/strict');\n" + section('function pageOffset(', 'function renderDestinationPager(')
    script += section('async function changeSearchPage(', 'form.addEventListener(')
    script += helpers
    script += """
const SEARCH_PAGE_SIZE=40;let active=true,searchTicket=0,lastStep=0;
let route={place:'system:fixture',q:'',interpretedQ:'',searchWithin:null,searchPending:false,
 local:true,searchOffset:0,offset:0,step:0,timeAt:''};
let searchResult=null,rendered=0;
const classList={add:()=>{},remove:()=>{},toggle:()=>{}};
const results={classList,replaceChildren:()=>{},append:()=>{},querySelectorAll:()=>[],querySelector:()=>null};
const searchPanel={classList},navigatorStatus={},input={value:'find matrix',maxLength:500,focus:()=>{}},scope={checked:true};
const places={children:[]};
const buttons=new Map();
const copyRoute=()=>JSON.parse(JSON.stringify(route)),remember=()=>{},el=()=>({append:()=>{}});
const button=(label,callback)=>{buttons.set(label,callback);return {classList}};
const renderSearch=()=>{rendered++},fail=e=>{throw e};
const response=()=>({published:123,center:{id:'system:fixture',label:'Fixture'},
 intent:{action:'search',query:'matrix',within:'system:fixture'},nodes:[],total:90,offset:0,limit:40,more:true,
 evidence:{sources:[{source_id:'original-local-source'}]}});
""" + body
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_search_page_keeps_original_local_boundary_after_checkbox_changes():
    run_controller("""
const requests=[];
const api=async url=>{requests.push(url);return response()};
(async()=>{
 await search(true);
 const evidence=searchResult.evidence;
 // Changing the checkbox configures the next search; it must not rewrite the
 // saved boundary used by the current result's metadata pagination.
 scope.checked=false;route.local=false;
 await changeSearchPage(40);
 const params=new URL(requests[1],'http://localhost').searchParams;
 assert.equal(params.get('within'),'system:fixture');
 assert.equal(searchResult.evidence,evidence);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_empty_submit_cancels_inflight_scoped_response():
    run_controller("""
let resolve;
const api=()=>new Promise(done=>{resolve=done});
(async()=>{
 input.value='find matrix in Fixture';
 const pending=search(true);
 input.value='';await search(true);
 resolve({...response(),scope_status:'resolved'});await pending;
 assert.equal(route.q,'');assert.equal(route.interpretedQ,'');assert.equal(route.searchWithin,null);
 assert.equal(searchResult,null);assert.equal(rendered,0);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_restored_named_search_uses_resolved_source_pin_without_reinterpreting():
    run_controller("""
const requests=[];const api=async url=>{requests.push(url);return {published:123,nodes:[],total:0}};
(async()=>{
 route={...route,q:'find matrix in One',interpretedQ:'matrix',searchWithin:'planet:one',searchPending:false};
 input.value=route.q;scope.checked=false;route.local=false;
 await search(false);
 const url=new URL(requests[0],'http://localhost');
 assert.equal(url.pathname,'/api/space');assert.equal(url.searchParams.get('within'),'planet:one');
 assert.equal(url.searchParams.get('q'),'matrix');assert.equal(url.searchParams.get('evidence'),'1');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_clear_button_cancels_inflight_page_without_restoring_old_results():
    renderer = section('function renderSearch(){', 'async function changeSearchPage(')
    renderer = renderer.replace('function renderSearch()', 'function renderActualSearch()', 1)
    run_controller("""
let resolve;const api=()=>new Promise(done=>{resolve=done});
(async()=>{
 route={...route,q:'find matrix',interpretedQ:'matrix',searchWithin:'system:fixture'};
 searchResult=response();renderActualSearch();
 const pending=changeSearchPage(40);
 assert.equal(typeof buttons.get('Clear'),'function');buttons.get('Clear')();
 resolve({...response(),offset:40});await pending;
 assert.equal(route.q,'');assert.equal(route.interpretedQ,'');assert.equal(route.searchWithin,null);
 assert.equal(searchResult,null);assert.equal(route.searchOffset,0);assert.equal(rendered,0);
})().catch(e=>{console.error(e);process.exitCode=1});
""", helpers=renderer)


def test_source_reader_uses_pinned_hit_identity_before_legacy_display_fields():
    source_ref = section('function sourceRef(', 'function evidenceCard(')
    run_controller("""
const pinned={source_id:'source:exact',relative_path:'engine/matrix.py',line:22,
 published:111,snapshot:'a'.repeat(64)};
const ref=sourceRef({source_ref:pinned,source_id:'source:old',source_path:'/old/location.py',
 file_path:'/old/artifact.py',line:99},
 {source_id:'source:context',published:222,snapshot:'b'.repeat(64)});
assert.deepEqual(ref,{source:'source:exact',path:'engine/matrix.py',history:'',published:111,
 snapshot:'a'.repeat(64),line:10,limit:80,focus:22});
""", helpers=source_ref)
