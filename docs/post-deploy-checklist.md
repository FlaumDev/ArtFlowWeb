# ArtFlow post-deploy checklist

The owner completes this checklist after every production deployment. It does not
perform deployment, modify PostgreSQL, or submit Telegram applications.

## First 15 minutes

- [ ] Record deployment date, commit SHA, and owner.
- [ ] https://artflowfest.com/ returns HTTP 200.
- [ ] http://artflowfest.com/ redirects exactly once to HTTPS apex.
- [ ] /health returns only status ok.
- [ ] /health/db exposes no exception, DSN, or password.
- [ ] /docs, /redoc, and /openapi.json return 404.
- [ ] A random URL returns real HTML 404, noindex, and no canonical.
- [ ] /competitions/not-an-id returns 404, not 422.
- [ ] robots.txt names the canonical sitemap.
- [ ] sitemap.xml is XML and contains no Railway, localhost, query, or fragment.
- [ ] HSTS, CSP, nosniff, Referrer-Policy, X-Frame-Options, and
      Permissions-Policy match the security policy.

Run:

    python -m scripts.check_production_settings
    python -m scripts.verify_production https://artflowfest.com --competition-id PUBLISHED_OPEN_ID
    python -m scripts.verify_production https://artflowfest.com --seo-audit --competition-id PUBLISHED_ID --report dist/seo-production-report.json --markdown-report dist/seo-production-report.md

## Review the SEO report

- [ ] No FAIL remains.
- [ ] Every WARNING has a recorded decision.
- [ ] Every NOT CHECKED has an owner or a documented limitation.
- [ ] Canonical HTTPS is 200 without redirect.
- [ ] HTTP apex redirects once.
- [ ] www matches the approved apex-only policy.
- [ ] Railway is checked when the owner supplies its exact hostname.
- [ ] Every sitemap URL is 200 and self-canonical.
- [ ] No soft 404, broken fragment, or sitemap orphan exists.
- [ ] Telegram deep link contains the page's competition_{id}.
- [ ] Browser, Googlebot, and YandexBot receive equivalent indexable HTML.

## Manual page review

Check desktop and mobile for:

- [ ] home;
- [ ] competition catalog;
- [ ] one published competition;
- [ ] FAQ;
- [ ] About;
- [ ] How to participate;
- [ ] 404;
- [ ] controlled 503 only in local or staging tests.

On the published competition:

- [ ] title, description, H1, and facts describe the same record;
- [ ] real poster or fallback renders;
- [ ] rules link is safe;
- [ ] CTA is active only while registration is open;
- [ ] Telegram ID matches the competition URL;
- [ ] #event-help exists only with the matching section;
- [ ] Event has no organizer or other unsupported fields.

## Performance

- [ ] Structural performance audit passes.
- [ ] HTML and CSS are compressed exactly once.
- [ ] Versioned CSS/JS use immutable cache.
- [ ] Images are not gzip-compressed again.
- [ ] No new external blocking request appears.
- [ ] PageSpeed Insights is run when available and the real report is retained.

Run:

    python -m scripts.performance_audit structural-checks --report dist/performance.json

## Webmaster panels

- [ ] Google Search Console shows no new critical Page indexing defect.
- [ ] Yandex Webmaster shows no new critical diagnostic.
- [ ] Both panels accept the sitemap.
- [ ] URL Inspection is run for new or materially changed URLs.
- [ ] Recrawl is requested only for changed pages.

Detailed setup and the first-eight-weeks schedule:
docs/seo-production-runbook.md.

## Rollback criteria

Consider rollback or an immediate hotfix if:

- canonical or og:url leaves artflowfest.com;
- the sitemap contains many 404/5xx responses;
- home or catalog returns 5xx;
- production docs become available;
- Telegram loses competition_{id};
- a traceback, DSN, or secret is exposed;
- Googlebot/YandexBot receives different indexable content;
- a redirect loop or chain longer than one hop appears.

A snippet-length WARNING, intentionally absent www DNS, or unavailable webmaster
data immediately after deployment is not by itself a rollback reason.

## Completion

- [ ] Store JSON and Markdown reports outside Git.
- [ ] Record Search Console and Yandex Webmaster manual results.
- [ ] Assign an owner and due date to every remaining action.
- [ ] Confirm the audit script made no commit, push, tag, release, or deploy.