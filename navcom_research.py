"""Evidence-led research trails. Project identity is distinct from a transcript mention.

Descriptions below are grounded in the cited source documents; they describe
research approaches, not current runtime health or experimental success.
"""
import difflib
import re
from pathlib import Path

PROFILES = {
 'exp29': dict(label='EXP29 · Protocol-guided chatbot',
   question='How can a chatbot hear concerns and follow inspectable protocols?',
   approach='Observer / listener + trained heads + deterministic protocol engine + speaker.',
   distinction='Engine lineage v13–v34. v34 is an EXP29 engine version, not EXP30.',
   aliases='chatbot chatbots cbt mental health clinical clinic protocol engine listener v13 v14 v15 v16 v17 v18 v19 v20 v21 v22 v23 v24 v25 v26 v27 v28 v29 v30 v31 v32 v33 v34',
   sources=['README.md','services/semantic-classifier/VERSIONS.md'],
   branches=[(f'v{i}',f'v{i}',f'"v{i}"', 'Version mentioned in this lab’s indexed conversation; not a claim of runtime status.') for i in range(13,35)]),
 'exp30': dict(label='EXP30 · Listener Lab & MLX chat',
   question='Can a small trained listener guide chat and blend with ML signals?',
   approach='Ministral fine-tuning, MLX inference, ML/LLM blending, NOW/EXPLORE scores and conversational routing.',
   distinction='Separate experiment. Its V1, V2 and V2.1 are not EXP29 v30–v34.',
   aliases='chatbot chatbots cbt listener lab mlx ministral trained training finetune blend blending slider v1 v2 v2.1 voice chat',
   sources=['README.md','ENGINE-V2.md'],
   branches=[('v1','V1 · Original engine','"v1"','Original engine; version mention in EXP30.'),('v2','V2 / V2.1 · Hear, combine, remember','"v2" OR "v2.1"','Hear → combine → remember → choose → speak; V2.1 refines tie-breaking.'),('trained','Trained listener · Ministral / MLX','"ministral" OR "mlx"','Model training and local inference, distinct from engine-version results.'),('blend','ML / LLM blend & answer memory','"blend" OR "answers-v1" OR "answer memory"','Combining signals and propagating supported answers.')]),
 'exp32': dict(label='EXP32 · JEV / hybrid investigation',
   question='Can JEV decisions preserve meaning, context, strength and clarity?',
   approach='Full-reader replacement versus a proposed hybrid; later strength/clarity arcs and hotflywheel experiments.',
   distinction='Separate attempt reusing EXP29’s engine. Observatory began here before moving to its own project.',
   aliases='chatbot chatbots cbt jev hybrid gemma qwen strength clarity arcs hotflywheel reader replacement semantic observatory',
   sources=['README.md','plans/semantic-observatory-stepwise/README.md'],
   branches=[('reader','Reader replacement / hybrid','"hybrid" OR "read_with" OR "replacement"','Track A: existing full-reader replacement. Track B: hybrid proposal; distinguish tests from proposals.'),('arcs','Strength / clarity · arcs & formats','"strength" AND "clarity"','Controlled semantic readings and context/format effects.'),('hotflywheel','Hotflywheel · ongoing conversational state','"hotflywheel"','Activity, participation, release and conversational state experiments.'),('observatory','Semantic Observatory · origin & handoff','"semantic observatory" OR "semanticobservatory"','Observatory planning remains in EXP32 history; the separate project is linked at the family level.')]),
 'observatory': dict(label='Semantic Observatory · Decision benchmark',
   question='Which semantic decisions do models get right, and why do they fail?',
   approach='SSDB semantic decision benchmark, strength/clarity arcs, measured model comparisons and research publication.',
   distinction='Research and benchmark project derived from EXP32 evidence; not another chatbot-engine version.',
   aliases='semanticobservatory semantic observatory ssdb benchmark hermes strength clarity arcs models leaderboard research chatbot experiments',
   sources=['README.md','HANDOFF.md'],
   branches=[('ssdb','SSDB · Benchmark & scoring','"ssdb" OR "benchmark"','Versioned benchmark and scoring methods.'),('arcs','Strength / clarity · model comparisons','"strength" AND "clarity"','Measured semantic readings, model configurations and probabilities.'),('hermes','Hermes · Research worker','"hermes"','Research operation and worker continuity.'),('release','Model release & provenance','"huggingface" OR "release"','Model provenance, artifacts and release evidence.')]),
}

def family(project):
    compact=re.sub(r'[^a-z0-9]','',project.lower())
    for key in ('exp29','exp30','exp32'):
        if re.search(r'(?<![a-z0-9])'+key+r'(?!\d)',project.lower()) or key in compact and re.search(key+r'(?!\d)',compact):return key
    if 'semanticobservatory' in compact:return 'observatory'
    return ''


def normalize_query(query):
    original=query
    query=re.sub(r'\b(?:epx|exp|lab)[ -]?(\d+)\b',r'exp\1',query,flags=re.I)
    query=re.sub(r'\bchat\s+bot\b','chatbot',query,flags=re.I)
    query=re.sub(r'\bversion\s+(\d+(?:\.\d+)?)\b',r'v\1',query,flags=re.I)
    words=re.findall(r'[\w.]+',query.lower())
    vocabulary=['chatbot','experiments','experiment','semantic','observatory','listener','hybrid','strength','clarity','ministral','protocol']
    for w in words:
        if len(w)>4 and w not in vocabulary:
            hit=difflib.get_close_matches(w,vocabulary,n=1,cutoff=.82)
            if hit:query=re.sub(r'\b'+re.escape(w)+r'\b',hit[0],query,flags=re.I)
    query=re.sub(r'\bsemanticobservatory\b','semantic observatory',query,flags=re.I)
    return query, original!=query


def intent(query):
    q,_=normalize_query(query);q=q.lower()
    explicit=[key for key in ('exp29','exp30','exp32') if key in q]
    if 'observatory' in q or 'ssdb' in q: explicit.append('observatory')
    if explicit:return explicit
    if 'jev' in q or 'hybrid' in q:return ['exp32']
    if re.search(r'\bv(?:1[3-9]|2[0-9]|3[0-4])\b',q):return ['exp29']
    if 'mlx' in q or 'ministral' in q or 'listener lab' in q:return ['exp30']
    if any(w in q for w in ('chatbot','cbt','mental health','strength','clarity')):return list(PROFILES)
    return []


def source_notes(profile,projects):
    """Bounded existence checks; do not treat a title match as source verification."""
    result=[]
    for project in sorted(projects,key=len):
        root=Path(project).expanduser()
        for relative in profile['sources']:
            path=root/relative
            if path.is_file():result.append(str(path))
        if result:break
    return result
