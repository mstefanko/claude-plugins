# Preschool Homepage Competitive Research

Research to inform the redesign of Trinity Episcopal Preschool (Moorestown, NJ). Surveyed peer preschool homepages across four categories: Episcopal/church-affiliated, local South Jersey, regionally-renowned independents, and national chains with mature digital experiences.

> **Methodology note.** WebFetch is blocked in this environment and the context-mode MCP fetcher is not loaded. Homepage elements were catalogued via WebSearch result snippets combined with structured queries about each site's nav, CTAs, contact info, parent portals, calendars, and content sections. Findings reflect what each site surfaces publicly and is indexed by search engines; specific above-the-fold positioning was inferred where direct DOM inspection was not possible.

---

## 1. Sites surveyed

| # | Site | URL | Category | One-line |
|---|---|---|---|---|
| 1 | Trinity Episcopal Preschool (baseline) | trinityepiscopalpreschool.com | Episcopal, church-affiliated | The site being redesigned — Moorestown, NJ. |
| 2 | First Light Early Learning Center | fmcmoorestown.com/preschool | Methodist, church-affiliated | Moorestown's other church preschool — direct local peer. |
| 3 | Haddonfield United Methodist ECC (HUMECC) | haddonfieldumc.org/humecc | Methodist, church-affiliated | South Jersey church preschool; Squarespace-based; PDF-heavy. |
| 4 | Moorestown Friends School — Beginnings | mfriends.org/moorestown-preschool | Independent K-12 (Quaker), preschool track | Premium-positioned, in Trinity's town. |
| 5 | Haddonfield Friends School | hfsfriends.org | Independent K-8 (Quaker) | Polished small-school site, nearby South Jersey. |
| 6 | The Acorn School (NYC) | acornschoolnyc.com | Independent urban preschool | Tight, application-driven IA; tour-gated by app. |
| 7 | Bing Nursery School (Stanford) | bingschool.stanford.edu | University-affiliated, research-oriented | Mission-forward; deep program detail. |
| 8 | St. Paul's Preschool (Cary, NC) | stpaulscary.org/preschool | Episcopal, church-affiliated | Episcopal peer of similar scale to Trinity. |
| 9 | The Goddard School | goddardschool.com | National chain | Best-in-class enrollment funnel + virtual tour. |
| 10 | Bright Horizons | brighthorizons.com | National chain | Strongest dual-audience IA (prospective vs. current). |
| 11 | Lightbridge Academy | lightbridgeacademy.com | National chain | Strongest current-family tech (ParentView cams, app, portal). |
| 12 | Cadence Academy Preschool — Cherry Hill | cadence-education.com/locations/nj/cherry-hill | National chain, local NJ site | Local peer of a national chain. |

---

## 2. Homepage element matrix

Legend: `Y` = present on homepage, `~` = present but weak/buried, `N` = absent, `?` = could not confirm via search snippets. **Trinity column reflects the audit baseline given in the brief.**

| Element | Trinity | First Light | HUMECC | MFS Beginnings | HFS | Acorn NYC | Bing Stanford | St Paul's Cary | Goddard | Bright Horizons | Lightbridge | Cadence CH |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Hero CTA (Tour/Apply/Enroll) | **N** | Y | ~ | Y | Y | Y (Apply) | Y (Apply) | Y (Tour) | Y (Tour + Enroll) | Y (Find a Center + Enroll) | Y (Tour) | Y (Tour) |
| Address above the fold | ~ footer only | Y | Y | ~ | ~ | Y | Y | Y | Y (via locator) | Y (via locator) | Y | Y |
| Phone above the fold | N | Y | Y | ~ | ~ | Y | Y | Y | Y | Y | Y | Y |
| Hours / drop-off & pick-up times | **N** | ~ (Classes pg) | ~ (PDF) | ~ | ~ | N | Y (session lengths) | ~ | ~ | ~ | ~ | Y (7am–5:30pm) |
| Upcoming events / calendar | **N** (Events nav but no homepage block) | Y (calendar linked) | Y (PDF calendar) | Y (news+events block) | Y | Y (tour dates) | ~ | ~ | ~ | ~ | ~ | ~ |
| Tuition info or "Pay tuition" link | **N** | Y (Classes & Tuition pg) | Y (PDF) | ~ | ~ | Y (app fee) | Y (program offerings & tuition) | Y | Y (dedicated /tuition-benefits) | Y (custom quote flow) | Y (registration fee + monthly) | ~ |
| Programs / age groups breakdown | ~ (Programs nav, no homepage cards) | Y (2.5/3/4/Dev-K) | Y (3–6, TK, K-Enrich) | Y (Preschool/Pre-K/K) | Y | Y (2s/3s/4s) | Y (2yr + nursery) | Y | Y (Infant–Pre-K) | Y (Infant–Pre-K) | Y (Infant–Pre-K) | Y |
| Teacher / staff bios | Y (4 photos + titles) | ~ | ~ | Y | Y | Y (meet director) | Y | Y | ~ | ~ | ~ | ~ |
| Photos of actual children / classrooms | Y (small) | Y | Y | Y (strong) | Y (strong) | Y | Y | Y | Y (and video) | Y | Y (live ParentView) | Y |
| Testimonials / parent quotes | Y (carousel — placeholder) | ~ | N | Y | Y | Y | ~ | Y | Y | Y | Y | Y |
| Mission / philosophy statement | Y | Y | Y | Y | Y | Y | Y (strong, lab-school framing) | Y | Y | Y | Y | Y |
| Accreditation / awards / trust badges | N | ~ | N | Y (NAIS, FCIS) | Y (FCIS) | ~ | Y (Stanford halo) | ~ | Y (NAEYC) | Y (NAEYC) | Y (Cognia, NJ DOE) | Y |
| Religious affiliation / values | Y (Christian setting) | Y (Christian) | Y (Christian) | Y (Quaker) | Y (Quaker) | N | N | Y (Episcopal) | N | N | N | N |
| Parent portal / login link | **N** | N | N | ~ | ~ | N | N | N | Y (MyGoddard) | Y (Family Information Center) | Y (Lightbridge Journey app) | Y (Cadence Connect) |
| Newsletter signup | N | N | N | ~ | ~ | N | N | N | ~ | Y | Y | ~ |
| Social media links | Y (footer) | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| Virtual tour or video | N | N | N | ~ | ~ | N | N | N | **Y** (11-min virtual tour + 10s hero loop) | Y | Y (ParentView live cams) | Y |
| FAQ / "What to expect" | N | ~ | ~ (PDF) | Y | Y | Y | Y (Enrollment FAQs) | Y | Y (/frequently-asked-questions) | Y | Y | Y |
| Safety / health policies | N | N | N | ~ | ~ | N | ~ | ~ | Y | Y | Y (security system) | Y |
| Map embed | N | ~ (address) | ~ (address) | Y | Y | Y | Y | Y | Y | Y | Y | Y |

---

## 3. Patterns observed

### Table stakes (present on ~9+ of 11 peer sites)

1. **A primary hero CTA button** — most often "Schedule a Tour," sometimes "Apply" or "Enroll." Trinity is the outlier with no hero CTA.
2. **Phone + address visible in the header or hero**, not just the footer.
3. **Age-group / program cards** on the homepage (typically a 3- or 4-card row: 2s / 3s / 4s / Pre-K).
4. **Photos of actual children and classrooms** (not stock). Universal.
5. **Mission/philosophy paragraph** at mid-page. Universal.
6. **Footer with phone, address, hours, social.** Universal.
7. **A "Programs," "Admissions," and "About" top-level nav** — almost identical IA across the board.
8. **Map embed** on either homepage or contact page. Universal among the more polished sites.
9. **A dedicated tuition page** (even if no homepage prices). Trinity has none.

### Differentiators (present on only the best 3-4 sites — high-value when present)

1. **Virtual tour video on the homepage.** Goddard's 10-second hero loop + 11-minute virtual tour is the strongest example. Lightbridge's ParentView live cams are an even stronger trust signal.
2. **Dual-audience landing strips** — Bright Horizons and Goddard prominently split "I'm a new family" (find a center / schedule tour) from "I'm a current family" (parent portal login, pay tuition, app download).
3. **Parent portal / app link in the header** — chain sites do this. Church preschools and independents largely do not. This is where Trinity can leapfrog its direct local peers.
4. **Events / news block on the homepage** (rotating cards with dates). MFS and HFS do this well.
5. **Trust badges row** — accreditations (NAEYC, NAIS), licensing, ratings. Chains do this aggressively. Church preschools rarely.
6. **Inline "Schedule a Tour" form** (5-7 fields max) below the hero, so prospective families can act without leaving the homepage.
7. **Clear hours band** — Cadence Cherry Hill shows "Mon–Fri 7:00 am – 5:30 pm" prominently. Most church preschools bury hours in PDFs.

### Dual-audience IA — how peers handle it

- **National chains (Goddard, Bright Horizons, Lightbridge):** persistent header strip with "Schedule Tour" + "Parent Portal Login" + sometimes "Pay Tuition." Hero serves prospective; a secondary band below the hero serves current families.
- **Independents (MFS, HFS, Acorn, Bing):** less aggressive — heavy on prospective-family content; current-family functions live behind a faculty/staff/parent portal link in the header or footer.
- **Church preschools (First Light, HUMECC, St Paul's Cary, Trinity today):** weakest. Most assume current families will email or use PDFs for everything. **This is the gap most worth closing.**

---

## 4. Best-in-class examples worth borrowing

### 4a. The Goddard School — best enrollment funnel
- Hero with a looping 10-second video of children at play, then a single contrasting CTA ("Schedule a Tour").
- An always-visible "Virtual Tour" link within the first viewport.
- Dedicated `/tuition-benefits` and `/frequently-asked-questions` pages linked from the homepage; FAQ answers the top objections (tour, enrollment timing, cost ranges) directly.
- **Why it matters for Trinity:** Trinity's stakeholder asked for "easy tour scheduling" — Goddard's pattern of hero-button + virtual-tour-link + below-the-fold inquiry form is the proven shape.

### 4b. Bright Horizons — best dual-audience IA
- Top-of-page split: a center locator for prospective families, plus a clearly labelled "Family Information Center" link for current families.
- "Find a Center" then "Tuitions and Openings" form — a structured, low-friction inquiry flow.
- **Why it matters for Trinity:** Trinity has two audiences but only serves prospective ones today. Borrow the persistent dual-strip: "Prospective families → Schedule a Tour" on one side, "Current families → Pay Tuition / Calendar / Drop-off Info" on the other.

### 4c. Lightbridge Academy — best current-family signal
- Live ParentView cameras and a parent app (Lightbridge Journey) get front-and-center treatment on the homepage as both a current-family tool and a prospective-family trust signal.
- **Why it matters for Trinity:** Even without live cams, Trinity can borrow the *idea* — a single colored band that says "Already a Trinity family? Pay tuition · See the calendar · Drop-off & pick-up times." That alone closes the biggest peer gap.

### 4d. Moorestown Friends School — best premium-feel reference (also Trinity's town)
- Strong children-in-action photography, mission-forward copy, news+events block, accreditation badges.
- Stakeholder is competing with MFS on the same street for the same families — Trinity should at minimum match its photographic and editorial polish.

---

## 5. Gap analysis vs. Trinity

### Keep (Trinity has it and it's standard)
- Mission paragraph mid-page.
- Teacher photos + names + titles (Trinity does this — most peers don't go this deep, this is a small positive differentiator).
- Religious affiliation framing ("Christian setting") — appropriate for the audience.
- Social media in footer.

### Cut or fix
- **Testimonial carousel with placeholder text.** Either populate with real parent quotes or remove. Placeholder copy is actively damaging credibility versus polished peer sites.
- **Hero with no CTA button.** The headline "Joyful Learning. Every Day." is fine, but it needs a button.

### Add — peer-universal, currently missing from Trinity (priority order)

1. **Hero CTA button: "Schedule a Tour"** (links to scheduling form or calendar) — *every peer site has this except Trinity.*
2. **Address + phone in the header**, not just the footer. Stakeholder explicitly asked for address emphasis.
3. **Programs / age-groups row** on the homepage (3 or 4 cards: 2s / 3s / 4s / Extended Day) instead of hiding them behind a nav link.
4. **Tuition page + "Pay Tuition" link** in the header (stakeholder ask + peer-universal).
5. **Hours band with drop-off and pick-up times** — colored strip directly under the hero. Stakeholder ask.
6. **Upcoming Events block** on the homepage (3 event cards with dates) — stakeholder ask; MFS / HFS / First Light all do this.
7. **Map embed** on the homepage or in the footer (Trinity has none).
8. **Real parent testimonials** (replace placeholder carousel).
9. **FAQ / "What to expect on your first visit"** page linked from the homepage.

### Consider — differentiators worth evaluating

- **Virtual tour video or photo gallery lightbox.** Goddard-style. Higher production cost but high impact.
- **Parent portal / "current families" strip** below the hero. Strongest dual-audience pattern; closes the gap that *no* church preschool in this peer set has closed.
- **Newsletter signup** in the footer (low cost, modest value).
- **Accreditation / "Established 2000" trust badges** in a small row above the footer.

---

## 6. Specific recommendations for Trinity

These are concrete, peer-backed patterns to bring to design.

1. **Hero gets a button.** Keep "Joyful Learning. Every Day." Add a primary button: "Schedule a Tour" (links to the existing Schedule a Tour page). Add a secondary text link beside it: "View Programs."
   - *Pattern source:* Goddard, Bright Horizons, Acorn, St Paul's Cary — all do this.

2. **A current-families band directly under the hero** — colored strip, 3 inline items:
   `Drop-off 8:45 am · Pick-up 12:15 pm · [Pay Tuition →]`
   - This is the single biggest gap-closer. No church preschool in the peer set does this. Trinity can be the first.
   - *Pattern source:* Lightbridge / Bright Horizons split, adapted to a small church preschool.

3. **Programs row — 3 or 4 cards** with photo, age, schedule, and "Learn more" link. Replace the navigation-only treatment.
   - *Pattern source:* universal among peers.

4. **Events block — 3 cards with date chips.** Use the existing Events nav page as the data source; surface the next 3 events on the homepage.
   - *Pattern source:* MFS, HFS, First Light.

5. **Address + phone in the header, not just the footer.** "207 W Main Street, Moorestown, NJ · 856-235-1840" as a small bar above the main nav.
   - *Pattern source:* most peer sites and stakeholder explicit ask.

6. **Replace placeholder testimonials with 3 real parent quotes** (name + child's age + photo if available). Don't ship a carousel with lorem-ipsum-style placeholder.

7. **Teachers section keeps its current treatment** — Trinity is actually ahead of most peers here. Consider adding a "Meet the rest of our team" link to a fuller staff page.

8. **Map embed in the footer** alongside address. Cheap, peer-universal, supports the stakeholder's address-emphasis ask.

9. **Add a small trust row above the footer**: "Serving Moorestown families since 2000 · A ministry of Trinity Episcopal Church · NJ-licensed."
   - *Pattern source:* chains do badges; for a church preschool, plain-text trust signals fit the tone better.

10. **Add an FAQ page** linked from the homepage. Top questions to answer: tour scheduling, programs and ages, tuition ranges, what to bring on the first day, religious practice expectations.

---

## Sources

- [Trinity Episcopal Preschool](https://www.trinityepiscopalpreschool.com/)
- [First Light Early Learning Center](https://fmcmoorestown.com/preschool/)
- [Haddonfield UMC ECC](https://www.haddonfieldumc.org/humecc)
- [Moorestown Friends — Beginnings](https://www.mfriends.org/moorestown-preschool/)
- [Haddonfield Friends School](https://hfsfriends.org/)
- [The Acorn School NYC](https://www.acornschoolnyc.com/)
- [Bing Nursery School (Stanford)](https://bingschool.stanford.edu/)
- [St. Paul's Preschool, Cary NC](https://stpaulscary.org/preschool/)
- [The Goddard School](https://www.goddardschool.com/)
- [Bright Horizons](https://www.brighthorizons.com/)
- [Lightbridge Academy](https://lightbridgeacademy.com/)
- [Cadence Academy Cherry Hill](https://www.cadence-education.com/locations/nj/cherry-hill/567/)
