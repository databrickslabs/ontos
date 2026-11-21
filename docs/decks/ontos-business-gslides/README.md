# Ontos · business catalog deck (Google Slides)

27 native, editable slides on the Databricks corporate template, written for data governance practitioners:
Ontos as the business catalog on top of Databricks, the three-branch operating model (governance / management / audit),
data mesh (personas, products & contracts, value chain, lifecycle, marketplace), ontologies, access policies and authority.
Sources: `../ontos-pitch`, `../access-policies-odrl`, `../arf`. No code, roadmap or protocol references on the slides.

Deck: https://docs.google.com/presentation/d/1FWrnrdylyl4DS8ihc8EoT-eux_kwArz4M48WXAmWYto/edit (id in `pid.txt`)

```bash
python3 step1.py        # once: copy the template, create the 24-slide layout skeleton, write pid.txt
python3 build.py        # redraw all slides  (python3 build.py 4 12  redraws only slides 4 and 12)
python3 notes.py        # five-part speaker notes on every slide
```

Demo numbers are quoted from the source decks' computed data: the access verdict grid and grant counts from
`access-policies-odrl` (VIZ-DATA), the authority divergence values from `arf/data/arf_scenarios.json` (stored `dna_rows`).
