"""Mechanism checks, including known failures; not a discovery accuracy score."""
import unittest
import lab

class EvidenceBoundaries(unittest.TestCase):
    def test_renamed_numbered_labs_reference_without_named_rules(self):
        docs=[{'root':'/work/trial742-forest','text':'We compare trial991 findings.'},
              {'root':'/work/trial991-river','text':'An independent research project.'}]
        edges=lab.reference_edges(docs)
        self.assertEqual([(e['source'],e['target'],e['relation']) for e in edges],
                         [('/work/trial742-forest','/work/trial991-river','references_only')])

    def test_ambiguous_prefix_does_not_pick_one(self):
        docs=[{'root':'/work/trial742','text':'compare trial991'},
              {'root':'/work/trial991-forest','text':''},
              {'root':'/work/trial991-river','text':''}]
        self.assertEqual(lab.reference_edges(docs),[])

    def test_prefix_collision_is_not_a_link(self):
        docs=[{'root':'/work/trial742-forest','text':'trial9910 is different'},
              {'root':'/work/trial991-river','text':''}]
        self.assertEqual(lab.reference_edges(docs),[])

    def test_credentials_not_in_remote_identity(self):
        self.assertEqual(lab.remote_identity('https://user:secret@host.example/team/repo.git?token=secret'), 'host.example/team/repo')

    def test_transcript_mention_not_ownership(self):
        a={'path':'/one','text':'belongs to two'};b={'path':'/two','text':''}
        self.assertEqual(lab.typed_pair(a,b),'unresolved')

    def test_moved_checkout_same_repository(self):
        a={'path':'/one','remote':'host/team/repo'};b={'path':'/Volumes/other','remote':'host/team/repo'}
        self.assertEqual(lab.typed_pair(a,b),'same_repository')

    @unittest.expectedFailure
    def test_known_gap_two_products_in_one_repo(self):
        a={'path':'/suite/product-a','remote':'host/team/suite'}
        b={'path':'/suite/product-b','remote':'host/team/suite'}
        self.assertNotEqual(lab.identity(a),lab.identity(b))

if __name__=='__main__': unittest.main()
