"""The service's existing evidence-count presentation order reaches every client."""
import json
from types import SimpleNamespace

import pytest

import navcom_navigation as navigation
from navcom_atlas import identity
from navcom_atlas_cli import render_space
from test_space_action_rail import DOM
from test_space_camera import js_between, run_js


@pytest.fixture
def grouped():
    # Alphabetic text-only matches must not bury conceptual matches. Equal
    # counts use label and exact identity, including case-insensitive labels.
    specs = [
        ('text', 'Alpha', 0, 8, 0),
        ('zero', 'Aardvark', 0, 0, 0),
        ('concept', 'Zeta', 2, 0, 0),
        ('conversation', 'Zulu', 1, 0, 2),
        ('tie-z', 'twin', 1, 0, 1),
        ('tie-a', 'Twin', 1, 0, 1),
        ('zero-z', 'zzz', 0, 0, 0),
    ]
    nodes, sources, conversations = [], [], []
    for key, label, concepts, text, chats in specs:
        project = '/work/' + key
        nodes.append(dict(id='planet:' + key, kind='planet', label=label,
                          source_scopes=[dict(source_id=key, paths=['.'])],
                          conversation_collections=['projects:' + identity(project)]))
        def hits(count):
            return [dict(relative_path=f'src/file-{n}.py', line=n+1,
                         source_path=f'{project}/src/file-{n}.py') for n in range(count)]
        sources.append(dict(source_id=key, concept_hits=hits(concepts), text_hits=hits(text)))
        conversations.extend(dict(key=f'{key}-{n}', project=project, label=label) for n in range(chats))
    result = dict(sources=sources, conversations=conversations, coverage={})
    api = SimpleNamespace(pretty_project=lambda project: project)
    navigation._place_evidence(api, nodes, result)
    return api, nodes, result


def test_shared_order_keeps_memberships_and_deterministic_ties(grouped):
    api, nodes, proof = grouped
    expected = ['concept', 'conversation', 'tie-a', 'tie-z', 'text', 'zero', 'zero-z']
    assert [p['id'] for p in proof['places']] == ['planet:' + key for key in expected]
    assert [p['has_evidence'] for p in proof['places']] == [True]*5 + [False]*2
    original = json.loads(json.dumps(proof))
    navigation._place_evidence(api, list(reversed(nodes)), proof)
    assert proof == original, 'Input catalog order must not alter ranking or exact source membership'
    assert next(p for p in proof['places'] if p['id']=='planet:text')['text_hits'] == 8
    assert all(h['place_ids']==['planet:'+s['source_id']]
               for s in proof['sources'] for field in ('concept_hits','text_hits') for h in s[field])


def test_cli_preserves_service_order_and_omits_zero_match_places(grouped, capsys):
    _, _, proof = grouped
    render_space(dict(nodes=[], evidence=proof))
    lines = capsys.readouterr().out.splitlines()
    printed = [line.rsplit(' · ', 1)[-1] for line in lines if ' · evidence found · ' in line]
    assert printed == [p['id'] for p in proof['places'] if p['has_evidence']]


def test_browser_consumes_exact_service_order_without_locale_resorting(grouped):
    _, _, proof = grouped
    renderer = js_between('function renderSearch(', 'async function changeSearchPage(')
    # Source/conversation cards are tested elsewhere; these buttons consume the
    # actual service grouping above, including equal-count case/ID ties.
    payload = dict(center=dict(id='system:fixture', label='Fixture'), nodes=[],
                   evidence=dict(places=proof['places'], sources=[], conversations=[]))
    run_js(DOM + renderer + '\nconst searchResult=' + json.dumps(payload) + r""";
const classes={add(){},remove(){},toggle(){}};
Object.defineProperty(El.prototype,'classList',{get(){return classes}});
const results=el('section'),places={children:[]},navigatorStatus={};
const route={place:'system:fixture',q:'How do the products handle login?',searchWithin:'system:fixture',local:true};
const placeBriefing=()=>null,briefingHasEvidence=()=>false,cliLine=()=>'',pageRange=()=>'',renderCarriedMatches=()=>0;
const contentsPreview=()=>null,conversationCard=()=>'',evidenceCard=()=>'',pathRow=()=>'';
const selected=[],followEvidence=place=>selected.push(place.id);
renderSearch();
const placeButtons=walk(results).filter(n=>n.attrs.class==='space-place-evidence');
for(const b of placeButtons)b.onclick();
assert.deepEqual(selected,searchResult.evidence.places.filter(p=>p.has_evidence).map(p=>p.id));
assert.deepEqual(selected,['planet:concept','planet:conversation','planet:tie-a','planet:tie-z','planet:text']);
""")
