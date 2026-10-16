# Starforge already searches the skipped material

The owner asked us to prove broader search before reinventing it. The lab exposed the same harvested snapshots in Starforge's existing source-cache layout and used its unchanged code-search command.

All 40 omitted files were retrievable, including 26 Markdown documents. Five targeted queries and three negative/scope controls passed. Actual CLI calls found the missing discovery class and the EXP32 controller-contract document. Catalog and concept search instead returned related gems; they are complementary surfaces.

Decision: reuse code-search for source/document coverage alongside gem/concept search. Do not change GemFinder simply to make every file a gem. Open: exact-source scoping, structured results/full paths, broad-corpus performance, and production integration. This is literal/regex coverage proof, not semantic-document-search proof.

[Results and reproduction](../LABS/spatial-discovery/BROADER-SEARCH-RESULTS.md).
