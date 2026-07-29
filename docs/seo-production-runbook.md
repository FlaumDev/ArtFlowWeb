# ArtFlow production SEO runbook

This is the single operational source for technical SEO, Google Search Console,
Yandex Webmaster, snippet review, and competition-page lifecycle decisions. It
does not promise rankings, traffic, indexing, or rich results.

## Scope and safety

- Canonical origin: https://artflowfest.com.
- The verifier only permits bounded GET and HEAD requests.
- Links found in HTML are inspected but external targets are never fetched.
- No cookies, Authorization, environment values, or DSN are sent or reported.
- The verifier does not connect to PostgreSQL directly and never changes data.
- It never sends a Telegram command or opens a Telegram application flow.
- Reports belong in the Git-ignored dist/ directory.
- A Railway hostname is checked only when the owner supplies the exact hostname.

## Before a production audit

1. Confirm the deployment has completed and /health returns status ok.
2. Select one currently published ID from sitemap.xml or the catalog.
3. Optionally select a known unpublished ID to verify its public 404 state.
4. Obtain the exact Railway public hostname from the owner if it must be tested.
5. Never infer the Railway hostname from a CI example.
6. Run only against the explicit HTTPS production origin.

Base command:

    python -m scripts.verify_production https://artflowfest.com --seo-audit --competition-id PUBLISHED_ID --report dist/seo-production-report.json --markdown-report dist/seo-production-report.md

Extended command:

    python -m scripts.verify_production https://artflowfest.com --seo-audit --competition-id PUBLISHED_ID --unpublished-competition-id UNPUBLISHED_ID --railway-hostname CONFIRMED_RAILWAY_HOST --report dist/seo-production-report.json --markdown-report dist/seo-production-report.md

The default hard limit is 80 HTTP requests, the timeout is 10 seconds, and the
transport follows no more than two redirects. ArtFlow should not need a higher
limit.

## Status model

| Status | Meaning | Owner action |
|---|---|---|
| PASS | The check ran and the condition is satisfied | Keep the report as a baseline |
| WARNING | A risk or deliberate policy needs review | Record the decision |
| FAIL | A confirmed technical defect exists | Fix before broad reindex requests |
| NOT CHECKED | Owner access or a known test state is missing | Complete the named manual check |

The command exits non-zero when any FAIL exists. WARNING and NOT CHECKED are
never promoted to PASS.

## Automated coverage

SEO mode checks:

- HTTPS apex, HTTP, www, and an explicitly supplied Railway hostname;
- redirect count and final canonical URL;
- robots.txt, sitemap.xml, MIME type, and nosniff;
- sitemap uniqueness, origin, query/fragment absence, and future lastmod;
- HTTP status, title, description, H1, robots, canonical, Open Graph, Twitter;
- JSON-LD parsing and unsupported or invented Event fields;
- favicon response type and body;
- query and trailing-slash canonical behavior;
- real 404 and soft-404 indicators;
- internal links, fragments, broken targets, and sitemap orphans;
- Telegram competition_{id} deep links without opening Telegram;
- normal browser, Googlebot, and YandexBot response parity;
- snippet QA lengths and schema types;
- observable lifecycle state of published competition pages.

It intentionally does not trigger production 500/503 responses, determine a
search engine's index, or distinguish deleted from unpublished data without a
known ID.

## Domain policy

The confirmed current policy is apex-only:

- https://artflowfest.com/ returns 200 without a redirect;
- http://artflowfest.com/ redirects once to the HTTPS apex;
- www.artflowfest.com currently has no DNS record;
- missing www is acceptable while this is an explicit owner decision;
- if www is added later, every HTTP/HTTPS variant must reach the canonical apex
  in one redirect;
- the Railway hostname must be inaccessible or redirect once to canonical;
- serving the same indexable HTML with 200 on Railway creates duplicate content.

## Google Search Console

### Initial setup

1. Add the Domain property artflowfest.com and verify through DNS.
2. Do not place a verification token in Python, JavaScript, or public JSON.
3. Submit https://artflowfest.com/sitemap.xml.
4. Use URL Inspection for:
   - the home page;
   - /competitions;
   - one published competition;
   - /about;
   - /how-to-participate;
   - /faq.
5. Compare Google-selected canonical with the declared canonical.
6. Request indexing only after the production report has no FAIL.

### Recurring review

- Page indexing: inspect new soft 404, server error, duplicate, and excluded
  reasons.
- Sitemaps: require Success and compare discovered pages with the public sitemap.
- URL Inspection: verify crawl allowed, indexing allowed, rendered HTML, and
  canonical.
- Enhancements: review Event errors only where Event is truthfully emitted.
- HTTPS and Core Web Vitals: use measured panel data, not assumed scores.
- Performance: review impressions, clicks, CTR, and average position by page and
  query; short fluctuations are not automatically a technical defect.

## Yandex Webmaster

### Initial setup

1. Add https://artflowfest.com and verify ownership through DNS.
2. Submit https://artflowfest.com/sitemap.xml.
3. Run the robots.txt analysis and inspect representative URLs.
4. Use page recrawl for home, catalog, and one current competition only after a
   successful technical audit.
5. Review indexed and excluded pages.
6. Set a geographic region only when the project's actual scope supports it.

### Recurring review

- site diagnostics and critical errors;
- changes in downloaded, indexed, and excluded page counts;
- 404, soft 404, redirect, and noindex reasons;
- the title and description actually selected for snippets;
- representation of current published competitions;
- absence of Railway and localhost URLs in diagnostics.

## First eight weeks

| Period | Google Search Console | Yandex Webmaster | Local work |
|---|---|---|---|
| Day 0 | Verify property, submit sitemap, inspect six URLs | Verify site, submit sitemap, inspect robots | Run SEO audit and retain JSON/Markdown |
| Day 2-3 | Check first crawl and selected canonical | Check sitemap processing and diagnostics | Fix only confirmed FAIL |
| Week 1 | Review Page indexing and URL Inspection | Review indexed and excluded pages | Repeat audit after each deploy |
| Week 2 | Review snippets and initial queries | Review snippets and recrawl | Improve factual titles/descriptions only |
| Week 3-4 | Review Event errors and CWV if data exists | Review crawl diagnostics | Compare performance baseline |
| Week 5-6 | Review low CTR only with enough impressions | Review index changes | Edit only verified weak content |
| Week 7-8 | Compare sitemap and indexed URL counts | Compare downloaded and excluded URLs | Record monthly baseline and next owner |

## Competition page lifecycle

The current application uses is_published as the only public visibility source.
application_deadline changes registration state in APP_TIMEZONE but does not
unpublish the page. An elapsed event_date also does not redirect or unpublish.

| State | Current HTTP/SEO behavior | Owner decision |
|---|---|---|
| Published, future event | 200, index, canonical, Event when facts suffice | Keep published |
| Deadline passed, event ahead | 200, closed CTA, index | Keep through the event |
| Event date passed, still published | 200 and index remain | Deliberately retain as history or unpublish |
| is_published=false | 404, noindex, no canonical | Confirm removal from sitemap/catalog after TTL |
| Deleted record | 404, noindex, no canonical | Add no redirect unless a truly equivalent replacement exists |
| Date/place/description incomplete | Event is omitted when required facts are absent | Add real facts; never invent schema |
| Poster absent | ArtFlow fallback is used | Verify alt text, OG image, and MIME type |
| Minimal useful content absent | A thin 200 page is risky | Improve with verified facts or unpublish |

Past events are not automatically redirected to the catalog because that would
discard the event URL and is not always a relevant permanent replacement.

## Snippet QA

The report lists URL, title/description lengths, H1, canonical, Open Graph, and
schema types. A length warning calls for human review, not automatic truncation.

Confirm:

- every title is unique and page-specific;
- descriptions are factual and not repetitive;
- there is exactly one relevant H1;
- canonical and og:url are identical;
- og:image is an available HTTPS image;
- Event.name matches the visible H1;
- Event organizer remains absent until every row has a verified organizer source;
- Google or Yandex may rewrite a snippet despite correct metadata.

## Common mistakes

- submitting the sitemap before FAIL findings are fixed;
- treating a site: search as an exact index count;
- requesting recrawl for unchanged URLs in bulk;
- using a temporary Removal tool instead of correct 404/noindex behavior;
- placing www or Railway URLs in canonical;
- adding Event organizer, Offer, rating, or review without a source;
- changing a past competition URL only to label it as archived;
- allowing redirect chains longer than one hop;
- treating a WARNING as proof without manual review;
- treating NOT CHECKED as a successful verification.

## After every deployment

Use docs/post-deploy-checklist.md. The owner stores reports outside Git together
with deployment date, commit SHA, audited competition ID, and manual panel results.