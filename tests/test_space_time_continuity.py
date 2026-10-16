"""The historical bridge reopens its pinned session, never a fresh HEAD by accident."""
import pytest

from test_space_camera import ROOT, js_between, run_js


def time_controller(checks):
    source = (ROOT / 'navcom_space.js').read_text()
    fresh = source[source.index('const fresh='):].splitlines()[0]
    helpers = js_between('function datedRoute(', 'function timeLabel(')
    helpers += js_between('function url(', '// A tab owns')
    helpers += js_between('function pageOffset(', 'function pageRange(')
    helpers += js_between('function restore(value)', 'function setActive(')
    helpers += js_between('function setTime(', 'function returnToPresent(')
    helpers += js_between('async function loadSystemTime(', 'function applySystemTime(')
    helpers += js_between('async function search(', "form.addEventListener('submit'")
    run_js(fresh + r"""
const assert=require('node:assert/strict');
const PAGE_SIZE=80,SEARCH_PAGE_SIZE=40;
let route={...fresh(),place:'system:orchard',timeAt:'2025-04-01T00:00:00Z',timeQ:'login',step:2};
let active=true,timeTicket=0,timeBusy=false,timeData=null,lastStep=2,searchTicket=0;
const systemViews=new Map(),requests=[],saved=[],rendered=[];
const input={value:'',maxLength:500,focus(){}},scope={},view={center:{id:'system:orchard'}};
const results={classList:{add(){},remove(){}}},places={children:[]};
const timeResults={classList:{remove(){}},replaceChildren(){},append(){},querySelectorAll(){return []}};
const navigatorStatus={textContent:''};
const no=()=>{},loadDatedConversations=no,renderTimeBar=no,applySystemTime=no,renderSelection=no,message=no;
const voiceInput={cancel:no};
const renderTimeResults=()=>rendered.push(timeData);
const el=no,button=no,timeLabel=String,returnToPresent=no;
const remember=()=>saved.push(structuredClone(route));
const api=(url,body)=>new Promise((resolve,reject)=>requests.push({url,body:structuredClone(body),resolve,reject}));
const location={href:'http://localhost:62811/?view=space'};
const sessionA='a'.repeat(64),sessionB='b'.repeat(64);
function page(session=sessionA,offset=0){return {session_id:session,cursor:session+':'+offset,
 next_cursor:offset<4?session+':4':null,as_of:route.timeAt,selected_place:{id:'system:orchard'},
 coverage:{completed_scopes:offset+4,eligible_scopes:8},commit:session==='a'.repeat(64)?'old-head':'new-head'};}
async function finish(response=page()){const pending=loadSystemTime();requests.at(-1).resolve(response);await pending;}
""" + helpers + checks)


def test_first_page_reload_reuses_returned_pin_after_head_changes():
    time_controller(r"""
(async()=>{
 await finish();assert.equal(requests[0].body.cursor,'');
 assert.equal(route.timeCursor,sessionA+':0');
 assert.equal(saved.at(-1).timeCursor,sessionA+':0');
 assert.equal(systemViews.get(timeKey()),timeData);
 assert.equal(systemViews.has(timeKey('')),false,'An unpinned cache key cannot impersonate a pinned session');
 const preserved=structuredClone(saved.at(-1));
 // Reload restores history state, but clears runtime caches. A new unpinned
 // request would resolve the newer HEAD; the saved cursor must prevent it.
 systemViews.clear();timeData=null;route=fresh();restore(preserved);
 const pending=loadSystemTime(),request=requests.at(-1);
 assert.equal(request.body.cursor,sessionA+':0');
 request.resolve(request.body.cursor?page(sessionA):page(sessionB));await pending;
 assert.equal(timeData.session_id,sessionA);assert.equal(timeData.commit,'old-head');
 assert.equal(route.timeQ,'login');assert.equal(route.place,'system:orchard');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_dated_search_restarts_query_page_without_repinning_after_head_changes():
    time_controller(r"""
(async()=>{
 await finish();
 const continuation=loadSystemTime(timeData.next_cursor);
 requests.at(-1).resolve(page(sessionA,4));await continuation;
 route.selected='planet:pears';route.pan={x:73,y:-31};route.zoom=1.8;
 const original=structuredClone(route),originalPage=timeData;
 input.value='Cognito access';const pending=search(),request=requests.at(-1);
 assert.equal(request.body.cursor,sessionA+':0','A new dated query restarts the page, not the repository HEADs');
 assert.equal(request.body.q,'Cognito access');assert.equal(request.body.at,original.timeAt);
 // The provider has a newer HEAD now. Only the original pin selects old code.
 request.resolve({...page(request.body.cursor?sessionA:sessionB),query:'Cognito access'});await pending;
 assert.equal(timeData.commit,'old-head');assert.equal(route.timeCursor,sessionA+':0');
 assert.equal(route.timeQ,'Cognito access');assert.equal(route.step,original.step+1);
 for(const field of ['timeAt','place','selected','pan','zoom'])assert.deepEqual(route[field],original[field]);
 const searched=structuredClone(route),count=requests.length;
 restore(original);timeData=null;await loadSystemTime();
 assert.equal(requests.length,count);assert.equal(timeData,originalPage,'Back restores the prior query and page');
 restore(searched);timeData=null;systemViews.clear();
 const copied=url();assert.equal(copied.searchParams.get('time_cursor'),sessionA+':0');
 assert.equal(copied.searchParams.get('q'),'Cognito access');
 const reload=loadSystemTime();assert.equal(requests.at(-1).body.cursor,sessionA+':0');
 requests.at(-1).resolve({...page(sessionA),query:'Cognito access'});await reload;
 assert.equal(timeData.commit,'old-head');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_explicit_date_change_starts_a_new_journey_and_cancels_older_query():
    time_controller(r"""
(async()=>{
 await finish();input.value='older query';const oldSearch=search(),oldRequest=requests.at(-1);
 assert.equal(oldRequest.body.cursor,sessionA+':0');
 const changed=setTime('2025-05-01T00:00:00Z','new date question'),newRequest=requests.at(-1);
 assert.equal(newRequest.body.cursor,'','Explicit date controls start a fresh dated journey');
 newRequest.resolve({...page(sessionB),query:'new date question'});await changed;
 const current=structuredClone(route),currentPage=timeData;
 oldRequest.resolve({...page(sessionA),as_of:'2025-04-01T00:00:00Z',query:'older query'});await oldSearch;
 assert.deepEqual(route,current);assert.equal(timeData,currentPage);
 assert.equal(route.timeCursor,sessionB+':0');assert.equal(route.timeQ,'new date question');
 assert.equal(systemViews.size,2,'The superseded query cannot add old response data');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_dated_query_clear_and_failed_search_keep_the_pin_without_unpinned_fallback():
    time_controller(r"""
(async()=>{
 await finish();
 input.value='missing term';const failed=search(),request=requests.at(-1);
 assert.equal(request.body.cursor,sessionA+':0');
 request.reject(Error('Snapshot unavailable'));await failed;
 assert.equal(route.timeCursor,sessionA+':0');assert.equal(requests.length,2);
 input.value='';const cleared=search(),emptyRequest=requests.at(-1);
 assert.equal(emptyRequest.body.cursor,sessionA+':0');assert.equal(emptyRequest.body.q,'');
 emptyRequest.resolve({...page(sessionA),query:''});await cleared;
 assert.equal(timeData.commit,'old-head');assert.equal(route.timeQ,'');
 route.timeCursor='invalid-saved-pin';input.value='another question';
 const invalid=search(),badRequest=requests.at(-1);
 assert.equal(badRequest.body.cursor,'invalid-saved-pin');
 badRequest.reject(Error('Invalid system history cursor'));await invalid;
 assert.equal(requests.length,4,'Invalid cursor rejection cannot start a new unpinned session');
 assert.equal(route.timeCursor,'invalid-saved-pin');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_continuation_and_back_restore_the_exact_pinned_page_from_cache_or_reload():
    time_controller(r"""
(async()=>{
 await finish();const first=structuredClone(saved.at(-1));
 const next=loadSystemTime(timeData.next_cursor);assert.equal(requests.at(-1).body.cursor,sessionA+':4');
 requests.at(-1).resolve(page(sessionA,4));await next;const continued=structuredClone(saved.at(-1));
 assert.equal(route.timeCursor,sessionA+':4');assert.equal(systemViews.size,2);
 route=fresh();restore(first);timeData=null;const count=requests.length;await loadSystemTime();
 assert.equal(requests.length,count,'Back should use the cached first pinned page');
 assert.equal(timeData.cursor,sessionA+':0');
 route=fresh();restore(continued);timeData=null;systemViews.clear();
 const reload=loadSystemTime();assert.equal(requests.at(-1).body.cursor,sessionA+':4');
 requests.at(-1).resolve(page(sessionA,4));await reload;
 assert.equal(timeData.session_id,sessionA);assert.equal(timeData.cursor,sessionA+':4');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize('invalid', ['missing', 'suffix', 'session_mismatch', 'different_pinned_page'])
def test_invalid_cursor_response_does_not_replace_valid_historical_state(invalid):
    change = {
        'missing': 'delete bad.cursor;',
        'suffix': "bad.cursor+='trailing-data';",
        'session_mismatch': 'bad.session_id=sessionB;',
        'different_pinned_page': 'bad.cursor=sessionA+\':0\';',
    }[invalid]
    time_controller(r"""
(async()=>{
 await finish();const good=timeData,snapshot=structuredClone(route),memoSize=systemViews.size,saves=saved.length;
 const pending=loadSystemTime(sessionA+':4'),bad=page(sessionA,4);CHANGE
 requests.at(-1).resolve(bad);await pending;
 assert.equal(timeData,good);assert.deepEqual(route,snapshot);
 assert.equal(systemViews.size,memoSize);assert.equal(saved.length,saves);
 assert.match(navigatorStatus.textContent,/did not retain its pinned session/);
 assert.equal(timeBusy,false);
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE', change))


def test_superseded_response_cannot_overwrite_newer_pinned_time_or_cache():
    time_controller(r"""
(async()=>{
 const old=loadSystemTime(),oldRequest=requests.at(-1);
 route.timeAt='2025-09-01T00:00:00Z';route.timeQ='cognito';
 const current=loadSystemTime(),newRequest=requests.at(-1);
 newRequest.resolve(page(sessionB));await current;const savedRoute=structuredClone(route),data=timeData;
 oldRequest.resolve({...page(sessionA),cursor:'invalid',as_of:'2025-04-01T00:00:00Z'});await old;
 assert.deepEqual(route,savedRoute);assert.equal(timeData,data);
 assert.equal(systemViews.size,1);assert.equal(rendered.length,1);
 assert.equal(route.timeCursor,sessionB+':0');assert.equal(route.timeQ,'cognito');
 assert.doesNotMatch(navigatorStatus.textContent,/could not finish/);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_copied_dated_link_restores_the_pin_in_a_fresh_route():
    time_controller(r"""
(async()=>{
 await finish();const link=url(),params=link.searchParams;
 assert.equal(params.get('at'),route.timeAt);assert.equal(params.get('q'),'login');
 assert.equal(params.get('time_cursor'),sessionA+':0');
 // A new tab has no history.state or localStorage. Its dated URL must be
 // enough to reopen exactly the same pinned page despite a newer HEAD.
 route=fresh();systemViews.clear();timeData=null;
 restore({place:params.get('place'),q:params.get('q'),...datedRoute(params)});
 assert.equal(route.timeQ,'login');assert.equal(route.timeCursor,sessionA+':0');
 const pending=loadSystemTime();const request=requests.at(-1);
 assert.equal(request.body.cursor,sessionA+':0');
 request.resolve(request.body.cursor?page(sessionA):page(sessionB));await pending;
 assert.equal(timeData.commit,'old-head');assert.equal(route.timeCursor,sessionA+':0');
 route.timeAt='';assert.equal(url().searchParams.has('time_cursor'),false,
  'A current chart link must not carry historical session state');
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize('cursor', ['not-a-valid-cursor', 'b' * 64 + ':0'])
def test_invalid_or_foreign_link_pin_fails_without_silently_repinning(cursor):
    time_controller(r"""
(async()=>{
 const params=new URLSearchParams({at:route.timeAt,time_cursor:CURSOR,q:'login',place:'system:orchard'});
 route=fresh();restore({place:params.get('place'),q:params.get('q'),...datedRoute(params)});
 const pending=loadSystemTime();assert.equal(requests[0].body.cursor,CURSOR);
 requests[0].reject(Error('Cursor belongs to a different place or UTC cutoff'));await pending;
 assert.equal(requests.length,1,'Failure must not silently issue an unpinned request');
 assert.equal(route.timeCursor,CURSOR);assert.equal(timeData,null);
 assert.equal(systemViews.size,0);assert.match(navigatorStatus.textContent,/different place or UTC cutoff/);
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CURSOR', repr(cursor)))


def test_explicit_larger_retry_keeps_viewpoint_and_back_reopens_original_pin():
    time_controller(r"""
(async()=>{
 await finish({...page(),retry_larger_available:true});
 route.selected='planet:pears';route.pan={x:46,y:-19};route.zoom=2;
 const original=structuredClone(route),oldData=timeData;
 const retry=retrySystemTime(),request=requests.at(-1);
 assert.equal(request.body.cursor,sessionA+':0');assert.equal(request.body.retry_larger,true);
 assert.equal(request.body.at,original.timeAt);assert.equal(request.body.within,original.place);
 assert.equal(request.body.q,'login');assert.equal(timeBusy,true);
 const count=requests.length;await retrySystemTime();assert.equal(requests.length,count,'Double activation cannot fork twice');
 request.resolve({...page(sessionB),derived_from_session_id:sessionA});await retry;
 assert.equal(route.timeCursor,sessionB+':0');assert.equal(route.step,original.step+1);
 for(const field of ['timeAt','timeQ','selected','pan','zoom','place'])assert.deepEqual(route[field],original[field]);
 assert.deepEqual(saved.at(-2),original,'Earlier viewpoint must be saved before the new pin');
 const recovered=structuredClone(route);
 restore(original);timeData=null;await loadSystemTime();
 assert.equal(timeData,oldData);assert.equal(requests.length,count,'Back uses the original immutable page');
 restore(recovered);timeData=null;systemViews.clear();
 const reload=loadSystemTime();assert.equal(requests.at(-1).body.cursor,sessionB+':0');
 assert.equal(requests.at(-1).body.retry_larger,undefined,'Reload must replay, not derive yet another pin');
 requests.at(-1).resolve({...page(sessionB),derived_from_session_id:sessionA});await reload;
 assert.equal(route.timeCursor,sessionB+':0');assert.equal(timeBusy,false);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize('invalid', ['same_session','wrong_origin','wrong_scope','wrong_date','invalid_cursor'])
def test_larger_retry_rejects_a_different_history_without_losing_the_old_view(invalid):
    change={
        'same_session': "bad.session_id=sessionA;bad.cursor=sessionA+':0';",
        'wrong_origin': "bad.derived_from_session_id='c'.repeat(64);",
        'wrong_scope': "bad.selected_place.id='system:other';",
        'wrong_date': "bad.as_of='2026-01-01T00:00:00Z';",
        'invalid_cursor': "bad.cursor='bad';",
    }[invalid]
    time_controller(r"""
(async()=>{
 await finish({...page(),retry_larger_available:true});
 const original=structuredClone(route),oldData=timeData,count=saved.length;
 const pending=retrySystemTime(),bad={...page(sessionB),derived_from_session_id:sessionA};CHANGE
 requests.at(-1).resolve(bad);await pending;
 assert.equal(timeData,oldData);assert.deepEqual(route,original);assert.equal(systemViews.size,1);
 assert.equal(saved.length,count);assert.equal(timeBusy,false);
 assert.match(navigatorStatus.textContent,/did not retain the original/);
 assert.equal(rendered.at(-1),oldData,'Failure re-renders the original results and retry control');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace('CHANGE',change))


def test_failed_or_superseded_retry_preserves_historical_state():
    time_controller(r"""
(async()=>{
 await finish({...page(),retry_larger_available:true});const original=structuredClone(route),oldData=timeData;
 const failed=retrySystemTime();requests.at(-1).reject(Error('Budget still exceeded'));await failed;
 assert.deepEqual(route,original);assert.equal(timeData,oldData);assert.equal(timeBusy,false);
 assert.match(navigatorStatus.textContent,/Budget still exceeded/);
 const retry=retrySystemTime(),request=requests.at(-1);
 route.timeAt='2025-09-01T00:00:00Z';route.timeCursor='';
 const current=loadSystemTime();requests.at(-1).resolve(page(sessionB));await current;
 const newer=structuredClone(route),newData=timeData;
 request.resolve({...page(sessionB),as_of:original.timeAt,derived_from_session_id:sessionA});await retry;
 assert.deepEqual(route,newer);assert.equal(timeData,newData);
 assert.equal(systemViews.size,2,'Superseded recovery cannot add its stale page');
})().catch(error=>{console.error(error);process.exitCode=1});
""")
