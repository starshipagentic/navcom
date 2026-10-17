"""CLI for exact Git revision navigation through the shared historical service."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import sqlite3

import navcom_history


def parser():
    p = argparse.ArgumentParser(
        prog="navcom history",
        description="Explore exact Git commits or a dated system chart, with cached Starforge code and document search.",
        epilog="Examples: navcom history timeline 'Quartz' · navcom history explore 'Quartz' COMMIT --query login · navcom history system 'Coastal tools' --at 2025-04-01 --query login. Current files and conversations are never substituted for historical evidence.")
    commands = p.add_subparsers(dest="action")
    for name, help_text in (("timeline", "List commits touching a place's paths in HEAD ancestry."),
                            ("explore", "Harvest a committed tree and show its files, product clues and native code groups."),
                            ("system", "Explore product snapshots across a system or galaxy at a UTC date."),
                            ("land", "Enter a saved historical product or native code group without returning to present-day files."),
                            ("conversations", "Read individually dated conversation turns at or before a UTC cutoff.")):
        child = commands.add_parser(name, help=help_text, description=help_text,
                                    epilog="Commit dates are recorded Git metadata, not deployment dates. Place scopes come from the current catalog; renamed paths are not followed.")
        child.add_argument("place", **({"metavar":"PLACE", "help":"Exact product or experiment ID from the saved historical system view."} if name=="land" else {"nargs":"?", "default":"", "metavar":"PLACE", "help":"Cached system/galaxy ID or unique label; omit when continuing with --cursor." if name=="system" else "Exact cached place ID or unique label; omit with --repo."}))
        if name == "land":
            child.add_argument("--cursor", required=True, help="Pinned system cursor returned by history system; keeps its date and repository heads.")
            child.add_argument("--result-key", required=True, help="Exact result_key returned by that system view; selects its saved native evidence.")
            child.add_argument("--group", help="Exact native district ID returned by a product landing; omit to explore the product.")
            child.add_argument("--query", default="", help="Search both Starforge paths within the saved product or district files.")
            child.add_argument("--cache", type=Path, help="Existing historical cache; default NAVCOM_HISTORY_CACHE or beside the index.")
            child.add_argument("--index", type=Path, help="Determine the default history cache location only; conversations are not read.")
            child.add_argument("--seconds", type=float, default=15, help="Snapshot validation and native search budget in seconds (default 15).")
            child.add_argument("--limit", type=int, default=20, help="Hits per native search path (default 20).")
            child.add_argument("--json", action="store_true", help="Saved chart, exact file scope, immutable source references and search evidence.")
            child.epilog="Start with history system --json, then use its cursor and result_key to land on a returned product ID. Follow a printed district command to inspect that native group. Missing or changed snapshots fail explicitly; this command never resolves current ownership, selects a new HEAD or harvests current files."
            continue
        if name == "conversations":
            child.add_argument("--at", required=True, help="Inclusive UTC cutoff; date means midnight UTC, timestamp needs an explicit offset.")
            child.add_argument("--query", default="", help="Native text search within eligible dated turns; omit for the latest dated passage per conversation.")
            child.add_argument("--limit", type=int, default=20, help="Returned conversations, 1–200 (default 20).")
            child.add_argument("--max-turns", type=int, default=100000, help="Maximum individually inspected user/assistant turns, 1–1000000; incomplete scans are disclosed.")
            child.add_argument("--seconds", type=float, default=5, help="Read budget in seconds, >0–30 (default 5).")
            child.add_argument("--space-cache", type=Path, help="Published current place addresses; defaults to NAVCOM_SPACE_CACHE or INDEX.space.json.")
            child.add_argument("--index", type=Path, help="Existing conversation index, opened read-only without migration or reindex.")
            child.add_argument("--json", action="store_true", help="Dated passages, parent/child links, timestamp coverage and attribution limits.")
            child.epilog="Example: navcom history conversations Aurora --at 2025-05-01 --query login. Current project addresses select scope; dated turns do not prove commit membership or historical ownership. Missing turn dates are excluded, never replaced by file mtimes. No raw logs are read or index refreshed by this command."
            next(a for a in child._actions if a.dest == 'place').help = "Cached place ID or unique label; omit for the current galaxy's project addresses."
            continue
        if name == "system":
            child.add_argument("--at",default="",help="UTC date/time cutoff, e.g. 2026-09-01 or 2026-09-01T12:00:00Z; required for a new journey.")
            child.add_argument("--cursor",help="Continue a returned journey with its pinned repository heads and date.")
            child.add_argument("--retry-larger",action="store_true",help="Retry a snapshot-size failure from --cursor with up to 10000 files/64 MiB per repository in the local cache; retain the same pinned HEADs/date and keep the original view.")
            child.add_argument("--query",default="",help="Search both historical Starforge paths at the selected commits.")
            child.add_argument("--cache",type=Path,help="Historical snapshot cache; default NAVCOM_HISTORY_CACHE or beside the index.")
            child.add_argument("--seconds",type=float,default=30,help="Work per page, >0–120 seconds (default 30); remaining places stay unknown.")
            child.add_argument("--limit",type=int,default=4,help="Repository scopes per page, 1–50 (default 4); follow Continue for the rest.")
            child.add_argument("--max-commits",type=int,default=10000,help="First-parent commit scan cap per repository, 1–100000; preserve when continuing.")
            child.add_argument("--search-limit",type=int,default=20,help="Hits per historical search path per repository, 1–200 (default 20).")
            child.add_argument("--max-files",type=int,help="Snapshot files per repository (new journey default 2000); omitted values inherit the cursor's budget.")
            child.add_argument("--max-bytes",type=int,help="Total snapshot bytes per repository (new journey default 16 MiB); omitted values inherit the cursor's budget.")
            child.add_argument("--max-file-bytes",type=int,help="Maximum individual snapshot file bytes (new journey default 2 MiB); omitted values inherit the cursor's budget.")
            child.add_argument("--space-cache",type=Path,help="Published current place addresses; current content is never substituted.")
            child.add_argument("--source-cache",type=Path,help="Current source registry for address resolution only.")
            child.add_argument("--index",type=Path,help="Determine default caches; current conversations are not read.")
            child.add_argument("--json",action="store_true",help="Structured dated chart, per-place evidence, coverage and continuation cursor.")
            child.epilog="Example: navcom history system 'Coastal tools' --at 2025-04-01 --query login --limit 4. Follow the printed Continue command to retain the same pinned HEADs and date. Use the printed --retry-larger command only after a snapshot-size failure; it creates a separate bounded local-cache view and retains the original. A date means midnight UTC; timestamps need an explicit offset. All place anchors remain visible, including unknown/unvisited history. Commit dates do not establish deployment or historical ownership."
            continue
        if name == "explore":
            child.add_argument("revision", metavar="REVISION", help="Commit SHA from timeline, or a Git revision resolved to a full SHA.")
            child.add_argument("--query", default="", help="Search both Starforge concept/gem and literal code/document paths (maximum 500 characters).")
            child.add_argument("--cache", type=Path, help="Private historical cache outside the repository; default NAVCOM_HISTORY_CACHE or beside the index.")
            child.add_argument("--max-files", type=int, default=10000, help="Abort above this snapshot file count (default 10000).")
            child.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024, help="Abort above total snapshot bytes (default 64 MiB).")
            child.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024, help="Abort above individual searchable file bytes (default 2 MiB).")
        child.add_argument("--repo", type=Path, help="Explicit local Git repository, or select a physical copy belonging to PLACE.")
        child.add_argument("--include", action="append", help="Narrow to a literal repository-relative path; repeat for a union. Cannot widen a selected place.")
        child.add_argument("--space-cache", type=Path, help="Published place catalog; default NAVCOM_SPACE_CACHE or INDEX.space.json.")
        child.add_argument("--source-cache", type=Path, help="Current source registry used only to resolve district addresses; never searched for historical results.")
        child.add_argument("--index", type=Path, help="Determine default cache locations from this conversation index; no conversations are read.")
        child.add_argument("--limit", type=int, default=50, help="Timeline rows or hits per search path, 1–200 (default 50).")
        child.add_argument("--json", action="store_true", help="Shared service JSON; progress and errors go to stderr.")
    return p


def render(result):
    if result.get('action') == 'land':
        center=result['center']
        print(center['label']+' · '+center['kind']+' · '+result['as_of'])
        print('Commit '+result['commit']+' · saved historical evidence')
        print(' / '.join(node['label'] for node in result.get('breadcrumbs',[])))
        for node in result.get('nodes',[]):
            print('\n'+node['label']+' · '+node['id'])
            if node.get('description'):print('  '+node['description'])
            if node.get('land_command'):print('  '+node['land_command'])
        files=result.get('files',[])
        print('\n'+str(len(files))+' retained files in this scope:')
        for file in files[:20]:print('  '+file['path'])
        if len(files)>20:print('  First 20 shown; --json returns the full retained inventory.')
        if result.get('evidence'):
            import navcom_sources
            navcom_sources.render(result['evidence'])
        if result.get('coverage',{}).get('complete') is False:print('\nCoverage is partial; retained files do not establish a complete historical repository.')
        for field in ('identity_policy','conversation_policy'):
            if result.get(field):print(result[field])
        if result.get('cli_command'):print('\nReplay this landing:\n'+result['cli_command'])
        return
    if result.get('action') == 'conversations':
        print(result['selected_place']['label']+' · current address · at or before '+result['as_of'])
        for node in result['conversations']:
            prefix='↳ Child of '+node['parent_ref']+' · ' if node.get('parent_ref') else ''
            print('\n'+prefix+node['label'])
            print('  '+node['recorded_at']+' · '+node['provider']+' · '+node['ref']+':'+str(node['start']))
            print('  Current project address: '+node['current_project'])
            print('  '+node['excerpt'])
        coverage=result['coverage']
        if not result['conversations']:print('\nNo eligible dated conversation passages were found.')
        print('\nCoverage: '+str(coverage['scanned_turns'])+' turns inspected; '+str(coverage['dated_turns'])+' dated; '+str(coverage['undated_turns'])+' undated; '+str(coverage['invalid_timestamp_turns'])+' invalid; '+str(coverage['future_turns_excluded'])+' after cutoff.')
        print(str(len(result['conversations']))+' of '+str(coverage['matching_conversations'])+' matching conversations returned; '+('complete scoped read.' if coverage['complete'] else 'coverage is partial.'))
        for gap in result['gaps']:print('Gap: '+gap)
        print(result['attribution_policy'])
        if result.get('cli_command'):print('\nRepeat this dated read:\n'+result['cli_command'])
        return
    if result.get('action')=='system':
        print((result.get('center',{}).get('label') or 'Historical geography')+' · '+str(result.get('as_of','')))
        if result.get('derived_from_session_id'):
            print('Larger bounded retry of pinned journey '+result['derived_from_session_id']+'; original view retained.')
        for node in result.get('nodes',[]):
            if node.get('id')==result.get('center',{}).get('id'):continue
            print('\n'+node.get('label',node['id'])+' · '+node.get('kind','place')+' · '+node['id'])
            state=node.get('historical_state','unknown')
            if state=='committed':
                print('  Commit '+node['commit']+' · '+node['committed_at'])
                if node.get('description'):print('  '+node['description'])
                print('  '+str(len(node.get('files',[])))+' committed files · '+str(len(node.get('structure',{}).get('token_groups',[])))+' native code groups')
                if node.get('land_command'):print('  Land: '+node['land_command'])
            elif state=='navigation_anchor':
                print('  Current navigation anchor; historical ownership is not inferred.')
            else:
                print('  Unknown: '+str(node.get('historical_gap') or 'This repository page has not been visited.'))
            if node.get('current_label') and node['current_label']!=node.get('label'):
                print('  Current address label: '+node['current_label'])
        for repository in result.get('repositories',[]):
            data=repository.get('data') or {}
            if data.get('evidence'):
                import navcom_sources
                print('\nHistorical search · '+data['repository']+' @ '+data['commit'][:12])
                navcom_sources.render(data['evidence'])
        coverage=result.get('coverage',{})
        print('\nCoverage: '+str(coverage.get('completed_scopes',0))+'/'+str(coverage.get('eligible_scopes',0))+' places reconstructed; '+str(len(coverage.get('unknown_scope_ids',[])))+' unknown. '+str(coverage.get('visited_repositories',0))+'/'+str(coverage.get('pinned_repositories',0))+' repositories visited.')
        skipped=sum(len(c.get('rejected',[])) for c in coverage.get('snapshot_coverage',[]))
        if skipped:print('Historical source exclusions: '+str(skipped)+' files or paths; use --json for reasons.')
        dates=result.get('available_dates',[])
        if dates:print('Observed commit dates: '+(', '.join(dates) if len(dates)<=6 else dates[0]+' to '+dates[-1]+' ('+str(len(dates))+' observations)'))
        if not result.get('date_coverage',{}).get('complete'):print('Date coverage is partial; unavailable or unvisited histories may contain other dates.')
        print('Git dates are recorded metadata, not deployment dates. Current files and conversations are excluded.')
        if result.get('cli_command'):print('\nReplay this pinned page:\n'+result['cli_command'])
        if result.get('continue_command'):print('\nContinue:\n'+result['continue_command'])
        if result.get('retry_larger_command'):print('\nRetry snapshot-size failures with a larger bounded local cache, keeping these pinned HEADs and date:\n'+result['retry_larger_command'])
        return
    place = result.get("selected_place")
    print((place["label"] + " · " if place else "") + result["repository"])
    print("Selected paths: " + ", ".join(result["include"]))
    if result["action"] == "timeline":
        for commit in result["commits"]:
            print(commit["commit"] + "  " + commit["committed_at"] + "  " + commit["subject"])
            print("  Author: " + commit["authored_at"] + " · tree " + commit["tree"])
        if not result["commits"]:
            print("No commits touch these paths in HEAD ancestry.")
        if result["truncated"]:
            print("More commits exist; increase --limit (maximum 200).")
        if result["shallow"]:
            print("Shallow repository: earlier history may be unavailable.")
        print(result["selection_policy"])
        return
    snapshot = result["snapshot"]
    print("Commit " + result["commit"] + " · tree " + result["tree"])
    print("Committed " + result["committed_at"] + " · authored " + result["authored_at"])
    print("Historical snapshot: " + snapshot["snapshot_path"])
    print("Cache: " + ("reused" if snapshot["cache_hit"] else "created") + "; " + str(snapshot["coverage"]["files"]) + " files")
    for manifest in result["manifests"]:
        print("Manifest " + manifest["path"] + ": " + json.dumps(manifest["metadata"], ensure_ascii=False))
    for clue in result["product_clues"]:
        print("  " + clue["text"] + " [" + clue["basis"] + "]")
    for group in result["structure"].get("token_groups", []):
        print("Code group: " + ", ".join(group["shared_tokens"][:8]) + " · " + ", ".join(group["paths"]))
    print("Files:")
    for entry in snapshot["files"]:
        print("  " + entry["path"])
    for exclusion in snapshot["coverage"]["rejected"]:
        print("Skipped " + exclusion["path"] + ": " + exclusion["reason"])
    for warning in result["warnings"]:
        print("Notice: " + warning)
    if result["evidence"]:
        import navcom_sources
        navcom_sources.render(result["evidence"])
    print(result["date_policy"])
    print(result["conversation_policy"])


def progress(message):
    stage=message.get('stage')
    number=message.get('completed',0)+1
    total=message.get('total',0)
    if stage=='pin':
        text='Inspecting address '+str(number)+'/'+str(total)+' · '+str(message.get('scope_id',''))
    elif stage=='reconstruct':
        text='Reading dated repository '+str(number)+'/'+str(total)+' · '+', '.join(message.get('scope_ids',[]))
    else:
        text='Reading historical evidence'
    print('navcom history ▸ '+text,file=sys.stderr,flush=True)


def run(api, argv):
    p = parser()
    args = p.parse_args(argv)
    if not args.action:
        p.print_help()
        return 0
    if args.action == 'system' and args.retry_larger and not args.cursor:
        p.error('--retry-larger requires --cursor from a journey with a snapshot-size failure')
    index = (args.index or api.default_index_path()).expanduser()
    from navcom_navigation import history_cache, paths
    space, sources = (None,None) if args.action=='land' else paths(index, args.space_cache, getattr(args,'source_cache',None))
    kwargs = dict(action=args.action, repo=getattr(args,'repo',None), space_cache=space, source_cache=sources,
                  include=getattr(args,'include',None), limit=args.limit)
    if args.action == "explore":
        kwargs.update(cache_path=args.cache or history_cache(index),
                      query=args.query, max_files=args.max_files, max_bytes=args.max_bytes, max_file_bytes=args.max_file_bytes)
    try:
        message=("reading committed timeline" if args.action=="timeline" else
                 "entering saved historical source scope" if args.action=="land" else
                 "reading individually dated indexed turns" if args.action=="conversations" else
                 "retrying snapshot-size failures with larger bounds and the same pinned repository heads" if args.action=="system" and args.retry_larger else
                 "continuing pinned system history" if args.action=="system" and args.cursor else
                 "pinning system addresses and repository heads" if args.action=="system" else
                 "preparing exact commit and checking cached Starforge harvest")
        print("navcom history ▸ "+message,file=sys.stderr,flush=True)
        if args.action=='land':
            import navcom_historical_landing
            result=navcom_historical_landing.landing(args.cursor,args.place,result_key=args.result_key,
                group_id=args.group,query=args.query,limit=args.limit,seconds=args.seconds,
                cache_path=args.cache or history_cache(index))
        elif args.action=='conversations':
            import navcom_historical_conversations
            conn=sqlite3.connect(index.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
            try:
                result=navcom_historical_conversations.view(api,conn,within=args.place,as_of=args.at,
                    space_cache=space,query=args.query,limit=args.limit,max_turns=args.max_turns,seconds=args.seconds,
                    index_path=index)
            finally:conn.close()
        elif args.action=='system':
            import navcom_system_history
            result=navcom_system_history.view(args.place,args.at,space_cache=space,source_cache=sources,
                cache_path=args.cache or history_cache(index),
                query=args.query,limit=args.limit,cursor=args.cursor,seconds=args.seconds,max_commits=args.max_commits,
                max_files=args.max_files,max_bytes=args.max_bytes,max_file_bytes=args.max_file_bytes,search_limit=args.search_limit,progress=progress,
                retry_larger=args.retry_larger)
        else:result = navcom_history.view(args.place, getattr(args, "revision", ""), **kwargs)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            render(result)
        return 0
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print("navcom history: " + str(exc), file=sys.stderr)
        if getattr(exc, "coverage", None):
            print(json.dumps(exc.coverage, ensure_ascii=False), file=sys.stderr)
        return 2
