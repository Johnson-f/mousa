# Ask about versioned Git documentation

This example is for a developer or local application looking up Git working-tree
operations. It returns a JSON packet of source passages, not a generated answer.
The bundled corpus contains the Git 2.51.0 `git-restore` and `git-switch` AsciiDoc
manual sources and their three direct include files at commit
`c44beea485f0f2feaf460e2ac87fdd5608d63cf0`: `diff-context-options.adoc`,
`includes/cmd-config-section-all.adoc` and `config/checkout.adoc`, all under
`Documentation/`. Git contributors retain copyright; the unmodified upstream
`COPYING` file is included under GPL-2.0-only. This is a documentation aggregate,
not Git code incorporated into Mousa. Fragments are separate attributed documents,
not expanded into parent coordinates. This is not complete AsciiDoc rendering.
The manifest records direct include relationships and unresolved linked manuals:
git, git-add, git-branch, git-checkout, git-config, git-reset, git-submodule,
git-worktree and gitglossary. No further include dependencies occur in this subset.

## Run

From the Mousa checkout, with Go 1.25+ and Python 3.9+ on Linux:

```sh
CGO_ENABLED=0 go build -o mousa ./cmd/mousa
python3 examples/docs/docs.py --directory ./git-docs prepare
python3 examples/docs/docs.py --directory ./git-docs sync
python3 examples/docs/docs.py --directory ./git-docs ask \
  --budget-bytes 4096 'What does restore overlay mode do?' > packet.json
```

Go dependencies must already be available for an offline build. The example uses
Python's standard library, the existing CLI and the maintained normalized-range
verifier in `eval/local/workflow.py`. Run it from a complete checkout; it is not a
standalone package or stable SDK. Without `--context-tokens`, no network,
model, service or extra framework is needed at runtime. Use `--mousa PATH` and
`--store PATH` before the operation to select a binary and store. The default
store is `docs.sqlite`.

## Optional prompt-content projection

For a caller that counts prompt content with `o200k_base`, install
`tiktoken==0.12.0` in the Python environment and cache that encoding before
offline use. Then add `--context-tokens 512` to `ask`. This opt-in operation
returns `context.text`, a rendered instruction, question and selected passages
with revision-pinned source URLs and line ranges. The URL already contains the
document path, so the citation header does not repeat it. `context.tokens`
counts the entire text using that encoding; it must not exceed the requested
limit. Each whole passage is tried in retrieved order; an oversized passage is
skipped and later passages can still fit. `selected_segment_ids` and
`omitted_segment_ids` record that choice, `sha256` identifies the exact UTF-8
text, and `source_packet_id` names the original byte-packed query packet. It is
not a new canonical packet or Source Trail. A limit too small for the instruction
and question returns an error rather than truncating them. The default `ask`
operation does not load the tokenizer.

Only `context.text` has the stated content-token limit. The surrounding JSON
still contains the complete byte-packed response, including omitted passages;
do not send that JSON as the bounded model input. This does not count chat
message framing, system messages, tool schemas, output reservations or another
model's tokenizer. The caller must account for those separately and check the
target model's actual encoding before treating the cap as a context-window
guarantee. No answerability or semantic selection is inferred from token fit.

In the [pinned development case](https://github.com/graydeon/mousa-benchmarks/tree/4a9a477907b7f0eb7af708118e50c047ba9b2a5d/results/2026-09-29-context-512),
the interactive-hunk question released 3,945 evidence bytes. The original
citation layout needed 524 tokens for the first fragment and its verified
`git-restore` parent passage; at 512 tokens it selected the fragment and an
unrelated `git-switch` passage (507 tokens). Removing the duplicate path from
each citation header retains both the fragment and parent at 511 tokens without
selecting `git-switch`. The parent contains the literal include directive and
the fragment contains the default. The later `git-restore` passage and both
`git-switch` passages remain omitted from the revised rendering, not the byte
packet. This is a single development question; fit does not establish that a
model can answer it. The earlier 544-token observation used the original layout.

In a [separate Git switch configuration case](https://github.com/graydeon/mousa-benchmarks/tree/b791571f569d41beb58a5d03dee167abda48a07a/results/2026-09-29-switch-default-remote), the same 512-token layout did not retain the required pair. A 4,096-byte query retrieved the `checkout.defaultRemote` fragment at rank 2, but the rank-1 switch option passage plus that fragment would cost 602 tokens. The projection kept ranks 1 and 5 at 430 tokens; rank 5 is a generic configuration preface. No retrieved passage contains the `git-switch` parent directive at line 276 that includes the checkout fragment, although the hashed parent and manifest verify that edge. The parent cannot be selected from this packet by changing only its rendering. This observation does not assess a generated answer or establish a general relevance rate.

An [explicit parent follow-up](https://github.com/graydeon/mousa-benchmarks/tree/67a6f0b528019b9ca089fd1ef926b53de0348558/results/2026-09-29-switch-parent-followup) retrieved the `git-switch` passage containing `include::config/checkout.adoc[]` at line 276 in a separate packet and Source Trail. The original packet's complete `checkout.defaultRemote` fragment and the follow-up parent passage require 513 rendered-content tokens together with the original question and citation layout, exceeding the frozen 512-token limit by one. The follow-up's greedy rendering retains the parent but not the fragment; no citation pair or answerability claim follows. The original failed packet, trail and historical report remain unchanged. Neither the limit nor the caller was changed after this observation.

The prior three sequential single-call observations had outer wall times of
242 ms without projection, 1,195 ms at 512 and 1,089 ms at 544 using the
original layout. Startup, tokenizer cache state and accumulated trail history
confound that comparison; it is not a latency benchmark for this change.

## Corpus and sync

`prepare` unpacks the bundled archive into a **new** directory and refuses to
overwrite an existing directory. `corpus.json` pins each source file's SHA-256,
upstream URL, version and revision. Before opening the store, `sync` previews
selection with the same options and requires exact equality with the manifest's
document set. A nested basename collision or a declared file excluded by the CLI
causes refusal without changing the store. The CLI's default hidden/generated,
`.git`, symlink/nonregular, UTF-8, entry and byte limits still apply.
Successful synchronization imports the declared set with `passage-v1`.
The directory's absolute path identifies the source; moving it creates a different
source. Keep the directory and store at stable locations. Use one writer;
trusted corpus files and the manifest must remain stable throughout the command.
Preview followed by synchronization is not an atomic filesystem snapshot.

## Read the packet

- `outcome: evidence_available` means lexical matches fit the budget. It does not
  mean the passages answer the question. `support: not_assessed` and `answer: null`
  are explicit: the caller must assess relevance and completeness.
- `outcome: insufficient_evidence` contains no passages or invented citations.
  Inspect `response.outcome` to distinguish `no_matches`, `budget_omitted`,
  `policy_excluded` and `lifecycle_excluded`. A semantically unrelated lexical
  match can still produce `evidence_available`; there is no answerability model.
- `response.evidence` contains the exact retrieved text, item, segment and
  representation identities, normalized representation SHA-256 and zero-based,
  end-exclusive UTF-8 byte coordinates. `location` adds the pinned source URL
  and one-based normalized line range. Line ranges locate the selected bytes;
  they do not promise a complete section, command or AsciiDoc include.
- `include_relationships` lists direct manifest include edges only when both
  documents contributed selected evidence. Each edge locates the literal
  include directive in its parent with a pinned URL, normalized line and byte
  range; the fragment retains its own URL and coordinates on its evidence hit.
  The example checks the directive against the hashed parent before emitting
  the edge. A lexical hit from `git-switch.adoc` alongside
  `diff-context-options.adoc` does not imply that switch includes the fragment.
  An empty list does not prove that no include exists outside selected evidence.
  These edges describe document structure, not semantic support or access grants.
- The byte budget counts released text once, not JSON metadata, URLs or tokens.
  The example verifies the full normalized source digest before checking every
  selected range and segment digest. It refuses mismatched source files or
  evidence outside the manifest rather than attaching a misleading citation.
- `elapsed_ms` covers corpus loading, CLI process execution and packet construction;
  it excludes the Python interpreter's startup and final stdout serialization.
  The evaluation runner separately records outer end-to-end wall time.

Empty evidence is an expected result and exits zero. Invalid inputs, failed CLI
commands, timeouts, changed corpus hashes or inconsistent evidence exit one with
an error JSON object on stderr and no packet on stdout. Argument errors exit two.
Do not consume a redirected output file unless the process succeeded.

## Updates, deletion and access

For another locally reviewed corpus revision, replace the document bytes and
update `corpus.json` with the actual hashes, revision and source URLs, then rerun
`sync`. Do not assign an upstream URL to locally edited bytes. Remove deleted
paths from `documents` and `files`; the complete directory sync deactivates old
selected items, even if an excluded file still exists on disk. The manifest is
provenance supplied by the corpus maintainer, not an authenticity signature.
A matching hash alone does not establish authorship or authorization.

To remove the final document, set `documents` to `[]`, remove its entry from
`files`, and run `sync`. Empty synchronization explicitly excludes every directory
entry; it never treats missing includes as permission to ingest everything.
It deactivates this source's current items without withdrawing the source or
changing other sources. Repeating it is safe. To repopulate, restore reviewed
document entries and hashes and run `sync` again. After an interrupted sync,
keep the intended manifest stable and retry; do not assume the whole multi-item
operation is atomic. Historical observations and text-free trails remain, as do
saved packets. Empty synchronization is not secure erasure.

Use the existing CLI for access and lifecycle operations:

```sh
./mousa -store docs.sqlite access ./git-docs deny
python3 examples/docs/docs.py --directory ./git-docs ask 'restore overlay'
./mousa -store docs.sqlite access ./git-docs allow
```

Every `ask` makes a fresh authorized query. Saved `packet.json` bytes are a snapshot
of an earlier authorized response, not a fresh authorization or proof that the
source is still current. Denial and deletion do not erase saved files. Keep the
matching corpus revision if you need to verify a saved packet's coordinates;
text-free historical trails cannot reconstruct retired text. Equal text in another
source does not transfer permission or provenance. Filesystem permissions remain
necessary for the store, corpus and saved packets.
Separate files and URLs provide document attribution, not separate authorization
domains: all documents in this directory belong to the same source.

## Acceptance and limited evaluation

```sh
python3 examples/docs/docs_test.py --mousa ./mousa
python3 examples/docs/evaluate.py --mousa ./mousa --output docs-results.json
```

Acceptance uses synthetic lifecycle fixtures to check updates, deletion, denial,
withdrawal, source isolation, changed-byte refusal and saved/current distinctions.
It also exercises the real bundled corpus. The prompt-content projection check
runs when `tiktoken==0.12.0` is installed and is skipped otherwise; a skipped
optional check is not evidence that token projection passed.

`questions.json` fixes four supporting-
passage questions and one no-match case before retrieval. They are development
questions, not held-out evaluation. The evaluation makes five passes of those same
five questions without resetting history or tuning keywords. Its `result: PASS`
means execution completed; `support_covered` records usefulness separately and can
be false. Each packet and latency is retained, including misses.

A [matched-corpus comparison](https://github.com/graydeon/mousa-benchmarks/tree/7292ebd385a9a7430dd457048f9016c3305b01b1/results/2026-09-17-corpus-boundaries)
retains those five cases and six prospectively fixed development cases. Adding
the three include files made four questions fully covered by their declared
supporting excerpts: restore context defaults, interactive restore with nearby
hunks, checkout worker count and the parallel checkout threshold. The interactive
case retrieves both parent applicability and the separately attributed fragment.
Two realistic unsupported questions still return lexical passages without the
requested support; `evidence_available` is not answerability.

The 44-query comparison uses fresh history per query and matched configuration,
not the accumulating-history loop above. Original/expanded median outer query
times were 145.17/156.39 ms on a shared worker. Document bytes grew from 15,969 to
18,615; each ask hashes 34,734/37,380 file bytes including COPYING. These are
small-run observations, not general quality or performance guarantees.

This small study cannot establish general answer quality, semantic retrieval or
universal performance. The lexical CLI can miss a supporting passage that exists
in the corpus. Queries durably record trails, and opening the growing store checks
its history; repeated use can become more expensive. Every `ask` also reads and
hashes every manifest file, including non-document license files, and retains
document bytes for range verification. A small output budget does not bound
corpus reads, memory, startup cost or total query work. No validity cache is used.
