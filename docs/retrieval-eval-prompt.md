You are an expert in information retrieval and ranking systems. I want you to critically evaluate the relevance-ranking logic of a tool I've built, find its failure modes, and propose concrete improvements. Be rigorous and skeptical — I want the weaknesses, not reassurance.

## Context

The tool ("Metatron") stores a company's coding conventions as structured **priors** and serves them to AI coding agents over MCP. When an agent is about to work on some code, it calls one function with:

- `repo` — which repository
- `file_path_or_area` — the path/area it's working in, e.g. `src/components/ApplicationPage` (agents sometimes pass several comma/space-separated paths)
- `task_description` — a natural-language description of what it's doing, e.g. *"change the owner-only 'Write a free review' CTA's href to /blog/write instead of the dashboard"*

The function must return the **8 most relevant priors** (default limit) for that situation. Each prior is a record with these fields relevant to ranking:

- `scope` — a path string the prior applies to, e.g. `src/utils/i18n` (empty string = a global prior that applies everywhere)
- `pattern` — the convention itself, one sentence, e.g. *"Build internal links through the local ./urls helper instead of hardcoding URL strings."*
- `rationale` — a short justification
- `confidence` — LOW / MEDIUM / HIGH

Only `status == CANONICAL` (human-approved) priors are served. A repo may have hundreds to low-thousands of canonical priors. There are **no embeddings** — ranking is lexical only (a deliberate current constraint; embeddings may come later). Latency matters: this runs synchronously on every agent step.

## The algorithm (current implementation, Python)

    _CONFIDENCE_WEIGHT = {LOW: 1, MEDIUM: 2, HIGH: 3}
    _SCOPE_SCALE = 10.0
    _CONF_SCALE = 0.1
    _RESERVED_KEYWORD_SLOTS = 3

    _STOPWORDS = {
        # common English
        "the","and","for","with","that","this","from","into","use","using",
        "add","should","when","your","you","are","but","not","all","any",
        # instruction/filler language (common in task phrasing, rare in priors,
        # so idf-over-priors wrongly rates it HIGH):
        "change","find","its","only","instead","free","make","update","new",
        "set","get","via","per","each","one","want","need","like","also",
        # generic path/structure tokens (no domain meaning as keywords):
        "src","lib","app","index","components","component",
    }

    _STEM_SUFFIXES = ("izations","ization","ships","ship","ments","ment",
        "sions","sion","tions","tion","ness","ings","ing","ies","es","ed","s")

    def _stem(tok):
        # iteratively strip suffixes, never leaving a stem < 3 chars; no "er"/"ers"
        changed = True
        while changed and len(tok) > 3:
            changed = False
            for suf in _STEM_SUFFIXES:
                if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                    tok, changed = tok[:-len(suf)], True
                    break
        return tok

    def _tokens(text):
        return { _stem(tok)
                 for tok in re.split(r"[^a-z0-9]+", text.lower())
                 if len(tok) >= 3 and tok not in _STOPWORDS }

    def _build_idf(priors):
        # inverse document frequency over THIS repo's canonical priors only
        n = len(priors)
        df = {}
        for p in priors:
            for tok in _tokens(p.pattern + " " + p.rationale):
                df[tok] = df.get(tok, 0) + 1
        return { tok: log((n + 1) / (count + 1)) for tok, count in df.items() }

    def _keyword_score(prior, query_tokens, idf):
        overlap = _tokens(prior.pattern + " " + prior.rationale) & query_tokens
        return sum(idf.get(tok, 0.0) for tok in overlap)

    def _pair_scope(prior_scope, area):
        # count shared leading path segments between the prior's scope and one area path
        scope  = prior_scope.strip("/").split("/")
        target = area.strip("/").split("/")
        shared = 0
        for a, b in zip(scope, target):
            if a != b: break
            shared += 1
        if shared == 0:                                  return 0.0   # no relation
        if shared == len(scope) == len(target):          return 3.0 + shared  # exact
        if shared == len(target):                        return 2.0 + shared  # prior INSIDE the area
        if shared == len(scope):                         return float(shared) # prior is an ANCESTOR (closer = higher)
        return 0.0                                                     # siblings: share a parent then diverge

    def _scope_weight(prior_scope, area_paths):
        if prior_scope == "": return 1.0                 # global prior, weak
        return max((_pair_scope(prior_scope, a) for a in area_paths), default=0.0)

    def _relevance(prior, area_paths, query_tokens, idf):
        scope = _scope_weight(prior.scope, area_paths)
        keywords = _keyword_score(prior, query_tokens, idf)
        if scope == 0 and keywords == 0:
            return 0.0                                   # no signal -> filtered out
        return scope * _SCOPE_SCALE + keywords + _CONFIDENCE_WEIGHT[prior.confidence] * _CONF_SCALE

    def get_priors_for_context(store, repo, file_path_or_area, task_description, limit=8):
        priors = store.list(repo=repo, status=CANONICAL)
        idf = _build_idf(priors)
        area_paths = _area_paths(file_path_or_area)        # split on commas/space
        query_tokens = _tokens(task_description)           # NOTE: task only, NOT the area path

        scored, by_keyword = [], []
        for p in priors:
            s = _relevance(p, area_paths, query_tokens, idf)
            if s > 0: scored.append((p, s))
            kw = _keyword_score(p, query_tokens, idf)
            if kw > 0: by_keyword.append((p, kw))
        scored.sort(key=lambda x: x[1], reverse=True)
        by_keyword.sort(key=lambda x: x[1], reverse=True)

        # Fill most slots by the scope-led combined score, but reserve up to 3 for the
        # strongest pure task-keyword matches, so a relevant prior scoped OUTSIDE the
        # named area isn't crowded out by a directory full of generic same-scope priors.
        # If there's no keyword signal at all, scope takes every slot.
        primary_n = max(0, limit - 3) if by_keyword else limit
        picked, seen = [], set()
        def take(pairs, cap):
            for p, _ in pairs:
                if len(picked) >= cap: break
                if p.id not in seen:
                    picked.append(p); seen.add(p.id)
        take(scored, primary_n)   # scope-led primary picks
        take(by_keyword, limit)   # reserved slots: best keyword matches not already picked
        take(scored, limit)       # backfill if there were few keyword matches
        return picked[:limit]

## Design intent (so you can judge it against its goals)

- **Scope is the strong prior**: the agent named a path, so priors scoped exactly at / inside that path should usually win. Scope is scaled (`×10`) so an exact 3-segment match (`3.0 + 3 = 6` → `60`) dominates keyword scores, which are typically single digits.
- **Keywords are the tie-breaker AND an escape hatch**: among same-scope priors, idf-weighted task-keyword overlap decides; and the *reserved slots* let a strongly task-relevant prior from a different directory break in.
- **idf is computed over the repo's own priors** to avoid a hand-maintained stopword list — boilerplate ("shared", "module") gets near-zero weight automatically.
- **Stemming + stopwords** were added because (a) the task says "owner" while the prior says "ownership"; (b) instruction filler like "change"/"find"/"free" is rare in priors so idf rated it *high*, letting coincidental matches win the reserved slots.

## A real example to ground your critique

Query: area `src/components/ApplicationPage`, task *"change the owner-only 'Write a free review' CTA's href to /blog/write instead of the dashboard."*

- The corpus DID contain the right priors: an ownership/auth convention (`src/utils/ownership`, "Clerk auth") and a link convention (`src/utils/i18n`, "build internal links via ./urls helper instead of hardcoding URLs"). Both live OUTSIDE `ApplicationPage`.
- Before the reserved-slots + stemming + token-cleaning changes, the function returned 8 generic `ApplicationPage`-structure priors and none of the relevant ones (ownership scored 0.0; link convention ranked ~#258).
- After the changes, the reserved slots correctly surface the `my-dashboard` Clerk-gating prior and the `blog/write` auth prior. BUT: the link-convention prior STILL doesn't surface — it says "url/links" while the task says "href" (lexical mismatch). And one reserved slot is wasted on a `docs/specs` prior that merely shares the verb "write".

## Your task

Evaluate this ranking logic rigorously. In particular:

1. **Soundness of the scoring model.** Is additive `scope*10 + keywords + conf*0.1` the right shape? Quantify when scope should vs shouldn't dominate. Is a 3-slot reservation a principled fix or a band-aid? What breaks it?
2. **Failure modes.** Construct concrete query + corpus scenarios where this returns bad results (false positives that crowd out, or true positives it drops). Pay attention to: many same-scope priors, multi-path areas, global (empty-scope) priors, very small vs very large corpora, and the `confidence*0.1` term (does it ever matter?).
3. **The idf-over-priors-only choice.** What are the consequences of computing idf only over priors (not over query language)? The stopword list is the patch for it — is that sustainable, or is there a more principled fix?
4. **Stemming + tokenization risks.** Where will `_stem` over- or under-stem and cause wrong matches or missed matches? Is the 3-char floor / no-"er" rule defensible?
5. **The lexical ceiling.** The "href ↔ url ↔ link" miss is a vocabulary-gap problem. Given embeddings are deferred, what lexical techniques (synonym/alias maps, query expansion, field weighting, BM25 instead of raw idf-sum, etc.) would most cheaply close it? Rank them by effort/payoff.
6. **Concrete improvements.** Give specific, minimal changes (formula tweaks, additional signals, re-ranking) with the trade-offs of each.
7. **Test cases.** Propose 6–10 (query, corpus, expected top results) cases that would catch regressions and pin down the intended behavior.

Assume nothing is sacred except: canonical-only serving, lexical-only (no embeddings yet), low latency, and a portable storage layer. Push hard on what's wrong before suggesting what to add.
