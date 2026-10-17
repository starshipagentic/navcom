"""Large destination sets remain reachable without changing search or camera state."""
import json
from pathlib import Path
import subprocess
import sys


import navcom_space
from navcom_web import WebApp
from test_space_camera import js_between, run_js

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'navcom_space.js').read_text()


def large_catalog(tmp_path):
    def node(i,label,kind,parent):
        return dict(id=i,label=label,kind=kind,parent_id=parent,position=dict(x=len(label)*7,y=len(i)*11),
                    locations=[],evidence=[],examples=[],source_ids=[],source_scopes=[],conversation_collections=[])
    nodes=[node('galaxy:owner','Your galaxy','galaxy',None),node('system:fixture','Independent fixture','system','galaxy:owner')]
    nodes += [node(f'planet:{i:03}',f'Product {i:03}','planet','system:fixture') for i in range(205)]
    path=tmp_path/'space.json'
    path.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    return path,nodes[2:]


def test_all_large_place_destinations_are_reachable_in_identical_cli_api_pages(tmp_path,monkeypatch):
    cache,expected=large_catalog(tmp_path)
    expected=[{**node,'contents':dict(basis='published_direct_children',groups=[],total=0)} for node in expected]
    sources=tmp_path/'sources';index=tmp_path/'absent.sqlite'
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(cache));monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(sources))
    app=WebApp(None,index);seen=[]
    # Places carry their CLI commands; adapters only pin them to the caches in use.
    bare=lambda nodes:[{k:v for k,v in n.items() if k!='commands'} for n in nodes]
    for offset,count in ((0,80),(80,80),(160,45)):
        page=app.get(None,'/api/space',dict(action=['explore'],within=['system:fixture'],offset=[str(offset)],limit=['80']))
        direct=navcom_space.view(cache,action='explore',within='system:fixture',offset=offset,limit=80)
        assert bare(page['nodes'])==bare(direct['nodes'])==expected[offset:offset+count]
        assert [n['commands'] for n in direct['nodes']]==[navcom_space.commands(n) for n in expected[offset:offset+count]]
        assert page['more']==(offset+count<205)
        assert page['total']==205 and len(page['nodes'])==count
        seen.extend(n['id'] for n in page['nodes'])
    assert len(seen)==len(set(seen))==205
    cli=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','explore','system:fixture',
                        '--offset','160','--limit','80','--space-cache',str(cache),'--source-cache',str(sources),
                        '--index',str(index),'--json'],capture_output=True,text=True)
    assert cli.returncode==0,cli.stderr
    assert bare(json.loads(cli.stdout)['nodes'])==expected[160:]
    assert [n['commands'] for n in json.loads(cli.stdout)['nodes']]==[n['commands'] for n in page['nodes']]
    assert not index.exists()


def test_destination_page_history_restores_query_camera_selection_and_link():
    helpers=js_between('function pageOffset(', 'function renderDestinationPager(')
    change=js_between('async function changeDestinationPage(', 'function renderCrumbs(')
    restore=js_between('function restore(value){','function setActive(')
    url=js_between('function url(){','function remember(')
    fresh=JS[JS.index('const fresh='):JS.index('\n',JS.index('const fresh='))]
    run_js("const assert=require('node:assert/strict');\n"+fresh+helpers+change+restore+url+"""
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40,location={href:'http://localhost/?view=space'};
let route={...fresh(),place:'system:fixture',q:'How does login work?',interpretedQ:'How does login work?',
           zoom:1.8,pan:{x:19,y:-41},selected:'planet:042',searchOffset:40};
let active=true,view={total:205},lastStep=0,input={},scope={},loaded=[];
const records=[],destinationPager={querySelectorAll:()=>[],querySelector:()=>null};
const remember=(push=false)=>records.push({push,state:JSON.parse(JSON.stringify(route))});
const loadView=async()=>loaded.push({...route});
(async()=>{
 await changeDestinationPage(80);
 assert.equal(route.offset,80);assert.equal(route.q,'How does login work?');assert.equal(route.searchOffset,40);
 assert.equal(route.zoom,1.8);assert.deepEqual(route.pan,{x:19,y:-41});assert.equal(route.selected,'');
 assert.equal(new URL(url()).searchParams.get('offset'),'80');
 assert.equal(new URL(url()).searchParams.get('search_offset'),'40');
 assert.equal(records[0].state.selected,'planet:042');assert.equal(records[1].push,true);
 restore(records[0].state); // Browser Back restores the full previous viewpoint.
 assert.equal(route.offset,0);assert.equal(route.selected,'planet:042');assert.equal(route.zoom,1.8);
 assert.deepEqual(route.pan,{x:19,y:-41});assert.equal(route.q,'How does login work?');
 assert.equal(pageRange(160,45,205),'161–205 of 205');assert.equal(pageOffset(-1,80),0);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_search_pages_fetch_only_metadata_and_keep_original_evidence_and_map():
    helpers=js_between('function pageOffset(', 'function renderDestinationPager(')
    change=js_between('async function changeSearchPage(', 'async function search(')
    run_js("const assert=require('node:assert/strict');\n"+helpers+change+"""
const SEARCH_PAGE_SIZE=40;let active=true,searchTicket=0,lastStep=0;
let route={place:'system:fixture',q:'find Product',interpretedQ:'Product',local:true,searchOffset:0,offset:80,
           zoom:2,pan:{x:7,y:9},selected:'planet:090',step:2};
const evidence={sources:[{text_hits:[{match:'original published evidence'}]}]};
let searchResult={published:123,nodes:[{id:'planet:000'}],total:205,more:true,offset:0,limit:40,evidence};
const results={querySelectorAll:()=>[],querySelector:()=>null},navigatorStatus={},records=[],requests=[];
const remember=(push=false)=>records.push({push,state:JSON.parse(JSON.stringify(route))});
const renderSearch=()=>{},fail=error=>{throw error};
const api=async url=>{requests.push(url);return {published:123,nodes:[{id:'planet:040'}],entities:[{id:'planet:040'}],offset:40,total:205,more:true,limit:40}};
(async()=>{
 await changeSearchPage(40);
 const query=new URL(requests[0],'http://localhost').searchParams;
 assert.equal(query.get('offset'),'40');assert.equal(query.get('q'),'Product');assert.equal(query.has('evidence'),false);
 assert.equal(searchResult.evidence,evidence);assert.equal(route.offset,80);assert.equal(route.selected,'planet:090');
 assert.equal(route.zoom,2);assert.deepEqual(route.pan,{x:7,y:9});assert.equal(route.q,'find Product');
 assert.equal(route.searchOffset,40);assert.equal(records[0].state.searchOffset,0);assert.equal(records[1].push,true);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_page_projection_returns_identical_ids_positions_and_canvas_on_back():
    project=js_between('function projectedNodes(', 'function renderMap(')
    run_js("const assert=require('node:assert/strict');\n"+project+"""
const PAGE_SIZE=80;let innerWidth=1440,geometry={},layoutNarrow=false;
const stage={clientWidth:900};let view={center:{position:{x:0,y:0}},total:205};
const all=Array.from({length:205},(_,i)=>({id:'planet:'+i,position:{x:(i%11)*42,y:Math.floor(i/11)*25}}));
for(const width of [1440,486]){
 innerWidth=width;
 const first=projectedNodes(all.slice(0,80)),size={...geometry};
 projectedNodes(all.slice(160));assert.deepEqual(geometry,size);
 const returned=projectedNodes(all.slice(0,80));assert.deepEqual(returned,first);
}
""")
