#!/usr/bin/env python3
"""Isolated, read-only discovery experiment. Writes only under this lab."""
import argparse, collections, hashlib, importlib.util, json, math, os, re, resource
import subprocess, time
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / 'private'
VERSION = 'lab01-v1'
STOP = set('the and for that this with from are was were have has its into can all not you your our using use used project application app repository code file files source install run test tests development documentation readme npm python javascript typescript node version http https www com org github'.split())

def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=8)
        return p.stdout.strip() if p.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''

def words(text):
    return [w for w in re.findall(r'[a-z][a-z0-9]{2,}', text.lower()) if w not in STOP]

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def remote_identity(value):
    # Never retain embedded username/password/query from a remote URL.
    if '://' in value:
        parsed = urlsplit(value); host, path = parsed.hostname or '', parsed.path
    elif re.match(r'[^/]+@[^:]+:', value):
        host, path = value.split('@', 1)[1].split(':', 1)
    else:
        return ''  # Local mirrors do not establish a global identity.
    return (host.lower() + '/' + path.strip('/').removesuffix('.git')).lower()

def system_candidate(path):
    parts = Path(path).parts
    if 'clients' in parts:
        i = parts.index('clients')
        if i + 2 < len(parts):
            return parts[i+1]  # Evidence is folder ownership, not employment status.
    return None

def identity(record):
    return record.get('remote') or record.get('common') or record['path']

def typed_pair(a, b):
    if identity(a) == identity(b):
        return 'same_repository'
    if a.get('system') and a['system'] == b.get('system'):
        return 'same_system_candidate'
    return 'unresolved'

def collect():
    started = time.perf_counter(); PRIVATE.mkdir(exist_ok=True, mode=0o700)
    nodes = []; offset = 0; freshness = None
    while True:
        p = subprocess.run(['navcom','atlas','list','projects','--limit','200','--offset',str(offset),'--json'], capture_output=True, text=True, check=True)
        d = json.loads(p.stdout); nodes.extend(d['nodes']); freshness = d['freshness']
        if not d['more']: break
        offset += 200
    cached_path = PRIVATE/'metadata.json'
    cached = json.loads(cached_path.read_text()) if cached_path.exists() else {}
    records = []; changed = 0; reused = 0
    for n in nodes:
        path = Path(n['label']).expanduser()
        if not path.is_absolute(): continue
        root = command(['git','-C',str(path),'rev-parse','--show-toplevel']) if path.is_dir() else ''
        base = Path(root) if root else path
        common = command(['git','-C',str(base),'rev-parse','--path-format=absolute','--git-common-dir']) if root else ''
        remote = remote_identity(command(['git','-C',str(base),'config','--get','remote.origin.url'])) if root else ''
        files = []
        if base.is_dir():
            files = sorted({*base.glob('[Rr][Ee][Aa][Dd][Mm][Ee]*'), *base.glob('package.json'), *base.glob('pyproject.toml')})
            docs = base/'docs'
            if docs.is_dir(): files += sorted(docs.glob('*.md'))[:8]
        files = [f for f in files if f.is_file() and not f.is_symlink() and f.stat().st_size <= 250_000][:12]
        sig = [(str(f),f.stat().st_mtime_ns,f.stat().st_size) for f in files]
        stamp = hashlib.sha256(json.dumps([VERSION,sig,root,common,remote]).encode()).hexdigest()
        old = cached.get(str(base),{})
        if old.get('signature') == stamp:
            metadata = old; reused += 1
        else:
            text = []; headings = []; deps = set(); tech = set()
            for f in files:
                body = f.read_text(errors='replace')[:24_000]
                if f.name == 'package.json':
                    try:
                        package = json.loads(body); deps.update(package.get('dependencies',{})); deps.update(package.get('devDependencies',{}))
                        text.append(str(package.get('name',''))+' '+str(package.get('description',''))); tech.add('javascript')
                        if 'typescript' in deps: tech.add('typescript')
                    except (ValueError,TypeError): pass
                elif f.name == 'pyproject.toml':
                    tech.add('python')
                    deps.update(re.findall(r'"([a-zA-Z][a-zA-Z0-9_-]+)(?:[<>=!~\[])', body))
                else:
                    text.append(body)
                    for line_no,line in enumerate(body.splitlines(),1):
                        if re.match(r'^#{1,4} ',line):
                            headings.append({'text':line.lstrip('# ').strip(),'file':str(f),'line':line_no})
            metadata = {'signature':stamp,'text':'\n'.join(text),'headings':headings,'deps':sorted(deps),'tech':sorted(tech),'files':[str(f) for f in files]}
            cached[str(base)] = metadata; changed += 1
        relative = str(path.relative_to(base)) if root else ''
        lab = bool(re.search(r'(^|/)(labs?|experiments?)(/|$)', relative, re.I) or re.match(r'exp\d+[-_]',base.name,re.I))
        records.append(dict(path=str(path),root=str(base),common=common,remote=remote,system=system_candidate(str(path)),experiment_candidate=lab,exists=path.is_dir(),count=n['count'],**metadata))
    cached_path.write_text(json.dumps(cached))
    result = dict(records=records,version=VERSION,freshness=freshness,collection_seconds=round(time.perf_counter()-started,3),metadata_extracted=changed,metadata_reused=reused)
    (PRIVATE/'snapshot.json').write_text(json.dumps(result))
    return result

def vectors(records):
    counts = [collections.Counter(words(Path(r['root']).name+' '+r['text'])) for r in records]
    df = collections.Counter(w for c in counts for w in c)
    idf = {w:math.log((len(records)+1)/(n+1))+1 for w,n in df.items()}
    def vector(c):
        v = {w:(1+math.log(n))*idf.get(w,0) for w,n in c.items()}
        norm = math.sqrt(sum(x*x for x in v.values())) or 1
        return {w:x/norm for w,x in v.items()}
    return [vector(c) for c in counts], lambda text:vector(collections.Counter(words(text)))

def dot(a,b): return sum(v*b.get(k,0) for k,v in a.items())

def reference_edges(docs):
    """Explicit known-root mentions. Direction is references, never ownership.

    Prefix aliases are accepted only when unique, at least five characters,
    and containing a digit (e.g. a numbered lab). No named project rules.
    """
    aliases=collections.defaultdict(set)
    for r in docs:
        name=Path(r['root']).name.lower()
        if len(name)>=5: aliases[name].add(r['root'])
        prefix=re.split('[-_]',name)[0]
        if len(prefix)>=5 and any(c.isdigit() for c in prefix): aliases[prefix].add(r['root'])
    patterns=[(re.compile(r'(?<![a-z0-9])'+re.escape(a)+r'(?![a-z0-9])',re.I),next(iter(roots)),a) for a,roots in aliases.items() if len(roots)==1]
    edges=[]
    for r in docs:
        seen=set()
        for pattern,target,alias in patterns:
            if target==r['root'] or target in seen:continue
            m=pattern.search(r['text'])
            if m:
                edges.append(dict(source=r['root'],target=target,alias=alias,evidence=r['text'][max(0,m.start()-100):m.end()+180].replace('\n',' '),relation='references_only'))
                seen.add(target)
    return edges

def browse(snapshot, query=None, system=None):
    docs=list({r['root']:r for r in reversed(snapshot['records'])}.values())
    if system: docs=[r for r in docs if r['system']==system]
    if not query:
        if system:
            return dict(system=system,status='folder-derived candidate',destinations=[dict(path=r['root'],status='repository candidate, product boundary unverified',experiment=r['experiment_candidate'],districts=r['headings'][:20]) for r in docs])
        groups=collections.Counter(r['system'] or 'UNRESOLVED' for r in docs)
        return dict(systems=[dict(name=k,destinations=v,status='folder-derived candidate' if k!='UNRESOLVED' else 'no ownership inferred') for k,v in groups.items()])
    vs,qv=vectors(docs)
    ranked=sorted(((dot(qv(query),v),r['root']) for r,v in zip(docs,vs)),reverse=True)
    direct=[dict(path=p,score=round(s,4)) for s,p in ranked[:8] if s>0]
    seeds={d['path'] for d in direct}
    signature=hashlib.sha256(json.dumps([(r['root'],r['signature']) for r in docs]).encode()+Path(__file__).read_bytes()).hexdigest()
    cache_path=PRIVATE/('references-'+signature+'.json')
    cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if cache.get('signature')==signature:
        links=cache['edges']
    else:
        links=reference_edges(docs)
        cache_path.write_text(json.dumps(dict(signature=signature,edges=links)))
    # Keep a linked-results section rather than quietly changing the query ranking.
    found={}
    for edge in links:
        if edge['source'] in seeds and edge['target'] not in seeds:
            target=edge['target']
        elif edge['target'] in seeds and edge['source'] not in seeds:
            target=edge['source']
        else:continue
        found.setdefault(target,[]).append(edge)
    related=sorted((dict(path=p,evidence=e) for p,e in found.items()),key=lambda d:(-len(d['evidence']),d['path']))[:8]
    return dict(query=query,system=system,direct=direct,linked=related,warning='Links establish references, not parenthood or shared ownership; linked results are an additional budget beyond direct top eight.')

def evaluate(snapshot, starforge):
    started = time.perf_counter()
    graph = load_module('sf_graph',starforge/'repo_graph.py')
    concept = load_module('sf_concept',starforge/'concept_search.py')
    records = snapshot['records']
    # One retrieval destination per local repository root, not per cwd.
    roots = {r['root']:r for r in reversed(records)}; docs = list(roots.values())
    deps = {r['root']:set(r['deps']) for r in docs}
    tech = {r['root']:set(r['tech']) for r in docs}
    edges = graph.compute_repo_similarity(deps,{},tech)
    clusters = graph.find_clusters(edges)
    cluster_ids = {p:i for i,cluster in enumerate(clusters) for p in cluster}
    vs, query_vector = vectors(docs)
    gems = [{'name':r['root'],'description':' '.join(words(r['text'])),'tags':[],'source_repo':''} for r in docs]
    by_name = {Path(r['path']).name:r for r in records}
    # Labels are evaluation-only and are never passed into extraction or ranking.
    pair_labels = [
        ('syrab2bdev','syrenity-ios','same_system'),
        ('syrab2bdev','mlmodel','same_system'),
        ('awaliv2','awalilessons2','same_system'),
        ('syrab2bdev','awaliv2','different_system'),
        ('syrenity-ios','awalilessons2','different_system'),
        ('mlmodel','awaliv2','different_system'),
        ('syrab2bdev','syrenity-ios','different_product'),
        ('navcom','starforge','different_product'),
        ('exp29-llm-cbt-aug2026','exp30-cbt-mlxmodel-sep2026','different_product'),
        ('exp30-cbt-mlxmodel-sep2026','exp32-hybrid-jev-cbt','different_product'),
    ]
    checks = []
    for an,bn,expected in pair_labels:
        a,b = by_name.get(an),by_name.get(bn)
        if not a or not b:
            checks.append(dict(a=an,b=bn,expected=expected,available=False));continue
        proposed = typed_pair(a,b)
        samecluster = a['root'] in cluster_ids and b['root'] in cluster_ids and cluster_ids[a['root']]==cluster_ids[b['root']]
        # Compare positively supported membership; abstention is not a correct positive.
        if expected=='same_system': typed_ok = proposed=='same_system_candidate'; sf_ok=samecluster
        elif expected=='different_system': typed_ok=bool(a['system'] and b['system'] and a['system']!=b['system']); sf_ok=not samecluster
        else: typed_ok=identity(a)!=identity(b); sf_ok=not samecluster
        checks.append(dict(a=an,b=bn,expected=expected,available=True,typed=proposed,typed_ok=typed_ok,starforge_same_cluster=samecluster,starforge_ok=sf_ok))
    query = 'chatbot listener protocol mental health'
    ranking = sorted(((dot(query_vector(query),v),r['root']) for r,v in zip(docs,vs)), reverse=True)
    bm25 = concept._bm25_score_gems(words(query),gems,top=8)
    wanted = ['exp29-llm-cbt-aug2026','exp30-cbt-mlxmodel-sep2026','exp32-hybrid-jev-cbt','semanticobservatory']
    retrieval = {'query':query,'expected':wanted,'tfidf':[dict(root=p,score=round(s,4)) for s,p in ranking[:8]],'starforge_bm25':[dict(root=g['name'],score=round(s,4)) for g,s in bm25]}
    for method in ['tfidf','starforge_bm25']:
        names = {Path(x['root']).name for x in retrieval[method]}
        retrieval[method+'_found'] = [w for w in wanted if w in names]
        retrieval[method+'_missed'] = [w for w in wanted if w not in names]
    # Candidate destinations, not asserted product truth.
    systems = collections.defaultdict(list)
    for r in docs:
        if r['system']: systems[r['system']].append(r['root'])
    districts = []
    for r in docs:
        if r['system']=='syra':
            for h in r['headings']:
                if set(words(h['text'])) & {'authentication','authorization','cognito','cerbos','rbac','security','access'}:
                    districts.append(dict(root=r['root'],**h,status='heading candidate, not verified capability'))
    related=[]
    for i,a in enumerate(docs):
        for j in range(i+1,len(docs)):
            s=dot(vs[i],vs[j])
            if s>=.12: related.append(dict(a=a['root'],b=docs[j]['root'],score=round(s,4),relation='related_text_only'))
    controlled = controlled_checks(graph)
    output = dict(version=VERSION,inventory=dict(cwds=len(records),local_directories=sum(r['exists'] for r in records),repository_roots=len(docs),with_text=sum(bool(r['text']) for r in docs),system_candidates=len(systems),unassigned_roots=sum(not r['system'] for r in docs),experiment_candidates=sum(r['experiment_candidate'] for r in records)),
        source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [starforge/'repo_graph.py',starforge/'concept_search.py']},
        systems=dict(systems),pair_checks=checks,retrieval=retrieval,district_candidates=districts,
        starforge_graph=dict(edges=len(edges),clusters=clusters),related_text_edges=related,controlled=controlled,
        timings=dict(collection_seconds=snapshot['collection_seconds'],evaluation_seconds=round(time.perf_counter()-started,3),peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024/1024,2)),
        metadata_extracted=snapshot['metadata_extracted'],metadata_reused=snapshot['metadata_reused'],freshness=snapshot['freshness'])
    (PRIVATE/'results.json').write_text(json.dumps(output,indent=2))
    return output

def controlled_checks(graph):
    def rec(path,remote='',system=None,text=''):
        return dict(path=path,remote=remote,common='',system=system,text=text)
    a=rec('/clients/orbit/alpha','host/orbit/a','orbit')
    moved=rec('/Volumes/base/alpha','host/orbit/a')
    b=rec('/clients/comet/beta','host/comet/b','comet')
    checks=[
        ('move preserves repository identity',typed_pair(a,moved)=='same_repository'),
        ('same technology does not establish ownership',typed_pair(a,b)=='unresolved'),
        ('comparative product mention does not establish ownership',typed_pair(a,rec('/tmp/other',text='Based on alpha, comparisons with orbit'))=='unresolved'),
        ('missing metadata abstains',typed_pair(rec('/tmp/one'),rec('/tmp/two'))=='unresolved'),
    ]
    # Deliberate expected failure: repo identity is insufficient for two products in a monorepo.
    c=rec('/clients/orbit/alpha/product-a','host/orbit/a','orbit')
    d=rec('/clients/orbit/alpha/product-b','host/orbit/a','orbit')
    checks.append(('monorepo yields separate product identity',identity(c)!=identity(d)))
    e=graph.compute_repo_similarity({'a':{'react','vite'},'b':{'react','vite'}},{},{'a':{'javascript','typescript'},'b':{'javascript','typescript'}})
    checks.append(('Starforge identical-stack baseline merges unrelated fixtures',bool(graph.find_clusters(e))))
    return [dict(check=n,passed=v) for n,v in checks]

def report(d):
    lines=['# Lab 01 measured results','',f"Inventory: {json.dumps(d['inventory'])}",'',
           f"Timings (this process): {json.dumps(d['timings'])}",
           f"Metadata extracted/reused: {d['metadata_extracted']}/{d['metadata_reused']}",'',
           '## Selected real-data pair checks','',
           '| A | B | Expected | Typed evidence | Starforge clusters used as ownership |',
           '| --- | --- | --- | --- | --- |']
    for c in d['pair_checks']:
        lines.append(f"| {c['a']} | {c['b']} | {c['expected']} | {'PASS' if c.get('typed_ok') else 'MISS'} | {'PASS' if c.get('starforge_ok') else 'MISS'} |")
    lines+=['','These are selected owner-context checks, not population accuracy. Separate repository identities do not prove separate products. A singleton in a similarity graph is not evidence of different ownership.','', '## Related-research retrieval','',f"Query: `{d['retrieval']['query']}`. Top eight, all available roots as distractors."]
    for method in ['tfidf','starforge_bm25']:
        lines += ['',f"### {method}",f"Found: {', '.join(d['retrieval'][method+'_found']) or 'none'}",f"Missed: {', '.join(d['retrieval'][method+'_missed']) or 'none'}"]
        lines += [f"- {Path(x['root']).name}: {x['score']}" for x in d['retrieval'][method]]
    lines+=['','## Controlled checks','']+[f"- {'PASS' if c['passed'] else 'FAIL'}: {c['check']}" for c in d['controlled']]
    lines+=['','## District candidates within Syra','']+[f"- {Path(h['root']).name}: {h['text']} ({Path(h['file']).name}:{h['line']})" for h in d['district_candidates']]
    lines+=['','## Limits','',
        'Client systems are folder-derived suggestions, not verified employment or ownership. Repo roots are candidate destinations, not solved product boundaries. Experiments are name/folder candidates, not proven moon ownership. Text-related edges never establish containment.',
        'Bounded input: current NavCom cwd inventory; at most 12 README/manifest/docs files per root and 24,000 characters per file, at most eight top-level docs. No recursive code scan, transcripts, curated research profiles, model calls, raw session reads, downloads or external writes. Missing local roots remain visible.',
        'The inventory includes B2B, syrenity-mobile and CarePlus as separate repository candidates under Syra. Product boundaries are still not proven: CarePlus exposes an upstream OpenEMR README and mobile a scaffold README. This lab cannot reliably identify multiple products inside one repository. There is no historical reconstruction or star/base/ship boarding.',
        'Private machine-derived snapshots and detailed relationships are under ignored private/. No production behavior has changed.']
    (HERE/'RESULTS.md').write_text('\n'.join(lines)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reuse-snapshot',action='store_true');p.add_argument('--starforge-source',type=Path,default=Path.home()/'dev/starforge/src/starforge')
    p.add_argument('--query',help='Search the saved snapshot; no rescan.');p.add_argument('--system',help='Inspect/search within a candidate system.');p.add_argument('--list-systems',action='store_true');args=p.parse_args()
    if args.query or args.system or args.list_systems:
        snapshot=json.loads((PRIVATE/'snapshot.json').read_text())
        print(json.dumps(browse(snapshot,args.query,args.system),indent=2));return
    snapshot=json.loads((PRIVATE/'snapshot.json').read_text()) if args.reuse_snapshot else collect()
    d=evaluate(snapshot,args.starforge_source);report(d)
    print(json.dumps({k:d[k] for k in ['inventory','timings','metadata_extracted','metadata_reused']},indent=2))
    print('Results:',HERE/'RESULTS.md')

if __name__=='__main__': main()
