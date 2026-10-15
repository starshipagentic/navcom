"""Atlas command parsing and human/JSON output. Help never opens the index."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sqlite3
import sys
import textwrap
from navcom_discovery import Discovery, EXPLAIN, GROUPS, refresh

OVERVIEW='''NavCom — find, understand and resume your coding conversations.

Search       navcom <words> [--project TEXT] [--here] [--days N]
Discover     navcom atlas list research
Read         navcom --open REF:TURN     · navcom --recap REF
Resume       navcom --resume REF        · --tab · --with HARNESS
Browse       navcom --menu              · navcom --tui
Maintain     navcom --maintain           · navcom --where

Atlas organizes the archive by topics, research families/versions, exact project
folders, broad folder districts, activity month and recorded Starship mappings.
Parent/child ancestry is separate from all these classifications.

Help layers:
  navcom help search       Search phrases, filters and output
  navcom help read         Open passages and recover context
  navcom help resume       Original conversation or fresh harness
  navcom help atlas        Discovery commands and grouping choices
  navcom help browse       Web Atlas, terminal keys and local intelligence
  navcom help maintenance  Indexing, archives and status
  navcom help all          Complete search option manual and Atlas command reference
  navcom atlas help research
  navcom atlas search --help

Examples:
  navcom voice latency --project media
  navcom atlas list projects
  navcom atlas explore research:exp29
  navcom atlas search listener --within research:exp30 --json

Leading atlas and help are commands. Search those literal words with
navcom --query "atlas help". Existing flags and positional searches still work.
'''
SUBJECTS={
 'browse':"""navcom --menu [--no-browser]    Local browser Library and Conversation Atlas
navcom --tui                    Full-screen terminal interface
Web: choose Topics, Research trails, Projects, Planet districts, Time or Starship
families. Search only this collection covers the entire collection, not one page.
Uncheck it for global search. Cards and map share evidence and open commands.
Copy this view as CLI command reproduces scope, filters and pagination.
Missing titles use short indexed passages as display labels, not saved renames.
Terminal Recents: / searches; h toggles children; r resumes; t opens a new tab;
n chooses a fresh harness. Original resumes resolve to the launchable parent.
Startup shows progress; recent dashboard work is cached. Busy indexing leaves
browsing available. Escape returns to the previous screen.
Optional title suggestions use an already-running local model (including the
selected CapCom route when available). No automatic model start or download.
Atlas search, classifications and display labels require no LLM.
""",

 'search':'navcom <words> [--project TEXT] [--here] [--provider NAME] [--since DATE] [--until DATE]\nUse --user or --role to select turns; --json for structured output; -n for limits.\nExamples:\n  navcom voice latency --project media\n  navcom deploy --days 7 --user\n  navcom --query "atlas help"\n',
 'read':'navcom --open REF[:TURN] [--window-turns N]\nnavcom --recap REF\nOpen exact passages or recover a bounded handoff. Atlas prints these commands.\nExample: navcom --open <ref>:42\n',
 'resume':'navcom --resume REF [--tab] [--with HARNESS] [--print]\nOriginal resumes resolve children to their launchable parent. --with starts a\nfresh harness with handoff context. --print previews without launching.\nExample: navcom --resume <ref> --print\n',
 'maintenance':'navcom --where\nnavcom --maintain\nnavcom atlas refresh\nUpkeep indexes/archives conversations and refreshes discovery evidence. Atlas\nrefresh only refreshes metadata from the existing index; it never scans raw logs.\nRead-only discovery remains usable while another process indexes.\n'}


def parser():
    p=argparse.ArgumentParser(prog='navcom atlas',description='Discover collections, then follow evidence to a conversation. No web server or model required.',epilog='Start: navcom atlas list research\nLearn: navcom atlas help research\nLiteral search: navcom --query "atlas"',formatter_class=argparse.RawDescriptionHelpFormatter)
    subs=p.add_subparsers(dest='command')
    descriptions={'list':'List collections by grouping.','explore':'Show collection branches or conversations.','search':'Search globally or within a collection.','show':'Show conversation context, ancestry and safe launch preview.','tree':'Show actual parent/child hierarchy.','refresh':'Incrementally refresh evidence from indexed turns only.','help':'Explain a grouping or command.'}
    for name,description in descriptions.items():
        s=subs.add_parser(name,help=description,description=description,formatter_class=argparse.RawDescriptionHelpFormatter)
        if name=='help':s.add_argument('subject',nargs='?');continue
        if name=='list':s.add_argument('grouping',choices=GROUPS)
        if name=='explore':s.add_argument('collection',help='Stable collection ID printed by list/explore.')
        if name=='search':s.add_argument('words',nargs='+',help='Natural words; quote phrases when convenient.')
        if name in ('show','tree'):s.add_argument('ref',help='Conversation ref printed in results; ambiguous refs require more characters.')
        if name not in ('list','refresh'):s.add_argument('--group-by',dest='grouping',choices=GROUPS,help='Grouping context; defaults to the selected collection, otherwise topics.')
        if name=='show':
            s.add_argument('--start',type=int,default=1,help='Evidence turn to preview (default 1).')
            s.add_argument('--within',help='Collection context for this conversation.')
            s.add_argument('--query',help='Search phrase retained as context; --start selects the evidence turn.')
        if name not in ('refresh','show','tree'):
            if name!='explore':s.add_argument('--within',metavar='COLLECTION',help='Limit to this entire collection, across all pages.')
            if name!='search':s.add_argument('--query',metavar='WORDS',help='Filter by indexed conversation evidence.')
            s.add_argument('--provider',help='Provider name or comma-separated names.')
            s.add_argument('--since',help='Last active on/after YYYY-MM-DD or relative 7d, 12h.')
            s.add_argument('--until',help='Last active on/before YYYY-MM-DD or relative time.')
            s.add_argument('--favorites',action='store_true',help='Only saved favorites.')
            s.add_argument('--children',action='store_true',help='Show child tasks separately; default groups matches under their root.')
        if name!='refresh':
            s.add_argument('--limit',type=int,default=12,help='Items per page (1–200; default 12).')
            s.add_argument('--offset',type=int,default=0,help='Skip this many items; default 0.')
        s.add_argument('--json',action='store_true',help='Versioned structured output; diagnostics go to stderr.')
        s.add_argument('--index',type=Path,help='Index path; defaults to NAVCOM_INDEX or the usual Codex index.')
        s.epilog={'list':'Example: navcom atlas list research\nNext: navcom atlas explore <collection>','explore':'Example: navcom atlas explore research:exp29\nNext: navcom atlas search listener --within research:exp29','search':'Example: navcom atlas search listener --within research:exp30 --json\nNext: navcom atlas show <ref>','show':'Example: navcom atlas show <ref>\nNext: use the printed --open or --resume command. No harness is launched here.','tree':'Example: navcom atlas tree <ref> --limit 50\nMissing parents are labeled; shared topics never become tree edges.','refresh':'Example: navcom atlas refresh\nUses a separate atomic metadata cache; no model, raw-log scan or SQLite writer required.'}.get(name)
    return p


def help_text(api,subject=None,atlas=False):
    if subject in (None,'atlas'):return parser().format_help()+'\nGroupings:\n'+ '\n'.join('  '+k+' — '+v for k,v in EXPLAIN.items())
    if subject in EXPLAIN:return subject+'\n\n'+EXPLAIN[subject]+'\n\n'+('navcom atlas tree <ref>' if subject=='ancestry' else 'navcom atlas list '+subject)+'\nUse a printed collection ID with explore or search --within.\n'
    if subject=='all':return api.build_parser().format_help()+'\nATLAS COMMAND REFERENCE\n'+help_text(api)+'\n'+ '\n'.join(parser()._subparsers._group_actions[0].choices[name].format_help() for name in ('list','explore','search','show','tree','refresh'))
    if subject in SUBJECTS and not atlas:return SUBJECTS[subject]
    sub=parser()._subparsers._group_actions[0].choices.get(subject)
    if sub:return sub.format_help()
    if subject in SUBJECTS:return SUBJECTS[subject]
    raise ValueError('Unknown help subject. Use navcom help or navcom atlas help.')


def render(data):
    width=max(40,min(100,shutil.get_terminal_size((88,24)).columns))
    def line(text='',indent=''):
        print(textwrap.fill(str(text),width=width,initial_indent=indent,subsequent_indent=indent,break_long_words=True,break_on_hyphens=False) if text else '')
    scope=data['effective_scope'];line('ATLAS · '+scope['label']);line('Grouping: '+scope['grouping']+' · Query: '+(scope['query'] or '(none)'))
    if scope['filters']:line('Filters: '+json.dumps(scope['filters']))
    line(data['summary']);line()
    for n in data['nodes']:
        indent='  '*min(n.get('depth',0),10)
        line(('↳ ' if n.get('depth') else '')+n['label'],indent)
        line(n.get('collection',n.get('ref','')),indent)
        if n.get('collection'):line(f"{n['main_count']} main conversations · {n['child_count']} child tasks · {n['projects']} projects",indent)
        if n.get('project'):line('Path: '+n['project'],indent)
        for path in n.get('project_names',[]):line('Path: '+path,indent)
        for key in ('question','approach','distinction'):
            if n.get(key):line(n[key],indent)
        for title in n.get('examples',[]):line('Inside: '+title,indent)
        if n.get('excerpt'):line('Evidence: '+n['excerpt'],indent);line(f"  {n.get('role','indexed')} turn {n.get('start',1)} · {n.get('evidence_ref',n.get('ref',''))}",indent)
        if n.get('parent_ref'):line('Parent: '+n['parent_ref'],indent)
        for child in n.get('matching_children',[])[:3]:line('Matching child: '+child['ref']+' · '+child['label'],indent)
        if len(n.get('matching_children',[]))>3:line(str(len(n['matching_children'])-3)+' more matching children; repeat with --children.',indent)
        if n.get('child_refs'):line('Children: '+', '.join(n['child_refs']),indent)
        line('Basis: '+n['reason'],indent)
        for key in ('next_command','open_command'):
            if n.get(key):print(indent+n[key])
        if n.get('resume_plan'):
            print(indent+'navcom --resume '+shlex.quote(n['ref'])+' --print')
            line('Launch target: '+str(n['resume_plan'].get('line') or 'Original unavailable; use the existing fresh-harness workflow.'),indent)
        line()
    line(f"{data['offset']+1 if data['total'] else 0}–{min(data['offset']+len(data['nodes']),data['total'])} of {data['total']} items · {data['matches']} matching conversations · {data['indexed']} indexed")
    if data['more']:
        args=shlex.split(data['cli_command'])
        if '--offset' in args:i=args.index('--offset');args[i+1]=str(data['offset']+data['limit'])
        else:args+=['--offset',str(data['offset']+data['limit'])]
        print('More: '+shlex.join(args))
    line(data['coverage'])


def run(api,argv):
    p=parser()
    if not argv:print(help_text(api));return 0
    args=p.parse_args(argv)
    if args.command=='help':print(help_text(api,args.subject,atlas=True));return 0
    if not args.command:p.print_help();return 0
    path=(args.index or api.default_index_path()).expanduser()
    if not path.is_file():raise ValueError('No index at '+str(path)+'. Run navcom --maintain first.')
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.3)
    try:
        if args.command=='refresh':
            stamp=[0]
            def progress(done,total):
                import time
                if time.monotonic()-stamp[0]>1:print(f'Atlas evidence: {done}/{total} indexed conversations',file=sys.stderr);stamp[0]=time.monotonic()
            result=refresh(conn,progress);print(json.dumps(dict(schema_version=1,**result)) if args.json else f"Atlas refreshed: {result['changed']} changed / {result['files']} indexed conversations.");return 0
        params={k:[str(v)] for k,v in vars(args).items() if v is not None and k in ('provider','since','until','limit','offset','start')}
        params['action']=[args.command]
        for flag in ('favorites','children'):
            if getattr(args,flag,False):params[flag]=['1']
        for k,dest in [('grouping','grouping'),('collection','within'),('within','within'),('ref','ref'),('query','q')]:
            if getattr(args,k,None):params[dest]=[getattr(args,k)]
        if args.command=='search':params['q']=[' '.join(args.words)]
        data=Discovery(api).view(conn,params)
        if args.json:print(json.dumps(data,ensure_ascii=False))
        else:render(data)
        if not data['freshness']['fresh']:print('navcom: '+data['freshness']['message'],file=sys.stderr)
        return 0
    finally:conn.close()
