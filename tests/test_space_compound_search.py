"""A resolved compound flight consumes its exact evidence once on arrival."""
import pytest

from test_space_journey_continuity import flight_controller


SETUP = r"""
const found={published:123,query:'matrix',scope_status:'resolved',destination:'planet:b2b',
 center:{id:'planet:b2b',label:'B2B'},intent:{action:'search',within:'planet:b2b',query:'matrix',navigate_first:true},
 nodes:[],total:0,offset:0,limit:40,more:false,
 evidence:{coverage:{catalog_published:123},sources:[{source_id:'b2b-only'}],conversations:[]}};
const arrived={...map,published:123};
async function compound(){
 input.value='fly to B2B then find matrix';const pending=search(true);
 navigation().resolve(found);await pending;
 assert.equal(route.place,'planet:b2b');assert.equal(route.q,'matrix');
 assert.equal(route.searchWithin,'planet:b2b');
}
"""


def test_compound_flight_has_one_retrieval_and_one_chart_request():
    flight_controller(SETUP + r"""
(async()=>{
 await compound();explore().resolve(arrived);await tick();
 assert.equal(requests.length,2,'Do not retrieve evidence a second time after the resolved flight');
 assert.deepEqual(requests.map(r=>r.url.pathname),['/api/navigate','/api/space']);
 assert.equal(requests[1].url.searchParams.get('action'),'explore');
 assert.equal(searchResult,found);assert.deepEqual(rendered,[found]);
 assert.equal(route.step,1);assert.equal(route.interpretedQ,'matrix');
 assert.ok(saved.every(entry=>!JSON.stringify(entry).includes('b2b-only')),'Evidence stays out of URL/history route state');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize('mismatch', ['publication','evidence_publication','scope','center','query','page','limit','unresolved'])
def test_arrival_mismatch_retrieves_again_with_exact_saved_scope(mismatch):
    change = {
        'publication': 'arrived.published=456;',
        'evidence_publication': 'found.evidence.coverage.catalog_published=456;',
        'scope': "found.intent.within='planet:other';",
        'center': "found.center.id='planet:other';",
        'query': "found.query='another phrase';",
        'page': 'found.offset=40;',
        'limit': 'found.limit=20;',
        'unresolved': "found.scope_status='choose';",
    }[mismatch]
    flight_controller(SETUP + r"""
(async()=>{
 await compound();CHANGE
 explore().resolve(arrived);await tick();
 assert.equal(requests.length,3);assert.equal(rendered.length,0);
 const replay=requests[2].url;
 assert.equal(replay.pathname,'/api/space');assert.equal(replay.searchParams.get('evidence'),'1');
 assert.equal(replay.searchParams.get('within'),'planet:b2b');assert.equal(replay.searchParams.get('q'),'matrix');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE', change))


@pytest.mark.parametrize('interruption', ['draft','clear','new_search','different_place','inactive'])
def test_compound_arrival_never_revives_superseded_evidence(interruption):
    change = {
        'draft': "input.value='unsent question';",
        'clear': "input.value='';await search(true);",
        'new_search': "input.value='find cobalt';search(true);",
        'different_place': "fly('planet:other');",
        'inactive': 'active=false;',
    }[interruption]
    flight_controller(SETUP + r"""
(async()=>{
 await compound();const arrival=explore();CHANGE
 const count=requests.length;arrival.resolve(arrived);await tick();
 assert.equal(requests.length,count,'A stale arrival must not launch another search');
 assert.ok(!rendered.includes(found));assert.notEqual(searchResult,found);
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE', change))


def test_later_restore_replays_scoped_query_without_retaining_response():
    flight_controller(SETUP + r"""
(async()=>{
 await compound();explore().resolve(arrived);await tick();
 assert.equal(requests.length,2);assert.equal(searchResult,found);
 // Back/Forward/reload call loadView without the one-arrival response argument.
 const restoring=loadView();assert.equal(requests.length,3);
 requests[2].resolve(arrived);await restoring;await tick();
 assert.equal(requests.length,4);
 const replay=requests[3].url;
 assert.equal(replay.pathname,'/api/space');assert.equal(replay.searchParams.get('action'),'search');
 assert.equal(replay.searchParams.get('within'),'planet:b2b');assert.equal(replay.searchParams.get('q'),'matrix');
 assert.equal(replay.searchParams.get('evidence'),'1');
})().catch(error=>{console.error(error);process.exitCode=1});
""")
