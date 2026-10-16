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
from navcom_navigation import KINDS as SPACE_KINDS

OVERVIEW='''NavCom — find, understand and resume your coding conversations.

Search       navcom <words> [--project TEXT] [--here] [--days N]
Discover     navcom atlas list systems   · navcom atlas list research
Navigate     navcom atlas navigate "fly to NAME"  · navcom help space
Find inside  navcom atlas navigate "find matrix in EXP32"
Related      navcom atlas related PLACE          · cached versions and references
History      navcom history timeline PLACE  · navcom history system PLACE --at DATE
Read         navcom --open REF:TURN     · navcom sources read SOURCE PATH
Inspect      navcom atlas inspect PLACE         · --refresh for code locations
Interact     navcom atlas ask STAR "question"  · navcom atlas board SHIP
Voice        navcom voice status               · navcom voice transcribe FILE
Resume       navcom --resume REF        · --tab · --with HARNESS
Browse       navcom --menu              · navcom --tui
Sources      navcom sources --help       Harvest, search and read cached code/docs
Maintain     navcom --maintain           · navcom --where

Atlas organizes the archive by topics, research families/versions, exact project
folders, broad folder districts, activity month and recorded Starship mappings.
Parent/child ancestry is separate from all these classifications.

Help layers:
  navcom help space        Galaxy, systems, products, experiments and districts
  navcom help sources      Cached Starforge harvest, both search paths and source reads
  navcom help history      Exact Git revisions and dated system/galaxy source views
  navcom help voice        Existing local Whisper speech tools and short recordings
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

Leading atlas, sources, history and help are commands; voice status/transcribe
select local speech tools. Other positional voice searches remain compatible. Search those literal words with
navcom --query "atlas help". Existing flags and positional searches still work.
'''
SUBJECTS={
 'browse':"""navcom --menu [--no-browser]    Local Galactic Bridge, Library and Conversation Atlas
navcom --tui                    Full-screen terminal interface
Bridge: fly between places, inspect ships/experts, and read exact harvested source
windows. Explore time selects committed source evidence at a UTC cutoff; current
addresses remain anchors. Continue remaining repositories follows the pinned cursor.
Conversation Atlas: choose Topics, Research trails, Projects, Planet districts, Time or Starship
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
 'read':'navcom --open REF[:TURN] [--window-turns N]\nnavcom --recap REF\nnavcom sources read SOURCE PATH [--line N] [--limit N]\nOpen exact conversation passages, recover a bounded handoff, or read a published\nsource snapshot. Source reads never open live working files; returned snapshot\nand published values pin subsequent windows. See navcom sources read --help.\nExample: navcom --open <ref>:42\n',
 'resume':'navcom --resume REF [--tab] [--with HARNESS] [--print]\nOriginal resumes resolve children to their launchable parent. --with starts a\nfresh harness with handoff context. --print previews without launching.\nExample: navcom --resume <ref> --print\n',
 'maintenance':'navcom --where\nnavcom --maintain\nnavcom atlas refresh\nUpkeep indexes/archives conversations and refreshes discovery evidence. Atlas\nrefresh only refreshes metadata from the existing index; it never scans raw logs.\nRead-only discovery remains usable while another process indexes.\n'}


def parser():
    p=argparse.ArgumentParser(prog='navcom atlas',description='Navigate cached places and collections; follow source, conversation and provider evidence. No web server or model required.',epilog='Start: navcom atlas list systems\nLearn: navcom help space\nLiteral search: navcom --query "atlas"',formatter_class=argparse.RawDescriptionHelpFormatter)
    subs=p.add_subparsers(dest='command')
    descriptions={'context':'Read a ship’s carried conversations and handover without resuming a captain.','files':'Browse the retained code and documents at a product, experiment or district.','ask':'Review a question for an exact Hermes expert; explicitly open it in its native terminal.','board':'Find and validate the native captain route for one local ship; explicitly reopen it.','list':'List places or conversation collections by grouping.','explore':'Show a place, collection branches or conversations.','search':'Search globally or within a place or collection.','navigate':'Interpret a destination or question and follow cached place, source and conversation evidence.','related':'Inspect cached native version-family suggestions and literal documented references to other projects.','inspect':'Inspect physical code locations, ship context or expertise; optionally observe an existing star provider process.','show':'Show a place or conversation context, ancestry and safe launch preview.','tree':'Show actual parent/child conversation hierarchy.','refresh':'Refresh indexed evidence, or rebuild current geography and provider metadata with --space.','help':'Explain a grouping or command.'}
    for name,description in descriptions.items():
        s=subs.add_parser(name,help=description,description=description,formatter_class=argparse.RawDescriptionHelpFormatter)
        if name=='help':s.add_argument('subject',nargs='?');continue
        if name=='context':
            s.add_argument('ref',metavar='SHIP',help='Exact ship ID or unique name from the chart.')
            choices=s.add_mutually_exclusive_group()
            choices.add_argument('--query',help='Search only this ship’s carried conversations using the native reader.')
            choices.add_argument('--session',help='Open one exact carried session ID printed by the catalog/search.')
            choices.add_argument('--handover',action='store_true',help='Read this ship’s documented HANDOVER.md in bounded pages.')
            s.add_argument('--turn',type=int,help='Read this exact original native message index; requires --session.')
            s.add_argument('--catalog',default='',help='Carried catalog SHA-256 from a previous result; rejects changed history.')
            s.add_argument('--offset',type=int,default=0,help='Native page offset; HANDOVER uses character offsets.')
            s.add_argument('--limit',type=int,default=10,help='Maximum sessions/messages per page, 1–50 (default 10).')
            s.add_argument('--max-chars',type=int,default=2000,help='Maximum characters per message or handover page, 1–8000.')
            s.add_argument('--space-cache',type=Path,help='Saved geography; defaults beside the index.')
            s.add_argument('--index',type=Path,help='Index location for default cache paths.')
            s.add_argument('--json',action='store_true',help='Native context, pagination and provenance.')
            s.epilog='Examples: navcom atlas context <ship-id>\n          navcom atlas context <ship-id> --query login\n          navcom atlas context <ship-id> --session <returned-id> --turn 12 --catalog <returned-sha256>\n          navcom atlas context <ship-id> --handover\nUses independently installed Starship tools. Copy returned commands to retain the catalog generation across pages and exact-turn reads. Stored archives are separate destinations discovered during atlas refresh --space. Remote or unavailable ships remain unavailable; this does not connect, restore or board.'
            continue
        if name=='files':
            s.add_argument('ref',metavar='PLACE',help='Exact product, experiment or district ID, or unique name.')
            s.add_argument('--query',default='',help='Filter retained file paths by words; never searches live source.')
            s.add_argument('--limit',type=int,default=40,help='Files per page, 1–200 (default 40).')
            s.add_argument('--offset',type=int,default=0,help='File offset; use the returned continuation command.')
            s.add_argument('--generation',default='',help='Inventory identity returned by a previous page; rejects changed sources.')
            s.add_argument('--space-cache',type=Path,help='Saved geography; defaults beside the index.')
            s.add_argument('--source-cache',type=Path,help='Published Starforge harvest cache.')
            s.add_argument('--index',type=Path,help='Index location for default cache paths.')
            s.add_argument('--json',action='store_true',help='File paths, exact reader references, pagination and coverage.')
            s.epilog='Example: navcom atlas files <district-id> --query jobs\nUse the returned sources read command to open a file. This lists retained harvests, not a full live repository. No harvest, source scan or model runs.'
            continue
        if name=='related':
            s.add_argument('ref',metavar='PLACE',help='Exact place ID or unique name; use its saved harvested source scopes.')
            s.add_argument('--query',default='',help='Filter suggested family paths and run both native search paths in the same scopes (at most 500 characters).')
            s.add_argument('--limit',type=int,default=20,help='Maximum returned families and references per source page (1–100; default 20).')
            s.add_argument('--seconds',type=float,default=15.0,help='Native analysis time budget (1–30 seconds; default 15).')
            s.add_argument('--offset',type=int,default=0,help='Source-scope offset; follow next_offset for pages of 8 sources (default 0).')
            s.add_argument('--space-cache',type=Path,help='Saved geography; defaults beside the index.')
            s.add_argument('--source-cache',type=Path,help='Published NavCom Starforge harvest cache.')
            s.add_argument('--index',type=Path,help='Index location for default cache paths; conversations are not scanned.')
            s.add_argument('--json',action='store_true',help='Native evidence, exact paths, snapshot provenance and coverage.')
            s.epilog='Examples: navcom atlas related <planet-id>\n          navcom atlas related <planet-id> --query engines --json\nUses retained harvest snapshots and caches native Starforge analysis. No new harvest, model, source sync or chart changes. Family scores are heuristic suggestions, not dated succession; documented references do not prove ownership or ancestry. Result caps and source pagination are explicit.'
            continue
        if name in ('ask','board'):
            s.add_argument('ref',help='Exact star or ship ID, or unique name from atlas list.')
            if name=='ask':s.add_argument('question',help='Question for this expert. Preparation does not send it.')
            else:
                s.add_argument('--route',type=Path,help='Exact native route when automatic route discovery is ambiguous.')
                s.add_argument('--validate',action='store_true',help='Read-only native thread and working-directory check.')
            s.add_argument('--launch',action='store_true',help='Explicitly open this reviewed native action in a new terminal.'+(' Hermes may run tools and use remote models.' if name=='ask' else ''))
            s.add_argument('--review',default='',help='Exact identity printed by preparation; changing inputs requires a fresh review.')
            s.add_argument('--space-cache',type=Path,help='Saved geography; defaults beside the index.')
            s.add_argument('--index',type=Path,help='Index location for default cache paths.')
            s.add_argument('--json',action='store_true',help='Versioned plan, provenance and disclosed effects.')
            s.epilog='Prepare first; then repeat with --launch --review TOKEN. No services are started by inspection. Terminal dispatch does not establish receipt, readiness or human takeover.'
            continue
        if name=='inspect':
            s.add_argument('ref',help='Exact product, experiment, district, ship or star ID, or unique destination name.')
            s.add_argument('--refresh',action='store_true',help='Repeat the read-only metadata observation; never restore, launch or board.')
            s.add_argument('--observe',action='store_true',help='Explicitly check a star provider process; never start a gateway, model or inference.')
            s.add_argument('--space-cache',type=Path,help='Geographic cache JSON; default beside the index.')
            s.add_argument('--index',type=Path,help='Index path used to locate the default geographic cache.')
            s.add_argument('--json',action='store_true',help='Versioned physical checkout, ship or star evidence with dated observations.')
            s.epilog='Examples: navcom atlas inspect <planet-id> --refresh\n          navcom atlas inspect <ship-id>\n          navcom atlas inspect <star-candidate-id> --observe\n  navcom atlas ask <star-candidate-id> "Explain your expertise"\n  navcom atlas board <ship-id> --validate\n  navcom voice status\nCode-location inspection uses native Git and is cached until --refresh. It distinguishes linked worktrees from independent copies without choosing a preferred copy. Metadata and recorded receipts do not prove current readiness. Star observation checks an existing process; it never asks an agent or starts a model. Remote ship locations remain unobserved.'
            continue
        if name=='list':s.add_argument('grouping',choices=sorted(set(GROUPS)|SPACE_KINDS))
        if name=='explore':s.add_argument('collection',help='Stable collection ID printed by list/explore.')
        if name in ('search','navigate'):s.add_argument('words',nargs='+',help='Natural words; quote phrases when convenient.')
        if name=='navigate':
            s.add_argument('--choose',default='',metavar='PLACE_ID',help='Choose one returned candidate for a named-place search; remains inside the allowed scope.')
            s.epilog='Examples: navcom atlas navigate "find matrix in EXP32"\n          navcom atlas navigate "fly to EXP32 then find matrix"\n          navcom atlas navigate "find login within Mobile" --choose <returned-place-id>\nNamed places resolve against the current chart before source/conversation search. Ambiguous or missing places never trigger a galaxy-wide fallback.'
            s.add_argument('--global',dest='global_scope',action='store_true',help='Search the entire galaxy instead of --within; returns explicit scope and steps.')
            s.add_argument('--within',metavar='PLACE',help='Current place ID or exact unique name; defaults to the galaxy.')
        if name in ('show','tree'):s.add_argument('ref',help='Conversation ref printed in results; ambiguous refs require more characters.')
        if name not in ('list','refresh','navigate'):s.add_argument('--group-by',dest='grouping',choices=sorted(set(GROUPS)|SPACE_KINDS),help='Grouping context; defaults to the selected collection, otherwise topics.')
        if name=='show':
            s.add_argument('--start',type=int,default=1,help='Evidence turn to preview (default 1).')
            s.add_argument('--within',help='Collection context for this conversation.')
            s.add_argument('--query',help='Search phrase retained as context; --start selects the evidence turn.')
        if name not in ('refresh','show','tree','navigate'):
            if name!='explore':s.add_argument('--within',metavar='COLLECTION',help='Limit to this entire collection, across all pages.')
            if name not in ('search','navigate'):s.add_argument('--query',metavar='WORDS',help='Filter by indexed conversation evidence.')
            s.add_argument('--provider',help='Provider name or comma-separated names.')
            s.add_argument('--since',help='Last active on/after YYYY-MM-DD or relative 7d, 12h.')
            s.add_argument('--until',help='Last active on/before YYYY-MM-DD or relative time.')
            s.add_argument('--favorites',action='store_true',help='Only saved favorites.')
            s.add_argument('--children',action='store_true',help='Show child tasks separately; default groups matches under their root.')
        if name!='refresh':
            s.add_argument('--limit',type=int,default=12,help='Items per page (1–200; default 12).')
            if name!='navigate':s.add_argument('--offset',type=int,default=0,help='Skip this many items; default 0.')
        else:
            s.add_argument('--harvest',action='store_true',help='With --space: resume automatic discovery and native Starforge harvest before charting.')
            s.add_argument('--seconds',type=float,default=60,help='With --harvest: wall-time budget, 1–120 seconds (default 60).')
            s.add_argument('--limit',type=int,default=20,help='With --harvest: at most this many pinned projects per pass (1–200; default 20).')
            s.add_argument('--restart',action='store_true',help='With --harvest: start a fresh inventory sweep; otherwise resume saved progress.')
        if name!='navigate':s.add_argument('--space',action='store_true',help='Use cached galactic destinations; refresh builds their evidence.')
        s.add_argument('--space-cache',type=Path,help='Geographic cache JSON; default beside the index.')
        s.add_argument('--source-cache',type=Path,help='NavCom Starforge harvest cache.')
        if name!='navigate':s.add_argument('--evidence',action='store_true',help='Search existing source, host conversation and carried ship context within this place.')
        s.add_argument('--json',action='store_true',help='Versioned structured output; diagnostics go to stderr.')
        s.add_argument('--index',type=Path,help='Index path; defaults to NAVCOM_INDEX or the usual Codex index.')
        s.epilog={'list':'Example: navcom atlas list research\nNext: navcom atlas explore <collection>','explore':'Example: navcom atlas explore research:exp29\nNext: navcom atlas search listener --within research:exp29','search':'Example: navcom atlas search listener --within research:exp30 --json\nNext: navcom atlas show <ref>','show':'Example: navcom atlas show <ref>\nNext: use the printed --open or --resume command. No harness is launched here.','tree':'Example: navcom atlas tree <ref> --limit 50\nMissing parents are labeled; shared topics never become tree edges.','refresh':'Example: navcom atlas refresh --space --harvest --seconds 60\nResumes a pinned project sweep; progress and failures are saved. --restart starts a new sweep.\nWithout --harvest, refresh only rebuilds cached geography/evidence; no raw-log scan.'}.get(name)
    return p


def help_text(api,subject=None,atlas=False):
    if subject=='space' or subject in SPACE_KINDS:
        meanings={'systems':'Substantial client/venture suites; folder-derived membership is labelled suggested.',
            'planets':'Product destinations, with manifest-backed app boundaries kept distinct inside repositories.',
            'moons':'Experiments, never provider child conversations.',
            'cities':'Conceptual districts suggested by existing Starforge token groups; inspect paths and cohesion.',
            'ships':'Starship snapshot entries. Recorded receiving tests do not establish current boarding readiness.',
            'bases':'Actual Starship storage destinations; host and physical location are separate from conceptual geography.',
            'starbases':'Actual Starship storage destinations, with snapshot provenance and live status unknown.',
            'stars':'Living-expertise candidates from provider descriptions and charter references. Declared metadata is not verified runtime readiness; automatic descriptions remain unconfirmed.',
            'galaxies':"Your work across storage locations; machines are not galaxies."}
        return """Galactic navigation — one cached geography for CLI and browser.

  navcom atlas refresh --space --harvest
  navcom atlas list systems
  navcom atlas list planets --within <system-id>
  navcom atlas explore <planet-id>
  navcom atlas files <district-id> --query login
  navcom atlas search matrix --within <moon-id> --evidence
  navcom atlas search exp32 --space
  navcom atlas navigate "fly to exp32"
  navcom atlas navigate "find matrix" --within <moon-id>
  navcom atlas related <planet-id> --query engines
  navcom atlas inspect <planet-id> --refresh
  navcom atlas list ships
  navcom atlas inspect <ship-id>
  navcom atlas context <ship-id> --query decision
  navcom atlas list stars
  navcom atlas inspect <star-candidate-id> --observe
  navcom atlas ask <star-candidate-id> "Explain your expertise"
  navcom atlas board <ship-id> --validate
  navcom voice status
  navcom sources read <source-id> <file-path> --line 1 --limit 80
  navcom history timeline <planet-id>
  navcom history explore <planet-id> <commit> --query login
  navcom history system <system-id> --at 2026-04-01 --json
  navcom history system --cursor <next-cursor> --json
  navcom history land <planet-id> --cursor <cursor> --result-key <result-key>

Search without --evidence finds destination metadata. --evidence also runs the
existing Starforge concept/text, NavCom conversation and native Starship carried
context searches in that place. Carried matches keep the exact ship, catalog and
original turn; repeated searches reuse cached native results and check remaining
ships within the budget. An exact ship search never substitutes another copy.
Source --path scopes constrain both engines. A reported cap or unavailable source
means evidence coverage is incomplete. No model is needed.
Related uses existing Starforge lineage and code-search on retained harvests to
find suggested version families and literal cross-project document references.
It does not harvest again or change the chart. --query also searches both native
paths within those saved scopes. Source pages contain up to 8 sources; follow
next_offset or the printed continuation command. Suggestions are not dated
succession, ownership or conversation ancestry.
Navigator accepts typed or transcribed requests, reports the steps it took and
resolves unambiguous destinations. Ambiguous names return choices. It never
launches a shell command or claims to have boarded a ship.

Refresh saves current evidence, candidate/declared relationships and stable
positions; ordinary navigation does not scan source. --space-cache and
--source-cache select private caches. sources discover is paginated; follow its
reported next_offset to harvest more than the first page. --menu offers the same
Galactic bridge and a tool-driven refresh of discovered material.

Show, explore and search include a bounded contents preview: counts and named
direct children from the same published chart. JSON provides their exact IDs;
these are recorded places, not a generated product summary. Runnable applications
inside an explicit experiment remain lab applications within that moon, rather
than extra product planets. Their native application evidence and file scope
remain inspectable.

Inspect a product, experiment or district to see its physical code locations,
branches, commits and linked worktrees. These dated observations are cached until
--refresh; runtime, working changes and preferred copy are not inferred.

Stars require provider description/charter evidence and remain candidates. Inspect
reads cached metadata; --refresh updates the selected dossier; --observe explicitly
checks an existing provider process without inference or service startup. Ask
prepares a native Hermes question; --launch --review TOKEN explicitly opens it.
Hermes uses its own tools, hooks and configured model, possibly remotely. Board
discovers native captain routes; --validate checks the exact thread and workspace.
An explicit launch revalidates and opens the native captain; takeover stays unproven. Stars
can relate to implementation products without acquiring client/system ownership.
Ship/base entries require actual records. Refresh also discovers local commission
archives from exact native evidence, using a bounded metadata cache. list ships
and search include stored copies; explore links their catalog without filling
the conceptual overview. Stored archives can read carried context but cannot board.
Ship inspection uses installed
Starship tools and matching historical receipts. Remote hosts remain unobserved;
integrity, receiving checks and captain takeover are separate from metadata.
Source reads use exact published snapshots, never current working files. History
explores one committed place or pages through system/galaxy repository histories
at a UTC cutoff. Current addresses stay fixed; committed content supplies past
labels and evidence. Missing history stays unknown. Cursor pages retain pinned
HEADs and never substitute current conversations or infer historical ownership.
Land follows a saved system result into a product and its native code groups;
queries stay within the pinned product or district files. Use the printed Land
command instead of transcribing the cursor and result key yourself.
Use navcom help history and navcom sources read --help for detailed parameters.
""" + ('\n'+meanings[subject]+'\n' if subject in meanings else '')

    if subject=='voice':
        import navcom_voice
        voice=navcom_voice.parser()
        return voice.format_help()+'\n'+ '\n'.join(child.format_help() for child in voice._subparsers._group_actions[0].choices.values())
    if subject=='history':
        import navcom_history_cli
        history=navcom_history_cli.parser()
        return history.format_help()+'\n'+ '\n'.join(child.format_help() for child in history._subparsers._group_actions[0].choices.values())
    if subject=='sources':
        import navcom_sources
        return navcom_sources.parser().format_help()
    if subject in (None,'atlas'):return parser().format_help()+'\nGroupings:\n'+ '\n'.join('  '+k+' — '+v for k,v in EXPLAIN.items())
    if subject in EXPLAIN:return subject+'\n\n'+EXPLAIN[subject]+'\n\n'+('navcom atlas tree <ref>' if subject=='ancestry' else 'navcom atlas list '+subject)+'\nUse a printed collection ID with explore or search --within.\n'
    if subject=='all':return api.build_parser().format_help()+'\nSOURCE COMMAND REFERENCE\n'+help_text(api,'sources')+'\nHISTORY COMMAND REFERENCE\n'+help_text(api,'history')+'\nLOCAL VOICE COMMAND REFERENCE\n'+help_text(api,'voice')+'\nGALACTIC NAVIGATION\n'+help_text(api,'space')+'\nATLAS COMMAND REFERENCE\n'+help_text(api)+'\n'+ '\n'.join(parser()._subparsers._group_actions[0].choices[name].format_help() for name in ('list','explore','search','navigate','related','files','context','inspect','ask','board','show','tree','refresh'))
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
    import navcom_navigation as navigation
    if not path.is_file() and not navigation.is_spatial(args):raise ValueError('No index at '+str(path)+'. Run navcom --maintain first.')
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.3) if path.is_file() else None
    try:
        import navcom_navigation as navigation
        if navigation.is_spatial(args):
            import navcom_space
            space_cache,source_cache=navigation.paths(path,args.space_cache,getattr(args,'source_cache',None))
            if args.command=='context':
                if args.turn is not None and not args.session:raise ValueError('--turn requires --session.')
                action='search' if args.query is not None else 'open' if args.session else 'handover' if args.handover else 'inspect'
                result=navigation.context(space_cache,args.ref,action=action,query=args.query or '',ref=args.session or '',turn=args.turn,offset=args.offset,limit=args.limit,max_chars=args.max_chars,expected_catalog=args.catalog)
                if args.json:print(json.dumps(result,ensure_ascii=False))
                else:
                    import navcom_ship_context
                    navcom_ship_context.render(result)
                return 0 if result['state']=='available' else 2
            if args.command=='files':
                import navcom_place_files
                result=navcom_place_files.files(space_cache,source_cache,args.ref,query=args.query,limit=args.limit,offset=args.offset,generation=args.generation)
                if args.json:print(json.dumps(result,ensure_ascii=False))
                else:navcom_place_files.render(result)
                return 0
            if args.command=='related':
                import navcom_relationships
                result=navcom_relationships.related(space_cache,source_cache,args.ref,
                    query=args.query,limit=args.limit,seconds=args.seconds,offset=args.offset)
                if args.json:print(json.dumps(result,ensure_ascii=False))
                else:navcom_relationships.render(result)
                return 0
            if args.command in ('ask','board'):
                result=navigation.interact(api,space_cache=space_cache,within=args.ref,action=args.command,
                    question=getattr(args,'question',''),launch=args.launch,review_token=args.review,
                    route_path=getattr(args,'route',None),validate=getattr(args,'validate',False))
                if args.json:print(json.dumps(result))
                else:navigation.render_interaction(result)
                return 2 if result['interaction']['state']=='blocked' else 0
            if args.command=='inspect':
                result=navigation.inspect(space_cache=space_cache,within=args.ref,refresh=args.refresh,observe=args.observe)
                if args.json:print(json.dumps(result))
                else:navigation.render_inspection(result)
                return 0
            if args.command=='refresh':
                if args.harvest:
                    import navcom_chart_refresh
                    result=navcom_chart_refresh.refresh(path,space_cache,source_cache,seconds=args.seconds,
                        limit=args.limit,restart=args.restart,
                        progress=lambda message:print('NavCom chart ▸ '+message,file=sys.stderr,flush=True))
                    if args.json:print(json.dumps(result))
                    else:
                        print(f"Chart intake: {result['visited']}/{result['total']} projects · {result['harvested']} analyzed · {result['reused']} reused · {len(result['failures'])} failed · {len(result['skipped'])} skipped.")
                        if result['next_command']:print('Continue: '+result['next_command'])
                        if result.get('chart_error'):print('Chart retained: '+result['chart_error'])
                    return 0
                result=navcom_space.refresh(api,conn,space_cache,source_cache=source_cache,
                    progress=lambda *message:print('NavCom geography ▸ '+' '.join(map(str,message)),file=sys.stderr,flush=True))
                if args.json:print(json.dumps(result))
                else:print('Geography refreshed: '+str(len(result['entities']))+' destinations.')
                return 0
            if any(getattr(args,k,None) for k in ('provider','since','until','favorites','children')):
                raise ValueError('Conversation filters apply to conversation collections; geographic evidence is a saved snapshot.')
            if args.command=='tree':raise ValueError('tree shows conversation ancestry; use explore for places.')
            if args.command=='navigate':
                result=navigation.navigate(api,conn,space_cache=space_cache,source_cache=source_cache,
                    text=' '.join(args.words),within=args.within or '',local=not args.global_scope,limit=args.limit,scope_choice=args.choose)
                if args.json:print(json.dumps(result))
                else:navigation.render(result)
                return 0
            result=navigation.view(api,conn,space_cache=space_cache,source_cache=source_cache,
                action=args.command,kind=getattr(args,'grouping','') or '',
                within=getattr(args,'collection',None) or getattr(args,'within',None) or getattr(args,'ref','') or '',
                query=' '.join(args.words) if args.command=='search' else getattr(args,'query','') or '',
                limit=args.limit,offset=args.offset,include_evidence=args.evidence)
            if args.json:print(json.dumps(result))
            else:navigation.render(result)
            return 0
        if args.command=='refresh':
            if args.harvest or args.restart:raise ValueError('--harvest and --restart require --space.')
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
    finally:
        if conn is not None:conn.close()
