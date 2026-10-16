"""Carried Navigator hits open the exact native turn without losing the journey."""
from test_space_carried_context import run_controller, section


HELPERS = section('function openCarriedMatch(', 'function renderSearch(')
SETUP = """
const flights=[],notices=[];
const fly=(...args)=>flights.push(args),message=text=>notices.push(text);
const results=el('section');
const hit={ship_id:ship.id,session_id:'same-session',index:7,catalog_sha256:catalog,
 context_ref:{ship_id:ship.id,session_id:'same-session',index:7,catalog_sha256:catalog},
 ship:{...ship,form:'archive',physical:{path:'/exact/archive'}},title:'',text:'Amber storage decision\\nDetails retained',
 provider:'fixture',role:'assistant',open_command:'navcom atlas context exact'};
"""


def test_result_opens_exact_physical_ship_catalog_and_original_turn():
    run_controller("""
openCarriedMatch(hit);
assert.equal(flights.length,1);
assert.deepEqual(flights[0],[ship.id,'',{place:ship.id,action:'open',q:'',ref:'same-session',turn:7,
 offset:0,chars:8000,catalog}]);
assert.deepEqual(notices,[]);
""", extra=HELPERS+SETUP)


def test_mismatched_or_missing_pins_never_open_a_different_copy():
    run_controller("""
for(const changed of [{...hit,ship_id:other.id},{...hit,index:8},{...hit,catalog_sha256:newCatalog},
 {...hit,context_ref:{...hit.context_ref,catalog_sha256:'not-a-hash'},catalog_sha256:'not-a-hash'}])
 openCarriedMatch(changed);
assert.equal(flights.length,0);assert.equal(notices.length,4);
""", extra=HELPERS+SETUP)


def test_matching_but_absent_identity_pin_or_turn_never_opens_unpinned_context():
    run_controller("""
for(const key of ['ship_id','session_id','catalog_sha256','index']){
 const changed={...hit,context_ref:{...hit.context_ref}};
 delete changed[key];delete changed.context_ref[key];
 openCarriedMatch(changed);
}
assert.equal(flights.length,0);assert.equal(notices.length,4);
""", extra=HELPERS+SETUP)


def test_matching_empty_pins_and_noninteger_turns_are_rejected_but_turn_zero_opens():
    run_controller("""
const invalid=[['ship_id',''],['ship_id','  '],['session_id',''],['session_id','  '],
 ['catalog_sha256',''],['catalog_sha256',null],['index',null],['index',false],
 ['index',-1],['index',1.5],['index','7'],['index',Number.MAX_SAFE_INTEGER+1]];
for(const [key,value] of invalid)
 openCarriedMatch({...hit,[key]:value,context_ref:{...hit.context_ref,[key]:value}});
openCarriedMatch(null);openCarriedMatch({});
assert.equal(flights.length,0);assert.equal(notices.length,invalid.length+2);
openCarriedMatch({...hit,index:0,context_ref:{...hit.context_ref,index:0}});
assert.equal(flights.length,1);assert.equal(flights[0][2].turn,0);
assert.equal(flights[0][2].catalog,catalog);
""", extra=HELPERS+SETUP)


def test_cards_use_verbatim_excerpt_and_physical_copy_instead_of_invented_title():
    run_controller("""
const count=renderCarriedMatches({hits:[hit],coverage:{eligible:4,searched:2,cached_ships:1,
 unavailable_ids:['remote'],unsearched_ids:['remaining'],truncated:true}});
assert.equal(count,1);
const text=walk(results).flatMap(x=>x.children||[]).filter(x=>typeof x==='string');
assert.ok(text.includes('Matched passage: Amber storage decision'));
assert.ok(text.includes('/exact/archive'));
assert.ok(text.some(x=>x.includes('Repeat this search to continue')));
click(results,'Read original turn 7 in Orchard →');assert.equal(flights[0][0],ship.id);
""", extra=HELPERS+SETUP)
