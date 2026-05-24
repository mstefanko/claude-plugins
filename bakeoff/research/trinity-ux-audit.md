# Trinity Episcopal Preschool — Homepage UX Audit

**Scope:** Pre-redesign audit of the current homepage. Observation + reporting only — no pixel-level design.
**Audiences:** (1) Prospective families evaluating fit; (2) Current families needing day-to-day practical info.

---

## 1. Audience-first review

### Prospective families (researching, evaluating, considering enrollment)

**What works**
- The Mission section communicates philosophy (play-based, nurturing, well-rounded growth) — this is on-target for a parent's first emotional read.
- The Meet Our Teachers section with named teachers + roles is a strong trust signal — humanizing the staff is exactly what prospects need before they hand over a child.
- The hero subhead establishing "established in 2000 in Moorestown" signals longevity, which is a credibility marker for childcare.

**Where it fails them**
- **No primary call-to-action in the hero.** A prospect reading "Joyful Learning. Every Day." has no next step. "Schedule a Tour" exists in the nav but is not surfaced where decision-momentum is highest (above the fold).
- **The testimonials section is broken.** It still contains Wix/template placeholder copy ("Testimonials are a great way to share positive feedback..."). For a prospect, this reads as either unfinished or unprofessional — a critical trust failure on a site selling childcare.
- **Location is buried.** "207 W Main Street, Moorestown" is footer-only. The stakeholder explicitly named the Main Street Moorestown address as a desirability signal — it should be visible without scrolling to the footer.
- **No proof of the actual school.** The only imagery near the top is wooden toys on a shelf (generic, stock-feeling). Prospects want to see real children, real classrooms, real moments — none of that is above the fold.
- **No program-at-a-glance.** A prospect cannot answer "what ages? what schedule? half-day or full-day?" from the homepage. They have to navigate into sub-pages to triage fit.
- **Contact form has no context.** "Get in Touch" with a generic message field doesn't tell prospects what to expect (response time, who answers, whether this is the same as scheduling a tour).

### Current families (already enrolled)

**What works**
- Footer phone number is present and easy to find once you scroll.
- Instagram/Facebook links in the footer support ongoing engagement.

**Where it fails them**
- **Zero day-to-day operational content on the homepage.** Pick-up / drop-off times, upcoming events, school calendar, closures — none of it is here. A current parent has no reason to land on the homepage; everything they need is hidden in nav sub-pages or not present at all.
- **No tuition payment path.** Stakeholder explicitly named this. It does not exist on the page or in the nav.
- **Upcoming events exist as a nav link only.** A current parent visiting the site for "is there school Friday?" has to click into Events rather than seeing the next 2–3 dates surfaced.
- **The page is built entirely for prospects.** Current families are not addressed at all.

---

## 2. Section-by-section: KEEP / CHANGE / CUT

### Header nav — **CHANGE**
Current nav order (Home | Extended Days | Schedule a Tour | About | Events | Contact) mixes prospect actions (Schedule a Tour, About, Contact) with operational items (Extended Days, Events) without hierarchy. Phone number and address are missing from the header — both stakeholder-priority items. Schedule a Tour should be visually distinguished (button-styled) rather than sitting as a plain link among siblings. Add a top utility strip with address + phone + (if added) tuition login so current families have a fast lane.

### Hero — **CHANGE**
The orange background + headline are fine as identity. What fails: no CTA, no location anchor, no proof imagery. "Joyful Learning. Every Day." is a tagline, not a value prop a parent can act on. The small wooden-toys photo does no work — it's not the school, not the children, not the teachers. The hero must (a) state who/what/where in one glance, (b) carry a primary "Schedule a Tour" CTA, and (c) anchor the Main Street Moorestown location. The "established 2000" line is worth keeping as a trust micro-signal.

### Testimonials carousel — **CHANGE (critical / blocker)**
This is the single most damaging element on the page. Live placeholder text ("Testimonials are a great way to share positive feedback you have received...") attributed to "Claire Brooks, MI" tells every prospect the site is unfinished. For a preschool — a category where parents are explicitly auditing care and attention to detail — this is a credibility wound. **Do not launch the redesign with this in any form.** Either replace with 3–5 real, attributed parent quotes (first name + child's class year is sufficient for privacy) or cut the section entirely until real testimonials are collected. Cutting is better than faking.

### Our Mission — **KEEP (with light edit)**
Content is on-strategy: nurturing, play-based, well-rounded. This serves the "informative + encouraging" stakeholder goal. Keep the cream background as visual breathing room between the louder sections. The only change: shorten if the paragraph runs over 3 lines on desktop — mission statements lose force at length.

### Meet Our Teachers — **KEEP and ELEVATE**
This is the strongest section for the stakeholder's "prop up the teachers" goal. Named, titled, photographed staff is exactly right. Two notes: (1) verify these are real teachers and real names, not template placeholders carried over from the same Wix kit that produced the Claire Brooks testimonial — flag for stakeholder confirmation. (2) Consider moving this section higher in the page order so teachers do more work for prospect trust earlier in the scroll.

### Get in Touch — **CHANGE**
A bare contact form under-serves both audiences. For prospects, the form competes with the (more valuable) Schedule a Tour intent — they're not the same action and shouldn't share a single ambiguous "Submit." Split into two clear paths: tour request (with date/age-of-child fields) vs. general contact. For current families, this section is irrelevant — they already have direct lines to the office. Also: the classroom photo here is the only authentic-feeling image on the page; that imagery deserves more prominent placement elsewhere too.

### Footer — **KEEP (with corrections)**
Footer has the right contents (phone, email, address, social, policies). Two issues to flag for the stakeholder: (1) "trinityepiscopalpreschool.org" in the email field appears to be a domain, not an email address — confirm and correct. (2) The footer is currently doing work the header should share — address and phone should also appear in a header utility strip per the stakeholder's emphasis on the Main Street location.

---

## 3. What's missing (stakeholder asks not currently on the page)

| Stakeholder ask | Current state | Where it should surface |
|---|---|---|
| **Address (Main St. Moorestown emphasis)** | Footer only | Header utility strip + hero anchor line + dedicated "Visit us" block near the top |
| **Pick-up / drop-off times** | Absent | Dedicated "A Day at Trinity" or "Hours & Schedule" block — visible without nav drill-down |
| **Upcoming events** | Nav link only, not on homepage | Homepage block surfacing next 2–3 events with date + title (serves current families primarily, prospects secondarily) |
| **Schedule a Tour CTA** | Nav link only | Primary button in hero + repeated CTA after Mission and after Teachers |
| **Pay tuition** | Absent entirely | Header utility strip "For Current Families" entry point or dedicated current-families band |
| **Photos of actual children / classrooms** | One classroom photo near contact form; rest is generic toys | Hero imagery, Teachers section backgrounds, and a small "Inside Trinity" gallery strip |
| **Day-to-day current-family content** | Absent | A clearly demarcated current-families band (events, hours, tuition link, school calendar) — visually distinct from prospect-facing content |

---

## 4. Recommended homepage structure (re-ordered)

Listed in scroll order. Hierarchy assumption: a prospect's first 3 seconds must answer "what is this place, where, and how do I tour it"; a current family's first 3 seconds must offer a fast lane to events / hours / tuition.

1. **Header utility strip** — Address (Main St. Moorestown), phone, and "Current Families" entry point (tuition + calendar). Serves both audiences instantly.
2. **Main header nav** — Logo, primary nav, visually-distinct "Schedule a Tour" button.
3. **Hero** — Real photograph of children/classroom; headline + one-line value prop; primary CTA "Schedule a Tour"; secondary anchor line with address + ages served.
4. **At-a-glance facts strip** — Ages served, hours (drop-off/pick-up), program length (half/full day), location. One-line each. Serves prospects' triage and current-family hour-checks simultaneously.
5. **Our Mission** — Short, philosophy-forward. Trust-building.
6. **Meet Our Teachers** — Elevated from current position; teachers as primary trust signal; light intro + named/titled grid; button to fuller team page.
7. **Real testimonials** — Only if real quotes are available at launch. Otherwise omit entirely; do not ship placeholder copy.
8. **Inside Trinity (gallery strip)** — Authentic photos of classrooms, art projects, outdoor play. Reinforces the teacher section's claims.
9. **Upcoming Events** — Next 2–3 events with date + title + link to full calendar. Primary current-family value.
10. **For Current Families band** — Visually distinct (different background). Tuition payment link, school calendar link, pick-up/drop-off hours, parent handbook link. This is the page's "second front door."
11. **Schedule a Tour CTA repeat** — Final-scroll CTA for prospects who read the whole page; pairs with a short "What to expect on a tour" line.
12. **Footer** — Existing footer contents with email-vs-domain correction.

---

## 5. Quick wins (highest-impact, lowest-effort)

1. **Remove the placeholder testimonial today.** Replace with 3 real attributed parent quotes if available; otherwise delete the section. Live template boilerplate on a childcare site is a credibility emergency — this is the single highest-priority change.
2. **Add a primary "Schedule a Tour" button in the hero.** Stakeholder asked for an easy way to schedule a tour; right now it lives only in the nav. A button in the hero converts the page's #1 prospect intent immediately.
3. **Add a header utility strip with address + phone + a "Current Families" link.** Surfaces the Main Street Moorestown location (stakeholder priority), gives current families their fast lane, and reduces footer-dependency — all without touching the hero composition.
4. **Add a one-row "At-a-glance" strip below the hero** with ages served, drop-off/pick-up hours, and half/full-day. Closes the prospect triage gap and the current-family hours question in a single component.
5. **Verify the teacher names and the footer email.** "Emily Thompson / Olivia Baker / Michael Davis / Sophia Clark" follow the same generic-name pattern as the "Claire Brooks, MI" placeholder testimonial — confirm with the stakeholder that these are real Trinity staff, not template residue. Same for the "trinityepiscopalpreschool.org" email line, which reads as a domain. Both are content-integrity issues that cost nothing to fix and would be embarrassing to launch with.

---

## Confidence notes

- Findings are based on the structural description and screenshot summary provided, not on a live crawl of the site. The placeholder-testimonial finding and the suspected-template-name finding should both be confirmed with the stakeholder before they're acted on in copy.
- Sentiment-style findings (e.g., "feels generic," "feels stock") are flagged as observations of pattern, not user-tested reactions. Real user testing with 3–5 prospective parents would validate or refute the "hero lacks a clear next step" hypothesis with higher confidence.
- No accessibility audit was performed (no live DOM available). The redesign should include a WCAG AA pass — particularly on the orange hero background's text contrast and the blue testimonial/teachers band.

## Status: COMPLETE
