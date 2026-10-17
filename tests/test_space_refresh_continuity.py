"""Background chart publication must not interrupt an open work surface."""
from pathlib import Path
from test_space_camera import run_js


def test_refresh_keeps_dossier_history_reader_voice_and_unsent_draft():
    source = (Path(__file__).resolve().parents[1] / 'navcom_space.js').read_text()
    start = source.index('function mayReloadChart()')
    function = source[start:source.index('\n', start)]
    script = function + """
const assert=require('node:assert/strict');
let active=true,voice=false,reading=false,drag=null,radarDrag=false,route={q:'',selected:'',timeAt:'',dossier:'',historyPlace:''};
const input={value:''},voiceInput={active:()=>voice},actionDialog={open:false},sourceDialog={open:false};
const document={body:{classList:{contains:()=>reading}},activeElement:null};
assert.equal(mayReloadChart(),true);
for(const key of ['copiesPlace','relatedPlace','filesPlace','carriedRead','railPanel','selected','timeAt','dossier','historyPlace']){route[key]='open';assert.equal(mayReloadChart(),false);route[key]='';}
for(const box of [actionDialog,sourceDialog]){box.open=true;assert.equal(mayReloadChart(),false);box.open=false;}
voice=true;assert.equal(mayReloadChart(),false);voice=false;
reading=true;assert.equal(mayReloadChart(),false);reading=false;
route.q='matrix';input.value='matrix';assert.equal(mayReloadChart(),false);route.q='';input.value='';
drag={};assert.equal(mayReloadChart(),false);drag=null;radarDrag=true;assert.equal(mayReloadChart(),false);radarDrag=false;
input.value='An unsent question';assert.equal(mayReloadChart(),false);input.value='';
document.activeElement=input;assert.equal(mayReloadChart(),false);document.activeElement=null;
active=false;assert.equal(mayReloadChart(),false);active=true;
assert.equal(mayReloadChart(),true);
"""
    run_js(script)
    assert source.count('&&mayReloadChart())await loadView()') == 2
