# Combined NavCom 0.13.0 release

The owner requested one published version containing the existing navigation UI,
place and source discovery, fleet layout, declared relationships, historical
workspaces, and the new bounded conversation evidence retrieval functions.
This release combines that work in the canonical main checkout. It supersedes
the locally patched 0.11.0 installation and the retrieval-only 0.12.0 release.

Validation before publication: 1,515 tests passed and 16 skipped. After the only
subsequent runtime change (caching passage token sets during MMR selection), all
eight evidence tests passed again. Wheel and source distribution passed Twine's
metadata checks. The bounded evidence reader is supplied no model or network;
interpretation and product decisions remain the caller's responsibility.

Raw private browser receipts stay local. The package contains runtime code,
ship art, and the declared package resources, not those receipts. Existing
earlier diary claims remain dated observations, not newly repeated tests.

Final installed CLI verification found that `--version` still printed a hard-coded
0.11.0 although the installed distribution and all packaged files matched 0.13.0.
Release 0.13.1 corrects that label and adds a regression comparing the CLI with
the distribution version. Navigation and retrieval behavior are unchanged.
