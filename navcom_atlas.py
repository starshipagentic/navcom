"""Read-only conversation atlas: catalog facets and explainable concept retrieval.

Inspired by Starship bridge's path districts and Starforge's category + multi-
strategy concept search. No dependency on either checkout or on model inference.
"""
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import navcom_research as research

STOP = set('a an the and or of to in on for from with this that those these it is are was were be been i we you my our your me us please find show bring where when how what about did do does have had has want need would could can should using used use get all some any conversation conversations discussion discussions talked talk working work project projects code just like into across related again up'.split())
STOP.update('fix fixing looking remember discuss discussed said doing made make help stuff thing things'.split())
TOPICS = {
 'Models & learning': 'model models llm training train inference gemma ollama llama qwen benchmark semantic embeddings cbt pytorch mlx listener',
 'Agents & tools': 'agent agents automation cli tui terminal harness codex claude capcom navcom llmcom mcp tool tools workflow',
 'Web & products': 'website web browser frontend react laravel api app mobile ios ui ux design product accessibility',
 'Voice & media': 'voice audio speech video music tts realtime microphone sonic voicecast image animation render podcast',
 'Infrastructure & recovery': 'backup restore recovery archive migration storage database sqlite locked lock server deploy deployment docker aws gpu fleet starship starforge',
 'Research & experiments': 'research experiment experiments exp study evaluation evaluate scoring dataset data analysis hypothesis paper science',
 'Clients & business': 'client clients business syra syrenity awali access cms meeting team sales billing contract',
 'Life & planning': 'family kids child tax taxes cpa mortgage divorce finance travel planning health calendar personal',
}
EXPANSIONS = [
 {'voice','audio','speech','tts','microphone'}, {'backup','backups','restore','recovery','archive'},
 {'model','models','llm','inference'}, {'train','training','finetune','fine-tuning'},
 {'crash','crashes','crashing','error','failure','bug'}, {'database','sqlite','db'},
 {'lock','locked','locking','contention'}, {'website','web','frontend','browser'},
 {'agent','agents','automation','harness'}, {'video','voicecast','render','rendering'},
 {'deploy','deployment','hosting','server'}, {'tax','taxes','cpa'},
 {'search','searching','find','retrieval'}, {'conversation','conversations','session','sessions','history'},
]
COLORS = ['#b2d9ac','#eabf83','#94c9db','#d2b4df','#e89f88','#9ccabf','#c6c68c','#a9b6de']


def tokens(text):
    return {w for w in re.findall(r'[\w]+(?:-[\w]+)*', text.casefold()) if len(w)>1 and w not in STOP}


def identity(text):
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def classify(title, project, note=''):
    words = tokens(title + ' ' + project + ' ' + note)
    ranked = sorted(((len(words & tokens(v)), k) for k,v in TOPICS.items()), reverse=True)
    selected = [(label, sorted(words & tokens(TOPICS[label]))) for count,label in ranked[:2] if count]
    return selected or [('Other discoveries', [])]


def district(project):
    if '/clients/' in project: return 'Client districts'
    if '/dev/' in project: return 'Development city'
    if any(p.startswith('.') for p in project.split('/') if p not in ('.','..','~')): return 'Hidden infrastructure'
    return 'Home & creative'


def fleet_snapshot():
    root = Path(os.environ.get('NAVCOM_STARSHIP_ROOT', str(Path.home()/'dev/starship'))).expanduser()
    path = root/'bridge/data.json'
    try:
        if path.stat().st_size > 5_000_000: return [], ''
        data = json.loads(path.read_text())
        ships = [(s['name'], source) for s in data.get('ships',[]) for source in s.get('sources',[])
                 if isinstance(s.get('name'),str) and isinstance(source,str) and source.startswith('/')]
        return ships, str(data.get('generated',''))
    except (OSError,ValueError,TypeError,KeyError): return [], ''


def _file_generation(path):
    try:
        st=Path(path).stat()
        return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
    except OSError:
        return None


def _month(stamp):
    if not stamp:return 'Undated'
    local=time.localtime(stamp)
    # strftime performs another timezone conversion on macOS. Preserve unusual
    # platform year formatting through the original path outside normal dates.
    if not 1000<=local.tm_year<=9999:return time.strftime('%Y-%m',local)
    return f'{local.tm_year:04d}-{local.tm_mon:02d}'


class Atlas:
    def __init__(self, api):
        self.api=api
        self.lock=threading.Lock()
        self.signature=None
        self.records={}
        self.built=0
        self.fleet_date=''
        self.trail_cache={}

    @staticmethod
    def database_generation(conn):
        db=next((r[2] for r in conn.execute('PRAGMA database_list') if r[1]=='main'),'')
        return (_file_generation(db),_file_generation(db+'-wal')) if db else None

    def catalog(self,conn):
        # A pooled caller captures this before opening its read snapshot. If a
        # writer publishes during a search, the next request must invalidate.
        generation=getattr(self,'_read_generation',self.database_generation(conn))
        annotations=self.api._ui_read(conn,'annotations')
        rows=conn.execute('SELECT s.file,s.mtime,s.msg_index,m.provider,m.project,m.title,s.size FROM file_state s LEFT JOIN file_meta m ON m.file=s.file ORDER BY s.file').fetchall()
        fleet_path=Path(os.environ.get('NAVCOM_STARSHIP_ROOT',str(Path.home()/'dev/starship'))).expanduser()/'bridge/data.json'
        signature=(identity(json.dumps(rows)),identity(json.dumps(annotations,sort_keys=True)),
                   generation,
                   str(fleet_path),_file_generation(fleet_path),os.environ.get('TZ'),time.tzname)
        with self.lock:
            if signature==self.signature and time.monotonic()-self.built<120: return self.records
            ships,self.fleet_date=fleet_snapshot()
            ships.sort(key=lambda p:-len(p[1]))
            records={}
            for key,mtime,turns,provider,project,title,_size in rows:
                provider=provider or self.api.detect_provider_from_path(key)
                project=project or self.api._project_from_key(key,provider) or 'Unknown project'
                parent,nickname=self.api._session_parent(conn,key,provider)
                if not title:
                    row=conn.execute("SELECT substr(f.text,1,220) FROM turn_loc l JOIN session_fts f ON f.rowid=l.rid WHERE l.file=? AND f.role='user' ORDER BY l.msg_index LIMIT 1",(key,)).fetchone()
                    title=row[0] if row else ''
                annotation=annotations.get(key,{})
                title=annotation.get('name') or self.api._one_line(title or '',160) or (nickname if parent else '') or 'Untitled conversation'
                display=self.api.pretty_project(project)
                labels=classify(title,display,annotation.get('note',''))
                raw_project=os.path.expanduser(display)
                fleet=next((name for name,source in ships if raw_project==source or raw_project.startswith(source.rstrip('/')+'/')),None)
                records[key]=dict(id=identity(key),key=key,title=title,project=display,provider=provider,
                                  mtime=mtime or 0,turns=turns or 0,topics=[t for t,_ in labels],
                                  basis={t:words for t,words in labels},district=district(display),
                                  month=_month(mtime),
                                  favorite=bool(annotation.get('favorite')),fleet=fleet,parent_id=parent,
                                  words=tokens(title+' '+display+' '+annotation.get('note','')+' '+(nickname if parent else '')))
            self.records=records;self.signature=signature;self.built=time.monotonic();self.trail_cache={}
            return records

    def trail_hits(self,conn,records,family,expression):
        cache_key=(self.signature,family,expression)
        # Signature contains only immutable scalars/tuples, including annotation hash.
        if cache_key in self.trail_cache:return self.trail_cache[cache_key]
        keys=[k for k,r in records.items() if research.family(r['project'])==family]
        if not keys:return {}
        rows=conn.execute("SELECT file,msg_index,role,snippet(session_fts,0,'','', ' … ',38) FROM session_fts WHERE session_fts MATCH ? AND role IN ('user','assistant') AND file IN (SELECT value FROM json_each(?)) ORDER BY (role='user') DESC,bm25(session_fts) LIMIT 1500",(expression,json.dumps(keys))).fetchall()
        hits={}
        quality={}
        for key,index,role,excerpt in rows:
            text=self.api._one_line(excerpt,340)
            clues=tokens(text) & set('why how protocol listener engine speaker meaning signals decision concern hybrid strength clarity training model context question semantic benchmark'.split())
            score=(3 if role=='user' else 0)+len(clues)*.7+min(len(text),280)/280-text.count('/')*.04
            if key not in hits or score>quality[key]:
                hits[key]=dict(start=index,excerpt=text,role=role);quality[key]=score
        self.trail_cache[cache_key]=hits
        return hits

    def evidence_label(self, text):
        # Extract displayed words, never invent a summary or expose Markdown URLs.
        def link_words(match):
            label,target=match.groups()
            if target.startswith('/') and label == Path(target).name:
                parts=Path(target).parts
                label='/'.join(parts[-3:] if parts[-2]=='sources' else parts[-2:])
            return label
        text=re.sub(r"\[([^]\n]+)\]\(([^)]+)\)", link_words, text or '')
        text=re.sub(r"<[^>]+>", " ", text)
        text=re.sub(r"`|\*\*|__|^#+\s*", "", text)
        text=re.sub(r"^(?:Untitled|Unknown) conversation\s*", "", text, flags=re.I)
        return self.api._one_line(text,88)

    def enrich(self,conn,node,record,hit=None,version=''):
        family=research.family(record['project']);profile=research.PROFILES.get(family,{})
        if not hit:
            row=conn.execute("SELECT f.msg_index,f.role,substr(f.text,1,420) FROM turn_loc l JOIN session_fts f ON f.rowid=l.rid WHERE l.file=? AND f.role IN ('user','assistant') ORDER BY (f.role='user') DESC,l.msg_index LIMIT 1",(record['key'],)).fetchone()
            hit=dict(start=row[0],role=row[1],excerpt=self.api._one_line(row[2],340)) if row else {}
        node.update(hit)
        if node.get('label','').lower() in ('untitled conversation','unknown conversation',''):
            title=self.evidence_label(node.get('excerpt',''))
            node['original_title']=node.get('label','')
            node['label']=title or ('Conversation '+self.api.session_ref(node['key']))
            node['label_basis']='Indexed passage' if title else 'Conversation reference'
        node.update(lab=profile.get('label',''),question=profile.get('question',''),approach=profile.get('approach',''),version=version,
                    distinction=profile.get('distinction',''),family=family)
        return node

    def research_view(self,conn,records,params,query):
        value=lambda k,d='':params.get(k,[d])[0]
        group=value('group');branch=value('branch');offset=max(0,int(value('offset','0')));limit=12
        normalized,corrected=research.normalize_query(query)
        allowed=research.intent(normalized)
        matched=None
        if normalized.strip() and not allowed:
            matched=set(self.search(conn,records,normalized)[0])
        families=collections.defaultdict(list)
        for r in records.values():
            f=research.family(r['project'])
            if f and (matched is None or r['key'] in matched) and (value('favorites')!='1' or r['favorite']):families[f].append(r)
        nodes=[];scope=sum(len(v) for v in families.values());summary='';sources=[]
        if not group:
            for name,p in research.PROFILES.items():
                members=families.get(name,[])
                if not members or (allowed and name not in allowed):continue
                nodes.append(dict(id=name,kind='research',family=name,label=p['label'],count=len(members),projects=len(set(r['project'] for r in members)),
                                  main_count=sum(not r['parent_id'] for r in members),child_count=sum(bool(r['parent_id']) for r in members),question=p['question'],approach=p['approach'],distinction=p['distinction'],reason='Indexed project identity; source-grounded research description',
                                  sources=research.source_notes(p,{r['project'] for r in members}),
                                  date=time.strftime('%Y-%m-%d',time.localtime(max(r['mtime'] for r in members))),
                                  branches=[b[1] for b in p['branches']],related=[]))
            center=dict(id='center',label='Chatbot & semantic research trails',kind='group')
            scope=sum(n['count'] for n in nodes)
            total=len(nodes);nodes=nodes[offset:offset+limit]
            summary='Separate research lines, not one version sequence. EXP29 contains v13–v34; EXP30 has its own V1/V2; EXP32 investigates JEV; Observatory is a benchmark project.'
        else:
            if group not in research.PROFILES:raise ValueError('Unknown research trail')
            p=research.PROFILES[group];members=families.get(group,[]);scope=len(members);keys={r['key'] for r in members}
            sources=research.source_notes(p,{r['project'] for r in members})
            summary=p['question']+' '+p['approach']+' '+p['distinction']
            center=dict(id='center',label=p['label'],kind='group')
            definitions=[('all','Overview · All conversations','',p['distinction'])]+(list(reversed(p['branches'])) if group=='exp29' else p['branches'])
            if not branch:
                for code,label,expression,description in definitions:
                    hits=self.trail_hits(conn,records,group,expression) if expression else {k:{} for k in keys}
                    matches=keys & set(hits)
                    if not matches:continue
                    # Show a parent conversation example before sub-agent task prompts.
                    sample=sorted(matches,key=lambda k:(bool(records[k]['parent_id']),-records[k]['turns']))[0]
                    node=dict(id=code,kind='branch',family=group,branch=code,label=label,count=len(matches),projects=len(set(records[k]['project'] for k in matches)),
                              reason='Matching user/assistant passages in this project family' if expression else 'Indexed project identity',
                              question=p['question'],approach=description,distinction=p['distinction'],version=code if code.startswith('v') else '',
                              excerpt=hits[sample].get('excerpt',''),role=hits[sample].get('role',''),start=hits[sample].get('start'),sources=sources)
                    nodes.append(node)
                version_match=re.search(r'\bv\d+(?:\.\d+)?\b',normalized.lower())
                if version_match:nodes.sort(key=lambda n:(n.get('branch')!=version_match[0],n['id']=='all'))
                total=len(nodes);nodes=nodes[offset:offset+limit]
            else:
                definition=next((b for b in definitions if b[0]==branch),None)
                if not definition:raise ValueError('Unknown research branch')
                code,label,expression,description=definition
                hits=self.trail_hits(conn,records,group,expression) if expression else {k:{} for k in keys}
                matches=sorted(keys & set(hits),key=lambda k:(bool(records[k]['parent_id']),-records[k]['turns'],-records[k]['mtime']))
                total=len(matches);scope=total;center['label']=p['label']+' / '+label
                for key in matches[offset:offset+limit]:
                    node=self.public(records[key],'Project identity + '+label)
                    self.enrich(conn,node,records[key],hits[key] or None,label)
                    node['label']=label+' · '+('Child task' if records[key]['parent_id'] else 'Main conversation')
                    node['original_title']=records[key]['title'];nodes.append(node)
        for n in nodes:n['color']=COLORS[int(identity(n['label'])[:6],16)%len(COLORS)]
        relations={'exp29':[('exp30','Separate listener / chat experiment'),('exp32','Reuses EXP29 engine for JEV investigation')],
                   'exp30':[('exp29','Comparison baseline, not the same version lineage')],
                   'exp32':[('exp29','Original engine lineage'),('observatory','Benchmark project split out from EXP32')],
                   'observatory':[('exp32','Originating research and earlier conversation history')]}
        related=[dict(family=f,label=research.PROFILES[f]['label'],reason=why) for f,why in relations.get(group,[]) if f in families]
        return dict(center=center,nodes=nodes,edges=[],total=total,offset=offset,more=offset+limit<total,indexed=len(records),matches=scope,scope=scope,related=related,
                    query=query,terms=[],lens='research',research=True,summary=summary,sources=sources,normalized_query=normalized,corrected=corrected,
                    coverage='Research identities come from indexed project folders; version branches require matching user/assistant passages. Branch counts use up to 1,500 ranked passages. Mentions are not proof of implementation or deployment.')

    def search(self,conn,records,query):
        words=tokens(query)
        if not words: return {}, {}, []
        expanded=set(words)
        for group in EXPANSIONS:
            if words & group: expanded |= group
        expanded=sorted(expanded)[:40]
        df=collections.Counter(w for r in records.values() for w in r['words'])
        scores={}; reasons={}; focus={}
        for key,r in records.items():
            hits=r['words'] & set(expanded)
            if hits:
                scores[key]=sum(math.log(2+len(records)/(1+df[w]))*(2 if w in words else .65) for w in hits)
                if words <= r['words']: scores[key] += 30
                reasons[key]='Title / project / note: '+', '.join(sorted(hits)[:6])
        # FTS5 ranks indexed transcript hits; all queries are parameterized literals.
        expression=' OR '.join('"'+w.replace('"','""')+'"' for w in expanded)
        if expression:
            direct=' AND '.join('"'+w+'"' for w in sorted(words)[:20])
            direct_rows=conn.execute("SELECT file,msg_index,bm25(session_fts) FROM session_fts WHERE session_fts MATCH ? AND role IN ('user','assistant') AND file IN (SELECT value FROM json_each(?)) ORDER BY (role='user') DESC,bm25(session_fts) LIMIT 500",(direct,json.dumps(list(records)))).fetchall()
            broad_rows=conn.execute("SELECT file,msg_index,bm25(session_fts) FROM session_fts WHERE session_fts MATCH ? AND role IN ('user','assistant') AND file IN (SELECT value FROM json_each(?)) ORDER BY (role='user') DESC,bm25(session_fts) LIMIT 1500",(expression,json.dumps(list(records)))).fetchall()
            for key,index,rank,exact in [(*row,True) for row in direct_rows]+[(*row,False) for row in broad_rows]:
                if key not in records or key in focus: continue
                focus[key]=index
                scores[key]=scores.get(key,0)+min(12,max(1,-rank))+(40 if exact else 0)
                reasons[key]=(reasons.get(key,'')+' · ' if key in reasons else '')+('All search terms in indexed transcript' if exact else 'Indexed transcript match')
        return scores, {k:dict(reason=reasons[k],start=focus.get(k,1)) for k in scores}, expanded

    def view(self,conn,params):
        value=lambda k,d='':params.get(k,[d])[0]
        query=value('q')[:500];lens=value('lens','topics')
        if lens not in ('topics','project','district','month','fleet','research'): raise ValueError('Unknown atlas lens')
        records=self.catalog(conn)
        if not value('key') and (lens=='research' or (lens=='topics' and value('research')!='0' and not value('group') and research.intent(query))):
            return self.research_view(conn,records,params,query)
        if lens=='research':lens='topics'  # selected conversation continues into the common neighborhood
        scores,evidence,terms=self.search(conn,records,query) if query.strip() else ({},{},[])
        chosen=[r for k,r in records.items() if not query.strip() or k in scores]
        if value('favorites')=='1': chosen=[r for r in chosen if r['favorite']]
        total_matches=len(chosen)
        group=value('group');project=value('project')
        def facets(r):return r[lens] if lens=='topics' else [r[lens] or 'Unlinked projects']
        if group:chosen=[r for r in chosen if group in facets(r)]
        if project:chosen=[r for r in chosen if r['project']==project]
        offset=max(0,int(value('offset','0')));limit=12
        selected=value('key')
        nodes=[];edges=[]
        if selected:
            if selected not in records: raise ValueError('Conversation is not in the atlas')
            r=records[selected]
            parent_id,nickname=self.api._session_parent(conn,selected,r['provider'])
            parent=next((k for k in records if self.api.session_ref(k)==parent_id and records[k]['provider']==r['provider']),None) if parent_id else None
            related=[]
            # Actual ancestry is checked only for the selected project's neighbors.
            for key,n in records.items():
                if key==selected: continue
                if value('favorites')=='1' and not n['favorite']: continue
                relation='';weight=0
                if key==parent:relation='Parent conversation';weight=1000
                elif n['provider']==r['provider'] and n['parent_id']==self.api.session_ref(selected):
                    relation='Child conversation';weight=900
                shared=n['words'] & r['words']; common=set(n['topics']) & set(r['topics'])
                if not relation and shared:
                    weight=len(shared)/(math.sqrt(len(n['words'])*len(r['words'])) or 1)
                    relation='Shared terms: '+', '.join(sorted(shared)[:5])
                if not relation and common: weight=.01;relation='Shared topic: '+sorted(common)[0]
                if relation:related.append((weight,n,relation))
            related.sort(key=lambda item:(-item[0],-item[1]['mtime'],item[1]['key']))
            total=len(related)
            for _,n,reason in related[offset:offset+limit]:nodes.append(self.public(n,reason))
            center=self.public(r,'Selected conversation');center['label']=r['title']
        elif group and (project or lens=='project'):
            chosen.sort(key=lambda r:(-scores.get(r['key'],0),-r['mtime'],r['key']))
            total=len(chosen)
            for r in chosen[offset:offset+limit]:
                reason=evidence.get(r['key'],{}).get('reason') or ('Topic terms: '+', '.join(r['basis'].get(group,[])) if lens=='topics' else 'Grouped by '+lens)
                node=self.public(r,reason);node['start']=evidence.get(r['key'],{}).get('start',1)
                self.enrich(conn,node,r)
                if r['key'] in evidence:
                    index=evidence[r['key']]['start'];rows=self.api.fetch_window_rows(conn,r['key'],[(index,index)])
                    if rows:node.update(start=index,role=rows[0][1],excerpt=self.api._one_line(rows[0][2],340))
                nodes.append(node)
            center=dict(id='center',label=project or group,kind='group')
        else:
            buckets=collections.defaultdict(list)
            for r in chosen:
                for label in ([r['project']] if group else facets(r)): buckets[label].append(r)
            ranked=sorted(buckets.items(),key=lambda item:(-sum(scores.get(r['key'],0) for r in item[1]),-len(item[1]),item[0]))
            total=len(ranked)
            for label,members in ranked[offset:offset+limit]:
                nodes.append(dict(id=identity(label),label=label,kind='project' if group else 'group',count=len(members),
                                  projects=len(set(r['project'] for r in members)),reason='Shared project folder' if group or lens=='project' else 'Metadata topic matches' if lens=='topics' else 'Recorded Starship source mapping' if lens=='fleet' else 'Shared '+lens,
                                  main_count=sum(not r['parent_id'] for r in members),child_count=sum(bool(r['parent_id']) for r in members),
                                  project_names=[name for name,_ in collections.Counter(r['project'] for r in members).most_common(3)],
                                  examples=[r['title'] for r in sorted(members,key=lambda r:(bool(r['parent_id']),-r['mtime']))[:3]]))
            center=dict(id='center',label=group or (query if query else 'Your conversation universe'),kind='group')
        for i,n in enumerate(nodes):
            n['color']=COLORS[int(identity(n['label'])[:6],16)%len(COLORS)]
            edges.append(dict(source=center['id'],target=n['id'],kind=n.get('reason','')))
        return dict(center=center,nodes=nodes,edges=edges,total=total,offset=offset,more=offset+limit<total,
                    indexed=len(records),matches=total_matches,scope=len(chosen),query=query,terms=terms,lens=lens,
                    fleet_snapshot=self.fleet_date,coverage='All indexed conversations; topic labels are metadata-based suggestions. Search includes up to 2,000 ranked transcript turns plus all matching titles, folders and notes.')

    @staticmethod
    def public(r,reason):
        return dict(id=r['id'],key=r['key'],label=r['title'],kind='conversation',project=r['project'],
                    provider=r['provider'],topics=r['topics'],mtime=r['mtime'],count=r['turns'],reason=reason,start=1,child=bool(r['parent_id']))
