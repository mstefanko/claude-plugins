# Prior Art Search - research lens overlay

Apply the normal `agent-research` claim-first contract. Do not change the output schema, required sections, or downstream handoff format.

Bias your investigation toward prior solutions inside and outside this repository.

- Run memory searches on at least three distinct phrasings of the task when memory is available, and cite the search terms in `### Sources`.
- Walk relevant docs, ADRs, and nearby commit history for earlier decisions or attempts that touched the same modules.
- Record prior-art findings as `R-###` claims in `### Research Claims`.
- Classify each prior-art claim as `[REUSE]`, `[ADAPT]`, `[REJECTED-EARLIER]`, or `[NONE]` in the claim text or `Notes:`.
- Use memory, docs, commit references, and URLs as claim evidence or source entries.
- Flag duplicate implementations or previously abandoned approaches without recommending what to do next.

Do not evaluate alternatives or propose an implementation. Analysis decides whether to reuse, adapt, or reject prior art.
