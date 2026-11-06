"""NavCom retrieval over frozen records, with no model or filesystem I/O.

Scores nominate passages; they never establish identity or claim truth.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations
import math
import posixpath
import re
import sqlite3

import hashlib
import json

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

VERSION = 'navcom.origin-retrieval/2'
PARAMETERS = {'rrf_k': 60, 'mmr_lambda': .7, 'request_tau': 2, 'preceding_requests': 3,
              'evidence_characters': 4800, 'passage_characters': 1100}
PATH = re.compile(r'(?<![\w/])(?:/|\./|\.\./)[\w./+@-]+')
INTRO = re.compile(r'\b(?:mkdir|create|created|add file|copy|copied|rename|renamed|git clone|cp)\b', re.I)
ACTION = re.compile(r'\b(?:mkdir|create|copy|rename|write|edit|import|launch|commit|checkout|worktree|clone|cp|mv)\b', re.I)
CHANGE = re.compile(r'\b(?:instead|legacy|replace|preserve|keep|new|later|formerly|supersed|generic|independent)\w*\b', re.I)
CONFLICT = re.compile(r'\b(?:not|never|unrelated|failed|failure|denied|separate|incorrect|contradict)\w*\b', re.I)
INITIATING = re.compile(r'\b(?:make|build|create|set up|start|implement|try|compare|test)\b', re.I)


def tokens(text):
    return set(re.findall(r'[\w-]+', text.casefold()))


def category(record):
    if record.get('source_kind') in {'git', 'source', 'receipt', 'coverage'}:
        return 'fact'
    text = record['text'].strip()
    if text.startswith('<user_shell_command>'):
        return 'tool_echo'
    if re.match(r'(?:another|the|an?) (?:llm|agent|assistant|model) (?:said|wrote|reported)\b', text, re.I):
        return 'quoted_history'
    if record.get('quoted') or text.startswith('>'):
        return 'quoted_history'
    if record.get('inventory') or (len(PATH.findall(text)) >= 6 and not record['role'] == 'user'):
        return 'inventory'
    if record['role'] == 'cmd':
        return 'action_attempt' if ACTION.search(text) else 'inspection'
    if record['role'] == 'tool':
        return 'tool_echo'
    if record['role'] == 'user':
        return 'request'
    return 'discussion'


def resolve(record, entities):
    """Only contextual paths resolve. Bare names remain ambiguous leads."""
    resolved, leads = set(), set()
    for token in PATH.findall(record['text']):
        path = token.rstrip('.,;:')
        if not path.startswith('/'):
            cwd = record.get('cwd')
            if not cwd or not cwd.startswith('/'):
                continue
            path = posixpath.join(cwd, path)
        path = posixpath.normpath(path)
        matches = [(len(root), entity['id']) for entity in entities for root in entity.get('paths', [])
                   if path == root or path.startswith(root.rstrip('/') + '/')]
        if matches:
            depth = max(n for n, _ in matches)
            choices = {eid for n, eid in matches if n == depth}
            if len(choices) == 1:
                resolved.update(choices)
            else:
                leads.update(choices)
    # Explicitly captured entity bindings are trusted only for structured facts.
    if record.get('source_kind') in {'git', 'source', 'receipt', 'coverage'}:
        resolved.update(set(record.get('entities', [])) & {e['id'] for e in entities})
    words = tokens(record['text'])
    for entity in entities:
        if any(posixpath.basename(p).casefold() in words for p in entity.get('paths', [])):
            leads.add(entity['id'])
    return {'resolved': sorted(resolved), 'ambiguous_leads': sorted(leads - resolved)}


def rrf(rankings, k=60):
    scores = Counter()
    for ranking in rankings:
        for rank, rid in enumerate(dict.fromkeys(ranking), 1):
            scores[rid] += 1 / (k + rank)
    return dict(scores)


def fractional_pairs(episodes, fractional=True):
    scores = Counter()
    for episode in episodes:
        members = sorted(set(episode))
        if len(members) < 2:
            continue
        weight = 1 / math.comb(len(members), 2) if fractional else 1
        for pair in combinations(members, 2):
            scores[pair] += weight
    return scores


class FrozenEvidence:
    def __init__(self, records, entities, coverage=(), parameters=None):
        self.parameters = {**PARAMETERS, **(parameters or {})}
        self.entities = deepcopy(entities)
        ids = [e['id'] for e in entities]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate entity IDs')
        self.records = deepcopy(records)
        self.by_id = {r['id']: r for r in self.records}
        if len(self.by_id) != len(self.records):
            raise ValueError('Duplicate evidence IDs')
        self.coverage = deepcopy(list(coverage))
        self.mentions = {r['id']: resolve(r, entities) for r in self.records}
        self.categories = {r['id']: category(r) for r in self.records}
        self.text_tokens = {r['id']: tokens(r['text']) for r in self.records}
        self.sessions = defaultdict(list)
        for r in self.records:
            self.sessions[r['session']].append(r)
        for rows in self.sessions.values():
            rows.sort(key=lambda r: (r['order'], r['id']))
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE VIRTUAL TABLE passages USING fts5(id UNINDEXED,text)')
        self.db.executemany('INSERT INTO passages VALUES (?,?)', [(r['id'], r['text']) for r in records])

    def close(self):
        self.db.close()

    def origin_context(self, entity, boundary):
        known = next((e for e in self.entities if e['id'] == entity), None)
        if not known or not boundary.startswith('/') or any(not (p == boundary or p.startswith(boundary.rstrip('/') + '/')) for p in known['paths']):
            raise ValueError('Entity outside supplied boundary')
        mentions = [r for r in self.records if entity in self.mentions[r['id']]['resolved']]
        sessions = []
        for sid in sorted({r['session'] for r in mentions}):
            rows = self.sessions[sid]
            hits = [r for r in rows if r in mentions]
            substantive = [r for r in hits if self.categories[r['id']] not in {'inventory', 'tool_echo', 'quoted_history'}]
            introductions = [r for r in substantive if INTRO.search(r['text'])]
            anchor = (introductions or substantive or hits)[0]
            preceding = [r for r in rows if r['order'] <= anchor['order'] and self.categories[r['id']] == 'request']
            candidates = []
            # Opening requests remain candidates even before the entity had a
            # name. They are context, not proof of purpose or identity.
            meaningful = [r for r in preceding if len(tokens(r['text'])) >= 6
                and not r['text'].lstrip().startswith(('# AGENTS.md', '<environment_context>', '<INSTRUCTIONS>'))]
            opening = next((r for r in meaningful if INITIATING.search(r['text'])), meaningful[0] if meaningful else None)
            if opening:
                candidates.append({'id': opening['id'], 'request_distance': len(preceding)-1-preceding.index(opening),
                                   'basis': 'opening request; relevance must be assessed', 'distance_weight': None})
            for distance, row in enumerate(reversed(preceding[-self.parameters['preceding_requests']:])):
                if opening and row['id'] == opening['id']: continue
                candidates.append({'id': row['id'], 'request_distance': distance,
                                   'distance_weight': math.exp(-distance / self.parameters['request_tau'])})
            # Acknowledgments need the preceding assistant question, not a guessed intent.
            context = []
            for item in candidates:
                row = self.by_id[item['id']]
                if len(tokens(row['text'])) < 6:
                    earlier = [r for r in rows if r['order'] < row['order'] and self.categories[r['id']] == 'discussion']
                    if earlier:
                        context.append(earlier[-1]['id'])
            sessions.append({'session': sid, 'first_observed_mention': hits[0]['id'],
                             'first_substantive_mention': substantive[0]['id'] if substantive else None,
                             'introduction': introductions[0]['id'] if introductions else None,
                             'introduction_status': 'attempt_or_statement; success not inferred',
                             'purpose_candidates': candidates, 'reply_context': context})
        return {'entity': entity, 'sessions': sessions, 'global_first': None,
                'limits': ['First within captured coverage, not proof of original creation',
                           'Conversation order does not establish cross-session chronology']}

    def related_evidence(self, entities, scope):
        wanted = set(entities)
        if not wanted.issubset({e['id'] for e in self.entities}):
            raise ValueError('Unknown entity')
        allowed = set(scope) if scope is not None else set(self.sessions)
        ids = [r['id'] for r in self.records if r['session'] in allowed and
               wanted.intersection(self.mentions[r['id']]['resolved'] + self.mentions[r['id']]['ambiguous_leads'])]
        episodes = []
        for sid, rows in self.sessions.items():
            if sid not in allowed:
                continue
            episode = set()
            for row in rows:
                if self.categories[row['id']] == 'request':
                    if episode:
                        episodes.append(episode)
                    episode = set()
                if self.categories[row['id']] not in {'inventory', 'quoted_history', 'tool_echo'}:
                    episode.update(self.mentions[row['id']]['resolved'])
            if episode:
                episodes.append(episode)
        return {'ids': ids, 'pairs': [{'entities': list(k), 'weight': v} for k, v in sorted(fractional_pairs(episodes).items())],
                'identity_claims': False}

    def evidence_pack(self, requirements, budget=4800):
        if type(budget) != int or not 1 <= budget <= 4800:
            raise ValueError('Evidence budget must be 1..4800 characters')
        selected_entities = requirements['entities']
        scope = requirements.get('scope')
        related = self.related_evidence(selected_entities, scope)
        permitted = set(scope) if scope is not None else set(self.sessions)
        query_words = tokens(requirements.get('query', ''))
        for entity in self.entities:
            if entity['id'] in selected_entities:
                query_words.update(posixpath.basename(p) for p in entity['paths'])
        query = ' OR '.join('"' + w.replace('"', '""') + '"' for w in sorted(query_words) if w)
        lexical = [r[0] for r in self.db.execute('SELECT id FROM passages WHERE passages MATCH ? ORDER BY bm25(passages),id', (query,))] if query else []
        lexical = [rid for rid in lexical if self.by_id[rid]['session'] in permitted]
        origins = []
        for eid in selected_entities:
            entity = next(e for e in self.entities if e['id'] == eid)
            boundary = requirements.get('boundary') or posixpath.commonpath(entity['paths'])
            for origin in self.origin_context(eid, boundary)['sessions']:
                if origin['session'] in permitted:
                    origins.extend(p['id'] for p in origin['purpose_candidates'])
                    origins.extend(origin['reply_context'])
        eligible = set(related['ids']) | set(origins)
        # Retrieve the whole request/action episode around an entity mention, including outcomes.
        for sid, rows in self.sessions.items():
            if sid not in permitted:
                continue
            groups = []; group = []
            for row in rows:
                if self.categories[row['id']] == 'request' and group:
                    groups.append(group); group = []
                group.append(row['id'])
            groups.append(group)
            for group in groups:
                if set(group).intersection(related['ids']):
                    eligible.update(group)
        actions = [r['id'] for r in self.records if r['id'] in eligible and self.categories[r['id']] in {'action_attempt', 'fact'}]
        scores = rrf([lexical, origins, actions], self.parameters['rrf_k'])
        pools = {
            'request': list(dict.fromkeys(origins + [r for r in related['ids'] if self.categories[r] == 'request'])),
            'action': actions,
            'change': [r for r in eligible if CHANGE.search(self.by_id[r]['text']) and self.categories[r] not in {'inventory', 'tool_echo', 'quoted_history'}],
            'contradiction': [r for r in eligible if CONFLICT.search(self.by_id[r]['text']) and self.categories[r] not in {'inventory', 'tool_echo', 'quoted_history'}],
            'fact': [r for r in eligible if self.categories[r] == 'fact'],
            'outcome': [r for r in eligible if self.categories[r] in {'discussion', 'tool_echo', 'fact'}],
        }
        chosen = []; passages = []; omissions = []; slots = {}
        used = 0
        def add(rid, limit=None):
            nonlocal used
            if rid in chosen:
                return True
            row = self.by_id[rid]
            text = row['text'][:min(limit or self.parameters['passage_characters'], budget - used)]
            if not text:
                return False
            passages.append({k: row.get(k) for k in ('id', 'citation', 'session', 'order', 'event_time', 'observed_at', 'authority', 'source_kind')} |
                            {'text': text, 'category': self.categories[rid], 'mentions': self.mentions[rid],
                             'truncated': row.get('truncated', False) or len(text) < len(row['text'])})
            chosen.append(rid); used += len(text)
            return True
        for slot in requirements['slots']:
            ranked = list(dict.fromkeys(origins + pools.get(slot, []))) if slot == 'request' else sorted(pools.get(slot, []), key=lambda rid: (-scores.get(rid, 0), rid))
            pick = next((rid for rid in ranked if rid not in chosen), ranked[0] if ranked else None)
            slots[slot] = pick if pick and add(pick, max(1, budget // max(1, len(requirements['slots'])))) else None
            if not slots[slot]:
                omissions.append(slot)
        max_score = max(scores.values(), default=1)
        while used < budget:
            available = eligible - set(chosen)
            if not available:
                break
            def mmr(rid):
                a = self.text_tokens[rid]
                similarity = max((len(a & self.text_tokens[c]) / max(1, len(a | self.text_tokens[c])) for c in chosen), default=0)
                lam = self.parameters['mmr_lambda']
                return lam * scores.get(rid, 0) / max_score - (1 - lam) * similarity
            pick = min(available, key=lambda rid: (-mmr(rid), rid))
            if not add(pick):
                break
        result = {'schema': 'navcom.evidence-pack/1', 'retrieval_version': VERSION, 'parameters': self.parameters,
                  'entities': deepcopy([e for e in self.entities if e['id'] in selected_entities]),
                  'requirements': deepcopy(requirements), 'passages': passages, 'characters': used,
                  'slots': slots, 'missing_slots': omissions, 'coverage': self.coverage,
                  'omitted_records': len(self.records) - len(passages),
                  'limits': ['Slot matches are retrieval heuristics, not semantic validation',
                             'Truncated passages and unvisited sources may conceal contradictions']}
        result['fingerprint'] = digest(result)
        return result


# Public descriptive name; FrozenEvidence remains available for existing callers.
EvidenceCorpus = FrozenEvidence
