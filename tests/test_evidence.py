"""Generic evidence contracts; no Starship, real private records or model calls."""
import unittest
from navcom_evidence import EvidenceCorpus, resolve, category, fractional_pairs, rrf

def row(n,text,role='user',**kw):
    return dict(id=str(n),session='s',order=n,text=text,role=role,cwd='/work',citation='fixture:'+str(n),event_time=None,observed_at=None,**kw)

class EvidenceTests(unittest.TestCase):
    def corpus(self,records):
        c=EvidenceCorpus(records,[{'id':'app','paths':['/work/app']},{'id':'other','paths':['/work/other']}]);self.addCleanup(c.close);return c
    def test_early_initiating_request_survives_low_overlap(self):
        rows=[row(1,'What choices are available for this workflow?'),row(2,'Build two experiments to discover which approach supports our product.')]
        rows += [row(i,'Explain this unrelated detail before we continue.') for i in range(3,12)]
        rows += [row(12,'mkdir ./app',role='cmd'),row(13,'Creation failed',role='tool')]
        c=self.corpus(rows);p=c.evidence_pack({'entities':['app'],'slots':['request','action'],'boundary':'/work'},4800)
        self.assertEqual(p['slots']['request'],'2');self.assertEqual(c.origin_context('app','/work')['sessions'][0]['introduction'],'12')
        self.assertIn('success not inferred',c.origin_context('app','/work')['sessions'][0]['introduction_status'])
    def test_generic_names_are_not_identity(self):
        c=self.corpus([row(1,'app and other use Python')]);self.assertFalse(c.mentions['1']['resolved']);self.assertFalse(c.related_evidence(['app'],None)['identity_claims'])
    def test_relative_paths_resolve_against_cwd(self):
        c=self.corpus([row(1,'edit ./app/main.py')]);self.assertEqual(c.mentions['1']['resolved'],['app'])
    def test_shell_echo_and_quoted_advice_are_not_requests(self):
        self.assertEqual(category(row(1,'<user_shell_command>mkdir /work/app</user_shell_command>')),'tool_echo')
        self.assertEqual(category(row(2,'another llm said "create the whole app"')),'quoted_history')
    def test_fractional_inventory_cannot_swamp_once_only_pair(self):
        self.assertEqual(fractional_pairs([['a','b']])[('a','b')],1)
        self.assertLess(fractional_pairs([list('abcdefghij')])[('a','b')],.03)
    def test_rrf_duplicates_and_determinism(self):
        self.assertEqual(rrf([['a','a']]),rrf([['a']]))
        c=self.corpus([row(1,'Build /work/app'),row(2,'edit /work/app',role='cmd')]);req={'entities':['app'],'slots':['request','action']}
        self.assertEqual(c.evidence_pack(req),c.evidence_pack(req));self.assertLessEqual(c.evidence_pack(req,35)['characters'],35)
    def test_scope_does_not_leak_other_session(self):
        rows=[row(1,'Build /work/app')];rows.append(dict(row(2,'Edit /work/app'),session='elsewhere'))
        p=self.corpus(rows).evidence_pack({'entities':['app'],'slots':['request'],'scope':['s']})
        self.assertTrue(all(x['session']=='s' for x in p['passages']))
    def test_evidence_and_parameters_invalidate_fingerprint(self):
        a=self.corpus([row(1,'Build /work/app')]);b=self.corpus([row(1,'Keep /work/app')]);req={'entities':['app'],'slots':['request']}
        self.assertNotEqual(a.evidence_pack(req)['fingerprint'],b.evidence_pack(req)['fingerprint'])
        for value in (0,-1,4801):
            with self.assertRaises(ValueError):a.evidence_pack(req,value)
