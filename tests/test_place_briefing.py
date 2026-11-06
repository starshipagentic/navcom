"""Place questions have useful exact-scope context without a running model."""
import hashlib
import json
from pathlib import Path
import sqlite3
import shlex
import subprocess
import sys

import pytest

from navcom_atlas import identity
import navcom_intelligence
import navcom_navigation as navigation
import navcom_place_briefing as briefing
from test_atlas import add
from test_source_reader import publish


def node(place='planet:lantern', kind='planet', **extra):
    result=dict(id=place, kind=kind, label='Lantern', parent_id='galaxy:owner',
        position=dict(x=2,y=3), locations=[], evidence=[], examples=[], source_ids=[],
        source_scopes=[], conversation_collections=[])
    result.update(extra)
    return result


def chart(tmp_path, center):
    path=tmp_path/'space.json'
    galaxy=node('galaxy:owner','galaxy');galaxy['parent_id']=None
    path.write_text(json.dumps(dict(schema_version=1,published=123,entities=[galaxy,center],edges=[],coverage={})))
    return path


def record(api, conn, path, project, title, answer, stamp=1700000000, parent=None):
    key=add(api,conn,path,title,'',project,stamp,parent)
    cursor=conn.execute("INSERT INTO session_fts(file,msg_index,role,text) VALUES (?,?,?,?)",(key,2,'assistant',answer))
    conn.execute('INSERT INTO turn_loc(file,msg_index,rid) VALUES (?,?,?)',(key,2,cursor.lastrowid))
    conn.execute('UPDATE file_state SET msg_index=2 WHERE file=?',(key,));conn.commit()
    return key


@pytest.fixture
def context(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(tmp_path/'no-fleet'))
    conn=navcom.open_index(tmp_path/'index.sqlite')
    project=str(tmp_path/'offline'/'lantern')
    center=node(locations=[dict(path=project,available=False)])
    center['conversation_collections']=['projects:'+identity(navcom.pretty_project(project))]
    keys=[]
    for index,answer in enumerate(['# Lantern purpose\nA synthetic orchard flood-risk study.',
                                   'The plan exposes POST /score with a typed feature manifest.',
                                   'The implementation produced a model card and measured calibration.']):
        key=record(navcom,conn,tmp_path/f'lantern-{index}.jsonl',project,'Read the saved plan.',answer,stamp=1700000000+index)
        keys.append(key);Path(key).unlink()
    foreign=record(navcom,conn,tmp_path/'foreign.jsonl',project+'-foreign','Same Lantern name','FOREIGN_SECRET_PURPOSE')
    yield navcom,conn,center,keys,foreign
    conn.close()


def test_missing_live_root_keeps_three_exact_indexed_outcomes(context,tmp_path):
    api,conn,center,keys,foreign=context
    got=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=tmp_path/'absent')
    texts=' '.join(item['text'] for item in got['evidence'])
    assert all(word in texts for word in ['flood-risk','POST /score','calibration'])
    assert 'FOREIGN_SECRET_PURPOSE' not in texts
    assert {item['conversation_ref']['key'] for item in got['evidence']}==set(keys)
    assert {item['conversation_ref']['turn'] for item in got['evidence']}=={1,2}
    assert got['coverage']['indexed_conversations']==got['coverage']['excerpted_conversations']==3
    assert got['coverage']['source_scopes']==0 and not got['coverage']['source_available']
    assert not got['coverage']['current_location_available'] and not got['coverage']['complete']
    assert got['summary']['basis']=='attributed_excerpts' and 'answer' not in got
    assert not (tmp_path/'offline').exists()


def test_arrival_never_calls_model_and_reads_only_saved_index(context,tmp_path,monkeypatch):
    api,conn,center,_,_=context
    path=chart(tmp_path,center);original=path.read_bytes()
    monkeypatch.setattr(navcom_intelligence,'answer_grounded',lambda *a,**k: pytest.fail('Arrival must not invoke inference'))
    for action in ('show','explore'):
        got=navigation.view(api,conn,space_cache=path,source_cache=tmp_path/'absent',within=center['id'],action=action)
        assert got['briefing']['place']['id']==center['id']
        assert got['briefing']['coverage']['excerpted_conversations']==3
    assert path.read_bytes()==original


@pytest.mark.parametrize('question',['What does it do?','How is this project useful?','Compare the approaches in this place'])
def test_questions_seed_referent_and_native_retrieval_without_phrase_special_cases(context,tmp_path,monkeypatch,question):
    api,conn,center,keys,foreign=context
    path=chart(tmp_path,center);seen=[]
    def answer(question,evidence,**kwargs):
        seen.append((question,evidence,kwargs))
        return dict(available=False,status='unavailable',message='No resident model')
    monkeypatch.setattr(navcom_intelligence,'answer_grounded',answer)
    got=navigation.navigate(api,conn,space_cache=path,source_cache=tmp_path/'absent',within=center['id'],text=question)
    assert got['intent']['retrieval_style']=='question'
    assert got['briefing']['answer']['available'] is False
    assert got['briefing']['coverage']['excerpted_conversations']==3
    assert len(seen)==1 and seen[0][0]==question
    assert seen[0][2]['place_id']==center['id']
    assert not any(foreign==e.get('conversation_ref',{}).get('key') for e in seen[0][1])
    assert got['evidence']['coverage']['source_scopes']==0


def test_literal_search_and_global_question_do_not_invent_a_referent(context,tmp_path,monkeypatch):
    api,conn,center,_,_=context
    path=chart(tmp_path,center)
    monkeypatch.setattr(navcom_intelligence,'answer_grounded',lambda *a,**k: pytest.fail('No selected-place question'))
    literal=navigation.navigate(api,conn,space_cache=path,source_cache=tmp_path/'none',within=center['id'],text='flood-risk')
    assert 'briefing' not in literal
    global_question=navigation.navigate(api,conn,space_cache=path,source_cache=tmp_path/'none',text='What does it do?',local=False)
    assert not global_question['briefing']['evidence']
    assert 'Choose a product' in global_question['briefing']['summary']['text']


def test_nested_source_document_context_cannot_read_parent_or_live_files(tmp_path):
    root=tmp_path/'live';root.mkdir()
    (root/'README.md').write_text('FUTURE LIVE CONTENT')
    cache=tmp_path/'sources'
    artifact,state=publish(cache,root,{'README.md':b'FOREIGN_PARENT',
        'apps/lantern/README.md':b'# Lantern\nA retained orchard risk study.',
        'apps/other/README.md':b'FOREIGN_SIBLING'})
    center=node();center['source_scopes']=[dict(source_id='quartz',paths=['apps/lantern'])]
    center['source_ids']=['quartz']
    result=briefing.briefing(None,None,center=center,catalog_published=123,source_cache=cache)
    texts=' '.join(item['text'] for item in result['evidence'])
    assert 'retained orchard' in texts and not any(x in texts for x in ['FOREIGN','FUTURE'])
    assert result['evidence'][0]['text']=='# Lantern\nA retained orchard risk study.'
    ref=result['evidence'][0]['source_ref']
    assert ref['relative_path']=='apps/lantern/README.md' and ref['snapshot']==artifact.name
    from navcom_source_reader import read_source
    opened=read_source(ref['source_id'],ref['relative_path'],cache_path=cache,snapshot=ref['snapshot'],published=ref['published'])
    assert 'retained orchard' in ''.join(line['text'] for line in opened['lines'])
    assert result['coverage']['retained_documents']==1


def test_context_is_bounded_and_parent_outside_scope_is_not_substituted(context,tmp_path):
    api,conn,center,keys,foreign=context
    project=conn.execute('SELECT project FROM file_meta WHERE file=?',(keys[0],)).fetchone()[0]
    for i in range(8):
        record(api,conn,tmp_path/f'more-{i}.jsonl',project,'Read plan',str(i)+'X'*200000,stamp=1800000000+i,parent=api.session_ref(foreign))
    got=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=tmp_path/'absent')
    assert got['coverage']['indexed_conversations']==11
    assert got['coverage']['selected_conversations']==3
    assert all(len(item['text'])<=briefing.MAX_TEXT for item in got['evidence'])
    assert sum(len(item['text']) for item in got['evidence'])<=briefing.MAX_TOTAL_TEXT
    assert foreign not in {item['conversation_ref']['key'] for item in got['evidence']}


def test_invalid_scope_cannot_supply_parent_source_context(tmp_path):
    center=node();center['source_scopes']=[dict(source_id='quartz',paths=[])]
    result=briefing.briefing(None,None,center=center,catalog_published=1,source_cache=tmp_path/'none')
    assert not result['evidence'] and not result['coverage']['source_available']
    assert any('Missing saved file scope' in text for text in result['coverage']['limitations'])


@pytest.mark.parametrize('paths,partial', [(['.', 'LAB/unharvested'], False),
                                         (['apps/lantern', 'LAB/unharvested'], True)])
def test_partial_harvest_scope_keeps_available_source_context(tmp_path, paths, partial):
    cache=tmp_path/'sources'
    publish(cache,tmp_path/'offline',{'apps/lantern/README.md':b'# Lantern\nRetained login notes.'},
            include=['apps/lantern/README.md'])
    center=node(source_scopes=[dict(source_id='quartz',paths=paths)])
    result=briefing.briefing(None,None,center=center,catalog_published=1,source_cache=cache)
    assert result['coverage']['source_available'] is True
    assert result['coverage']['retained_documents']==1
    assert result['evidence'][0]['source_ref']['relative_path']=='apps/lantern/README.md'
    gaps=result['coverage']['limitations']
    assert not any('source is unavailable' in text for text in gaps)
    assert any('no overlap with the retained harvest' in text for text in gaps)==partial


@pytest.mark.parametrize('path,available', [('src/login.py',True), ('other/login.py',False)])
def test_scoped_native_evidence_proves_availability_when_document_sampling_fails(tmp_path,path,available):
    center=node(source_scopes=[dict(source_id='quartz',paths=['src'])])
    ref=dict(source_id='quartz',relative_path=path,line=7,snapshot='a'*64,published=123)
    retrieval=dict(sources=[dict(source_id='quartz',concept_hits=[],text_hits=[
        dict(relative_path=path,source_ref=ref,match='def login(user):')])],coverage=dict(complete=False))
    got=briefing.briefing(None,None,center=center,catalog_published=1,
                          source_cache=tmp_path/'unavailable',retrieval=retrieval)
    assert got['coverage']['source_available'] is available
    assert any(item['kind']=='source' for item in got['evidence']) is available
    assert any('Retained document context is unavailable' in text for text in got['coverage']['limitations'])
    assert got['coverage']['complete'] is False


def test_valid_receipt_without_retained_scope_still_reports_unavailable(tmp_path):
    cache=tmp_path/'sources'
    publish(cache,tmp_path/'offline',{'apps/other/README.md':b'FOREIGN PURPOSE'},
            include=['apps/other/README.md'])
    center=node(source_scopes=[dict(source_id='quartz',paths=['apps/lantern'])])
    result=briefing.briefing(None,None,center=center,catalog_published=1,source_cache=cache)
    assert result['coverage']['source_available'] is False
    assert not result['evidence']


def test_native_middle_turn_hit_survives_endpoint_context_selection(context,tmp_path):
    api,conn,center,keys,_=context
    key=keys[0]
    for index,role,text in [(3,'user','What next?'),(4,'assistant','Later unrelated wrap-up.')]:
        cursor=conn.execute('INSERT INTO session_fts(file,msg_index,role,text) VALUES (?,?,?,?)',(key,index,role,text))
        conn.execute('INSERT INTO turn_loc(file,msg_index,rid) VALUES (?,?,?)',(key,index,cursor.lastrowid))
    conn.execute('UPDATE file_state SET msg_index=4 WHERE file=?',(key,));conn.commit()
    path=chart(tmp_path,center)
    found=navigation.evidence(api,conn,path,tmp_path/'none',center['id'],'flood-risk')
    got=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=tmp_path/'none',retrieval=found)
    matches=[item for item in got['evidence'] if item.get('conversation_ref',{}).get('key')==key]
    assert {item['conversation_ref']['turn'] for item in matches}=={1,2,4}
    assert any('flood-risk' in item['text'] for item in matches)


def test_authored_description_wins_and_fallback_is_short_clean_attributed(context,tmp_path):
    api,conn,center,_,_=context
    center['description']='Owner purpose: **model orchard risk**.'
    center['clues']=[dict(text=center['description'],basis='owner_declaration')]
    got=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=tmp_path/'none')
    assert got['summary']['text']=='Owner purpose: model orchard risk.'
    assert got['summary']['basis']=='recorded_description'
    center['description']='Unavailable indexed location; current repository identity could not be checked.'
    center['clues']=[]
    got=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=tmp_path/'none')
    assert got['summary']['basis']=='attributed_excerpts' and len(got['summary']['text'])<=280
    assert 'Unavailable indexed' not in got['summary']['text']
    assert got['summary']['evidence_ids'][0] in {item['id'] for item in got['evidence']}


@pytest.mark.parametrize('style,expected_basis', [('question','attributed_excerpts'),
                                                ('literal','recorded_description'),
                                                (None,'recorded_description')])
def test_question_summary_prefers_first_admitted_native_hit_over_project_description(tmp_path,style,expected_basis):
    description='This is a starter project. Follow the setup instructions.'
    center=node(description=description,clues=[dict(text=description,basis='harvested_readme')],
                source_scopes=[dict(source_id='quartz',paths=['apps/lantern'])])
    cache=tmp_path/'sources'
    artifact,state=publish(cache,tmp_path/'offline',{'apps/lantern/README.md':description.encode()})
    def hit(path,text):
        return dict(relative_path=path,description=text,source_ref=dict(source_id='quartz',
            relative_path=path,line=7,snapshot=artifact.name,published=state['published']))
    first=hit('apps/lantern/auth.py','Lantern authentication uses the gateway session proxy.')
    retrieval=dict(query_plan=dict(style=style),coverage=dict(complete=True),sources=[dict(source_id='quartz',
        concept_hits=[hit('apps/other/auth.py','FOREIGN AUTHORITY'),first,
                      hit('apps/lantern/second.py','Second native result.')],text_hits=[])]) if style else None
    got=briefing.briefing(None,None,center=center,catalog_published=123,source_cache=cache,retrieval=retrieval)
    assert got['summary']['basis']==expected_basis
    cited=next(item for item in got['evidence'] if item['id']==got['summary']['evidence_ids'][0])
    if style=='question':
        assert got['summary']['text']==first['description']
        assert cited['source_ref']==first['source_ref']
        assert 'FOREIGN' not in ' '.join(item['text'] for item in got['evidence'])
    else:
        assert got['summary']['text']==description and cited['kind']=='description'


def test_question_summary_prefers_exact_matched_turn_over_description_and_readme(context,tmp_path):
    api,conn,center,keys,foreign=context
    description='Owner purpose: maintain the orchard workspace.'
    center.update(description=description,clues=[dict(text=description,basis='owner_declaration')],
                  source_scopes=[dict(source_id='quartz',paths=['.'])])
    cache=tmp_path/'sources'
    publish(cache,tmp_path/'offline',{'README.md':b'# Lantern\nWorkspace setup instructions.'})
    retrieval=dict(query_plan=dict(style='question'),coverage=dict(complete=True),conversations=[
        dict(open_key=foreign,start=2),dict(open_key=keys[0],start=2)])
    got=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=cache,retrieval=retrieval)
    assert got['summary']['basis']=='attributed_excerpts'
    assert 'flood-risk' in got['summary']['text']
    cited=next(item for item in got['evidence'] if item['id']==got['summary']['evidence_ids'][0])
    assert cited['conversation_ref']['key']==keys[0] and cited['conversation_ref']['turn']==2
    assert got['coverage']['retained_documents']==1
    retrieval['conversations']=[dict(open_key=foreign,start=2)]
    unmatched=briefing.briefing(api,conn,center=center,catalog_published=123,source_cache=cache,retrieval=retrieval)
    assert unmatched['summary']['text']==description
    assert unmatched['summary']['basis']=='recorded_description'


def test_public_cli_arrival_and_question_expose_native_saved_context_without_model(context,tmp_path):
    api,conn,center,keys,_=context
    path=chart(tmp_path,center)
    script=Path(__file__).resolve().parents[1]/'navcom.py'
    index=conn.execute('PRAGMA database_list').fetchone()[2]
    common=['--space-cache',str(path),'--source-cache',str(tmp_path/'none'),'--index',index,'--json']
    arrival=subprocess.run([sys.executable,str(script),'atlas','explore',center['id'],*common],capture_output=True,text=True,timeout=20)
    assert arrival.returncode==0,arrival.stderr
    loaded=json.loads(arrival.stdout)
    assert loaded['briefing']['coverage']['excerpted_conversations']==3
    # Only transport discovery is disabled: this still uses the public parser,
    # native retrieval, context seed and the actual no-model answer adapter.
    code="import navcom,navcom_intelligence;navcom_intelligence.discover=lambda:dict(available=False,message='Fixture has no resident model');raise SystemExit(navcom.main())"
    question=subprocess.run([sys.executable,'-c',code,'atlas','navigate','What does it do?',
        '--within',center['id'],*common],capture_output=True,text=True,timeout=20,cwd=script.parent)
    assert question.returncode==0,question.stderr
    result=json.loads(question.stdout)
    assert result['evidence']['conversations']==[]
    assert result['briefing']['coverage']['excerpted_conversations']==3
    assert not result['briefing']['answer']['available']
    refs=[item for item in result['briefing']['evidence'] if item['kind']=='conversation']
    assert {item['conversation_ref']['key'] for item in refs}==set(keys)
    for item in refs:
        command=shlex.split(item['open_command'])
        assert command[command.index('--index')+1]==index
        ref=item['conversation_ref']
        row=api.fetch_window_rows(conn,ref['key'],[(ref['turn'],ref['turn'])])[0]
        assert row[2].startswith(item['text'])
