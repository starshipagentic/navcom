"""Navigator cargo federation preserves place and physical-copy boundaries."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

import navcom_navigation as navigation
from test_ship_context import require_native, ship


def node(identity, kind, **extra):
    return dict(id=identity, kind=kind, label=identity, parent_id='galaxy:owner',
                position={}, locations=[], evidence=[], examples=[], **extra)


def test_product_association_takes_only_native_ship_and_its_one_stored_copy():
    product=node('planet:orchard','planet',ship_links=[
        dict(id='ship:work',relation='source_context'),dict(id='ship:other',relation='related')])
    working=node('ship:work','ship',ship_links=[dict(id='ship:archive',relation='stored_copy'),
        dict(id='ship:other',relation='working_copy'),dict(id='planet:foreign',relation='source_context')])
    archive=node('ship:archive','ship',form='archive',ship_links=[dict(id='ship:other',relation='working_copy')])
    other=node('ship:other','ship')
    all_nodes=[product,working,archive,other,node('planet:foreign','planet')]
    found=navigation._carried_candidates(all_nodes,[product],product)
    assert {n['id'] for n in found}=={'ship:work','ship:archive'}


def test_exact_ship_never_substitutes_linked_archive_or_working_copy():
    working=node('ship:work','ship',ship_links=[dict(id='ship:archive',relation='stored_copy')])
    archive=node('ship:archive','ship',form='archive')
    assert navigation._carried_candidates([working,archive],[working,archive],working)==[working]
    assert navigation._carried_candidates([working,archive],[working,archive],archive)==[archive]


def test_district_does_not_inherit_the_parent_products_whole_cargo():
    district=node('district:auth','district')
    product=node('planet:orchard','planet',ship_links=[dict(id='ship:work',relation='source_context')])
    working=node('ship:work','ship')
    assert navigation._carried_candidates([district,product,working],[district],district)==[]


def test_base_uses_containment_without_borrowing_archives_on_another_base():
    base=node('base:one','starbase')
    working=node('ship:work','ship',ship_links=[dict(id='ship:archive',relation='stored_copy')])
    archive=node('ship:archive','ship',form='archive')
    assert navigation._carried_candidates([base,working,archive],[base,working],base)==[working]


def test_public_navigator_native_cargo_cache_and_original_turn_replay(ship,tmp_path):
    require_native()
    entity,root,_=ship
    galaxy=node('galaxy:owner','galaxy');galaxy['parent_id']=None
    chart=tmp_path/'space.json'
    chart.write_text(json.dumps(dict(schema_version=1,published=123,entities=[galaxy,entity],edges=[],coverage={})))
    script=Path(__file__).resolve().parents[1]/'navcom.py'
    index=tmp_path/'absent.sqlite'
    def cli(argv):
        p=subprocess.run([sys.executable,str(script),*argv,'--index',str(index),'--json'],capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        return json.loads(p.stdout)
    args=['atlas','navigate','find amber','--within',entity['id'],'--space-cache',str(chart),
          '--source-cache',str(tmp_path/'sources')]
    first=cli(args);cargo=first['evidence']['carried'];hit=cargo['hits'][0]
    assert hit['ship_id']==entity['id'] and hit['session_id']=='session-0' and hit['index']==3
    assert not first['evidence']['conversations'] and not first['evidence']['sources']
    opened=cli(shlex.split(hit['open_command'])[1:])
    assert opened['messages'][0]['index']==3
    assert opened['messages'][0]['text']=='Why did Orchard choose amber storage?'
    assert opened['catalog']==hit['catalog_sha256']
    again=cli(args)['evidence']['carried']
    assert again['cached']
    assert [h['text'] for h in again['hits']]==[h['text'] for h in cargo['hits']]
    assert not index.exists(), 'Carried context must not create a host conversation index.'
