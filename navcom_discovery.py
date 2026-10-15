"""Shared, read-only Atlas discovery; explicit incremental evidence refresh."""
import collections
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import time

from navcom_atlas import Atlas, COLORS, identity, tokens
import navcom_research as research

GROUPS = {'topics':'topics','research':'research','projects':'project','districts':'district','time':'month','starships':'fleet'}
EXPLAIN = {
 'topics':'Suggested subjects from titles, folders and saved notes. Collections can overlap.',
 'research':'Defined research families and suggested project families. Branches are evidenced mentions, not proof of implementation or succession.',
 'projects':'Exact indexed working directories. Paths are preserved in full; similar names are not merged.',
 'districts':'Broad folder classifications: Development city, Client districts, Hidden infrastructure, Home & creative. These are not verified ancestry or live planets.',
 'time':'Calendar months of last activity, using the local timezone.',
 'starships':'Source-folder mappings from the local Starship snapshot. Unlinked projects remain visible. Snapshot mappings are not live fleet status.',
 'ancestry':'Actual provider-recorded parent/child links. Shared terms and topics are not ancestry.'}
RESEARCH_WORDS=set('research experiment experiments benchmark training model models listener classifier semantic hypothesis evaluation'.split())
APPROACHES={'listener':'Listener','training':'Training','benchmark':'Benchmark','hybrid':'Hybrid','evaluation':'Evaluation'}
VERSION=re.compile(r'\b(?:v|version\s+)(\d{1,3}(?:\.\d{1,2})?)\b',re.I)


def cache_path(conn):
    path=conn.execute('PRAGMA database_list').fetchone()[2]
    return Path(path+'.atlas.json') if path else None


def read_cache(conn):
    path=cache_path(conn)
    try:
        if not path or path.stat().st_size>32_000_000:return {}
        data=json.loads(path.read_text())
        return data if data.get('version')==1 else {}
    except (OSError,ValueError,TypeError):return {}


def refresh(conn, progress=None):
    """Stream changed indexed user/assistant turns; never read raw archives or hold a writer."""
    old=read_cache(conn).get('files',{});files={};changed=0
    states=conn.execute('SELECT file,mtime,size,msg_index FROM file_state').fetchall()
    for i,(key,mtime,size,last) in enumerate(states):
        signature=[mtime,size,last]
        if old.get(key,{}).get('signature')==signature:files[key]=old[key];continue
        item={'signature':signature,'research':False,'evidence':[],'branches':{}}
        rows=conn.execute("SELECT l.msg_index,f.role,f.text FROM turn_loc l JOIN session_fts f ON f.rowid=l.rid WHERE l.file=? AND f.role IN ('user','assistant') ORDER BY l.msg_index",(key,))
        for index,role,text in rows:
            words=tokens(text);terms=sorted(words & RESEARCH_WORDS)
            evidence={'start':index,'role':role,'excerpt':re.sub(r'\s+',' ',text).strip()[:340]}
            if len(terms)>=2:
                item['research']=True
                if len(item['evidence'])<3:item['evidence'].append(dict(evidence,terms=terms))
            branches=['v'+m for m in VERSION.findall(text)]
            branches += [word for word in APPROACHES if word in words]
            for branch in set(branches):
                if branch not in item['branches'] and len(item['branches'])<80:
                    # Center evidence on the actual mention, not the beginning of a long turn.
                    m=re.search(r'\b(?:v|version\s+)'+re.escape(branch[1:])+r'\b',text,re.I) if branch.startswith('v') else re.search(r'\b'+branch+r'\b',text,re.I)
                    excerpt=re.sub(r'\s+',' ',text[max(0,m.start()-70):m.start()+270]).strip() if m else evidence['excerpt']
                    item['branches'][branch]=dict(evidence,excerpt=excerpt)
        files[key]=item;changed+=1
        if progress:progress(i+1,len(states))
    data={'version':1,'updated':time.time(),'files':files}
    path=cache_path(conn)
    if path:
        fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False)
            os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)
    return {'changed':changed,'files':len(files),'updated':data['updated']}


class Discovery:
    def __init__(self,api):
        self.api=api;self.atlas=Atlas(api)

    def registry(self,conn,records):
        cache=read_cache(conn);files=cache.get('files',{});groups={}
        def put(cid,label,kind,keys,**extra):
            groups[cid]=dict(id=cid,label=label,grouping=kind,keys=set(keys),**extra)
        for grouping,field in GROUPS.items():
            if grouping=='research':continue
            buckets=collections.defaultdict(list)
            for k,r in records.items():
                for value in (r[field] if field=='topics' else [r[field] or 'Unlinked projects']):buckets[value].append(k)
            for value,keys in buckets.items():
                put(grouping+':'+identity(value),value,grouping,keys,reason=EXPLAIN[grouping])
        families=collections.defaultdict(list)
        for k,r in records.items():
            if r['project']!='Unknown project':families[research.family(r['project']) or 'suggested-'+identity(r['project'])].append(k)
        for family,keys in families.items():
            profile=research.PROFILES.get(family)
            if not profile and not any(files.get(k,{}).get('research') for k in keys):continue
            cid='research:'+family
            label=profile['label'] if profile else Path(records[keys[0]]['project']).name+' · Suggested research family'
            put(cid,label,'research',keys,family=family,defined=bool(profile),reason='Defined family · indexed project identity' if profile else 'Suggested family · indexed project and research passages')
            if profile:
                for code,title,expression,description in profile['branches']:
                    put(cid+'/'+code,title,'research',keys,family=family,branch=code,expression=expression,description=description,defined=True,reason='Version mention' if code.startswith('v') else 'Evidenced approach mentions')
            else:
                branches=sorted({b for k in keys for b in files.get(k,{}).get('branches',{})})
                for code in branches:
                    members=[k for k in keys if code in files.get(k,{}).get('branches',{})]
                    put(cid+'/'+code,code if code.startswith('v') else APPROACHES.get(code,code),'research',members,family=family,branch=code,defined=False,reason='Version mention' if code.startswith('v') else 'Suggested approach · indexed mentions')
            put(cid+'/all','Overview · All conversations','research',keys,family=family,branch='all',defined=bool(profile),reason='Indexed project identity')
        return groups,cache

    def resolve(self,ref,records):
        matches=[k for k,r in records.items() if ref in (k,r['id'],self.api.session_ref(k)) or self.api.session_ref(k).startswith(ref)]
        if len(matches)!=1:raise ValueError('Conversation reference '+('is ambiguous; use a full ref.' if matches else 'was not found.'))
        return matches[0]

    def ancestry(self,records):
        lookup={(r['provider'],self.api.session_ref(k)):k for k,r in records.items()}
        parents={k:lookup.get((r['provider'],r['parent_id'])) for k,r in records.items()}
        return parents

    def hits(self,conn,records,collection,cache):
        if collection.get('expression'):
            return self.atlas.trail_hits(conn,records,collection['family'],collection['expression'])
        if collection.get('branch') and collection['branch']!='all' and not collection.get('defined'):
            return {k:cache.get('files',{}).get(k,{}).get('branches',{}).get(collection['branch']) for k in collection['keys']}
        return {k:{} for k in collection['keys']}

    def collection_node(self,conn,records,c,keys,cache):
        members=[records[k] for k in keys];profile=research.PROFILES.get(c.get('family'),{})
        examples=sorted(members,key=lambda r:(bool(r['parent_id']),-r['turns'] if c['grouping']=='research' else -r['mtime']))[:3]
        n=dict(id=c['id'],collection=c['id'],label=c['label'],kind='branch' if c.get('branch') else 'research' if c['grouping']=='research' else 'group',
               count=len(keys),projects=len({r['project'] for r in members}),main_count=sum(not r['parent_id'] for r in members),child_count=sum(bool(r['parent_id']) for r in members),
               examples=[r['title'] for r in examples],project_names=list(dict.fromkeys(r['project'] for r in examples)),reason=c['reason'],
               next_command=shlex.join(['navcom','atlas','explore',c['id']]),grouping=c['grouping'])
        if members:n['date']=time.strftime('%Y-%m-%d',time.localtime(max(r['mtime'] for r in members)))
        if profile:n.update(question=profile['question'],approach=c.get('description',profile['approach']),distinction=profile['distinction'],sources=research.source_notes(profile,{r['project'] for r in members}))
        if c.get('branch') and c['branch']!='all':
            hits=self.hits(conn,records,c,cache)
            sample=next((hits[r['key']] for r in sorted(members,key=lambda r:(bool(r['parent_id']),-r['turns'])) if hits.get(r['key'])),None)
            if sample:n.update(sample)
        elif not c.get('defined') and c['grouping']=='research':
            sample=next((cache['files'][r['key']]['evidence'][0] for r in examples if cache.get('files',{}).get(r['key'],{}).get('evidence')),None)
            if sample:n.update(sample)
            n['approach']='Suggested from indexed research passages; not reviewed or merged with other projects.'
        return n

    def view(self,conn,params):
        value=lambda k,d='':params.get(k,[d])[0]
        records=self.atlas.catalog(conn);registry,cache=self.registry(conn,records)
        within=value('within');query=value('q');action=value('action');lens=value('grouping') or next((k for k,v in GROUPS.items() if v==value('lens','topics')),'topics')
        if value('lens') and value('lens') not in GROUPS.values():raise ValueError('Unknown atlas lens')
        if lens not in GROUPS:raise ValueError('Unknown grouping. Choose '+', '.join(GROUPS))
        # Preserve existing journey URLs while using the common collection resolver.
        if not within and value('group'):
            if value('lens')=='research':within='research:'+value('group')+('/'+value('branch') if value('branch') else '')
            else:
                label=value('project') or value('group');kind='projects' if value('project') or value('lens')=='project' else lens
                within=kind+':'+identity(label)
        if '+' in within:
            parts=within.split('+')
            if any(part not in registry for part in parts):raise ValueError('Unknown collection in scope: '+within)
            combined=set(records)
            for part in parts:combined &= registry[part]['keys'] & set(self.hits(conn,records,registry[part],cache))
            registry[within]=dict(registry[parts[-1]],id=within,base_id=parts[-1],keys=combined,label=' / '.join(registry[part]['label'] for part in parts))
        if within and within not in registry:raise ValueError('Unknown collection: '+within+'. Use navcom atlas list '+lens)
        c=registry.get(within)
        if c and not value('grouping') and not value('lens'):lens=c['grouping']
        if not action:action='show' if value('key') else 'explore' if within else 'list'
        if action not in ('list','explore','search','show','tree'):raise ValueError('Unknown Atlas action')
        offset=max(0,int(value('offset','0')));limit=int(value('limit','12'))
        if not 1<=limit<=200:raise ValueError('--limit must be between 1 and 200')
        eligible=set(records)
        if c:eligible &= c['keys'] & set(self.hits(conn,records,c,cache))
        provider=value('provider');since=value('since');until=value('until')
        for k in list(eligible):
            r=records[k]
            if (provider and r['provider'] not in provider.split(',')) or (value('favorites') in ('1','true') and not r['favorite']) or (since and r['mtime']<self.api._parse_when(since)) or (until and r['mtime']>self.api._parse_when(until)):eligible.remove(k)
        # Filter before transcript ranking, so unrelated global hits cannot consume the cap.
        candidates={k:records[k] for k in eligible}
        scores,evidence,terms=self.atlas.search(conn,candidates,research.normalize_query(query)[0]) if query else ({},{},[])
        preferred=research.intent(query) if query else []
        matched=eligible & set(scores) if query else eligible
        normalized,corrected=research.normalize_query(query)
        intents=research.intent(query) if not within and lens in ('topics','research') and (lens=='research' or value('research')!='0') else []
        family_navigation=bool(intents) and action in ('search','list')
        if family_navigation:lens='research';action='list'
        nodes=[];parents=self.ancestry(records);center_label=c['label'] if c else 'Your conversation universe'
        if action in ('show','tree'):
            key=self.resolve(value('key') or value('ref'),records);center_label=records[key]['title']
            if action=='tree':
                root=key;seen=set()
                while parents.get(root) and root not in seen:seen.add(root);root=parents[root]
                children=collections.defaultdict(list)
                for child,parent in parents.items():
                    if parent:children[parent].append(child)
                stack=[(root,0)];seen=set()
                while stack:
                    k,depth=stack.pop()
                    if k in seen:continue
                    seen.add(k);node=self.atlas.public(records[k],'Actual parent/child');node['depth']=depth;nodes.append(node)
                    stack.extend((ch,depth+1) for ch in reversed(sorted(children[k])))
            else:
                node=self.atlas.public(records[key],'Selected conversation')
                start=max(1,int(value('start','1')));rows=self.api.fetch_window_rows(conn,key,[(start,start)])
                hit={'start':start,'role':rows[0][1],'excerpt':self.api._one_line(rows[0][2],340)} if rows else None
                self.atlas.enrich(conn,node,records[key],hit);nodes=[node]
                node['parent_ref']=self.api.session_ref(parents[key]) if parents[key] else None
                node['child_refs']=[self.api.session_ref(k) for k in records if parents[k]==key]
                node['resume_plan']=self.api.resume_plan(conn,key,records[key]['provider'])
            matched={n['key'] for n in nodes}
        elif action=='list' or (action=='explore' and c and not c.get('branch') and c['grouping']=='research'):
            listing=[g for g in registry.values() if (g['id'].startswith(c.get('base_id',within)+'/') if action=='explore' else g['grouping']==lens and not g.get('branch'))]
            for g in listing:
                keys=set(self.hits(conn,records,g,cache)) & (eligible if family_navigation else matched)
                if family_navigation and g.get('family') not in intents:continue
                if keys:
                    contextual=g
                    if c and action=='list' and g['id'] not in within.split('+'):
                        cid=within+'+'+g['id']
                        contextual=dict(g,id=cid,keys=g['keys'] & c['keys'])
                        registry[cid]=contextual
                    elif c and action=='explore' and '+' in within:
                        cid=within.rsplit('+',1)[0]+'+'+g['id']
                        contextual=dict(g,id=cid,keys=g['keys'] & c['keys'])
                        registry[cid]=contextual
                    nodes.append(self.collection_node(conn,records,contextual,keys,cache))
            if action=='explore':nodes.sort(key=lambda n:(n['collection'].split('/')[-1]!='all',-int(re.search(r'v(\d+)',n['label'])[1]) if re.search(r'^v\d+',n['label']) else 0,n['label']))
            else:nodes.sort(key=lambda n:(n['reason'].startswith('Suggested'),-n['count'],n['label']))
            matched=set().union(*(registry[n['collection']]['keys'] & (eligible if family_navigation else matched) for n in nodes)) if nodes else set()
        else:
            families=collections.defaultdict(list)
            expanded=value('children') in ('1','true')
            for key in matched:
                root=key;seen=set()
                if not expanded:
                    while parents.get(root) and root not in seen:seen.add(root);root=parents[root]
                families[root].append(key)
            ordered=sorted(families,key=lambda k:(bool(preferred) and not any(research.family(records[m]['project']) in preferred for m in families[k]),-max((scores.get(m,0) for m in families[k]),default=0),bool(records[k]['parent_id']),-records[k]['turns'] if c and c['grouping']=='research' else -records[k]['mtime'],k))
            for key in ordered:
                matches=families[key];focus=max(matches,key=lambda k:(scores.get(k,0),k==key,records[k]['mtime']))
                r=records[key];node=self.atlas.public(r,'Matching child task' if key not in matched else 'Indexed conversation')
                branch_hits=self.hits(conn,records,c,cache) if c else {}
                hit=branch_hits.get(focus)
                if evidence.get(focus):
                    index=evidence[focus]['start'];rows=self.api.fetch_window_rows(conn,focus,[(index,index)])
                    if rows:hit={'start':index,'role':rows[0][1],'excerpt':self.api._one_line(rows[0][2],340)}
                self.atlas.enrich(conn,node,records[focus],hit,c['label'] if c and c.get('branch') else '')
                node['evidence_ref']=self.api.session_ref(focus);node['evidence_key']=focus
                node['open_key']=focus;node['matching_children']=[dict(ref=self.api.session_ref(m),label=records[m]['title']) for m in matches if m!=key]
                node['child_count']=sum(p==key for p in parents.values());node['parent_ref']=self.api.session_ref(parents[key]) if parents[key] else None
                if r['parent_id'] and not parents[key]:node['reason']+=' · parent not indexed'
                nodes.append(node)
        total=len(nodes);page=nodes[offset:offset+limit]
        for n in page:
            n['color']=COLORS[int(identity(n['label'])[:6],16)%len(COLORS)]
            if n.get('key'):
                n['ref']=self.api.session_ref(n['key']);n['open_command']=shlex.join(['navcom','--open',self.api.session_ref(n.get('open_key',n['key']))+':'+str(n.get('start',1))]);n['next_command']=shlex.join(['navcom','atlas','show',n['ref']])
        fresh=bool(cache) and all(cache.get('files',{}).get(k,{}).get('signature')==[mtime,size,last] for k,mtime,size,last in conn.execute('SELECT file,mtime,size,msg_index FROM file_state'))
        filters={k:value(k) for k in ('provider','since','until','favorites','children') if value(k)}
        effective={'collection':within or None,'label':center_label,'grouping':lens,'query':query,'filters':filters}
        command=['navcom','atlas',action]
        if action=='list':command.append(lens)
        elif action=='explore':command.append(within)
        elif action=='search':command.append(query)
        elif action in ('show','tree'):command.append(value('ref') or value('key'))
        if within and action not in ('explore','tree'):command+=['--within',within]
        if action!='list' and lens!=(c['grouping'] if c else 'topics'):command+=['--group-by',lens]
        if query and action!='search':command+=['--query',query]
        for k,v in (filters.items() if action not in ('show','tree') else []):
            command+=['--'+k] if k in ('favorites','children') else ['--'+k,v]
        if action=='show' and value('start','1')!='1':command+=['--start',value('start')]
        if offset:command+=['--offset',str(offset)]
        if limit!=12:command+=['--limit',str(limit)]
        db=conn.execute('PRAGMA database_list').fetchone()[2]
        if db and Path(db)!=self.api.default_index_path():command+=['--index',db]
        for node in page:
            if node.get('collection'):
                next_args=shlex.split(node['next_command'])
                for flag,arg in filters.items():next_args+=['--'+flag] if flag in ('favorites','children') else ['--'+flag,arg]
                if query and not family_navigation:next_args+=['--query',query]
                node['next_command']=shlex.join(next_args)
            if db and Path(db)!=self.api.default_index_path():
                for field in ('next_command','open_command'):
                    if node.get(field):node[field]+=' --index '+shlex.quote(db)
        related=[]
        if c and c.get('family') in research.PROFILES:
            rel={'exp29':['exp30','exp32'],'exp30':['exp29'],'exp32':['exp29','observatory'],'observatory':['exp32']}
            related=[{'collection':'research:'+f,'label':research.PROFILES[f]['label'],'reason':'Related research line; not conversation ancestry'} for f in rel[c['family']] if 'research:'+f in registry]
        return dict(schema_version=1,effective_scope=effective,cli_command=shlex.join(command),nodes=page,total=total,offset=offset,limit=limit,more=offset+limit<total,
                    center=dict(id='center',label=center_label,kind='group'),scope=len(matched),matches=len(matched),indexed=len(records),edges=[],query=query,terms=terms,lens=GROUPS[lens],
                    research=lens=='research',summary=EXPLAIN[lens],coverage=EXPLAIN[lens]+' Transcript search uses up to 2,000 ranked passages; defined branches up to 1,500. Suggested branches retain up to 80 names per conversation. Version mentions do not prove implementation.',
                    related=related,normalized_query=normalized,corrected=corrected,fleet_snapshot=self.atlas.fleet_date,
                    freshness={'fresh':fresh,'updated':cache.get('updated'),'message':'Discovery evidence current' if fresh else 'Discovery suggestions missing or stale; run navcom atlas refresh. Indexed search remains available.'})
