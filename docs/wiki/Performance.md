# Performance and load testing

The changes below are in the current source, after published 0.1.1. Measure the
installed revision on your own database and infrastructure before setting a
traffic or latency target.

## How reads are bounded

Recent-comment selection reads ordered SQL batches of 20–100 candidates with
keyset pagination. Site, effective hidden mode, Page publication and Site-root
membership are filtered in SQL. Specific Page models are loaded together;
ordinary inherited restrictions are checked in batches. Aliases retain Wagtail's
native restriction resolution, including restrictions on their source pages.
Custom Page restriction methods also retain native resolution.
Target access, title and validated URL are reused within one selection only.

The discussion widget initially renders 20 roots and up to 20 replies per opened
thread. Reply counts for displayed roots come from one grouped query. Host URLs,
discussion settings and reply-author relations are reused during rendering;
pending-revision eligibility is annotated instead of queried per visible author
comment. Detecting another root window uses a limited existence query rather
than counting all roots. Snapshot navigation and exact published totals remain.

The moderation list displays 30 comments, aggregates status tabs together and
uses Wagtail's searchable Page chooser instead of embedding every discussion
Page in a select. Mail claims load their author and revision together. Cleanup
selects expired unconfirmed comments before taking discussion locks and rechecks
expiry under the lock; fresh messages do not cause discussion writes.

Phrase moderation uses a call-local word trie. Shared prefixes avoid comparing
every rule against every text position. Whole-word matching, normalization,
disabled rules and rejection priority are unchanged; changes to rules take
effect on the next submission.

## Database upgrade

Run migration `0014_reading_indexes` when installing this source revision. It
adds indexes for global publication order, ordered roots, published replies,
active CAPTCHA lookup by Site/session and rate-event cleanup by creation time.
It changes no comment content or state. The migration is reversible.

Index creation needs additional disk space and write work, and the standard
migration can block concurrent writes while building indexes. For a large
existing database, measure migration time on a representative restored copy and
schedule the change accordingly. Keep planner statistics current after bulk
imports; the benchmark collects statistics before inspecting plans. Recollect
static files for the updated admin filter.

## Reproduce the synthetic workload

From a source checkout with the [test dependencies](Example-and-testing.md):

```sh
python tools/benchmark_performance.py --comments 100000 --samples 30 \
  --workers 4 --load-seconds 15 --migration-cycle
```

`--comments` supplies replies in addition to `--roots` (100 by default). Use
`--roots 100000` to exercise many roots rather than a few dense threads.
`--load-seconds` runs that duration for each of two concurrent phases: read-only
fragments and open guest forms. The latter raises synthetic CAPTCHA quotas so
it measures issuance rather than quota rejection. Submission timing uses
different registered authors and still exercises admission, quotas and writes.

The script creates and destroys a uniquely named disposable test database.
SQLite uses a temporary file. For PostgreSQL use a dedicated synthetic cluster,
the `COMMENTAIL_TEST_POSTGRES=1` switch and PGUSER, PGPASSWORD, PGHOST and PGPORT
variables described in [Example and testing](Example-and-testing.md). Never point
test tooling at a production cluster. `--migration-cycle` reverses/reapplies 0014
on synthetic data and checks that all comment field values remain unchanged.

Workloads include recent selection, denied Pages, closed/open threads, moderation
listing, guest forms, parallel reads/submissions, 20,000 phrase rules, up to
100,000 historical or future queued mail jobs and active CAPTCHAs, and 10,000 fresh unconfirmed
comments. An active worker batch delivers 25 messages through Django's in-memory
mail backend; it measures no external SMTP transport. JSON output includes query
counts, median/p95 timings and the actual recent-selection query plan.

## Local reference measurement

Measured on 19 October 2026 on macOS ARM64, Python 3.12.14, Django 5.2.18,
Wagtail 7.4.3, PostgreSQL 18.6 and file-backed SQLite 3.53.1. The initial data
contained 100 roots and 100,000 replies. Each serial measurement used 30 warm
samples; cells below show median / p95 milliseconds, including ORM and Python
work rather than database execution alone. Query counts are the observed maximum
for this fixture, not a contract for custom host integrations.

| Operation | PostgreSQL | SQLite | Queries |
| --- | ---: | ---: | ---: |
| Select 5 recent comments | 2.97 / 3.50 | 1.98 / 2.75 | 6 |
| Render 20 roots | 28.43 / 29.50 | 29.51 / 31.73 | 13 |
| Render one opened thread | 31.61 / 32.79 | 31.99 / 34.21 | 14 |
| Render pending moderation list | 15.65 / 16.19 | 13.86 / 14.34 | 10 |
| Match 20,000 phrase rules | 15.73 / 16.28 | 14.73 / 14.93 | 1 |
| Render an open guest form | 31.06 / 35.96 | 35.45 / 116.65 | 34 |
| Accept a registered submission | 6.42 / 8.06 | 5.56 / 6.15 | 31 |

On PostgreSQL, four concurrent threads completed 4,521 read-only requests in
60.02 seconds (p95 68.63 ms), then 3,782 open-guest requests in 60.03 seconds
(p95 75.30 ms), without request errors. Thirty parallel submissions were all
accepted as distinct comments. The migration reverse/reapply preserved every
comment field on both databases. A separate five-sample PostgreSQL check with
100,000 roots plus 100,000 replies measured 4.54 / 6.99 ms for recent selection
and 65.98 / 70.18 ms for the 20-root fragment; exact totals remain data-dependent.
These local checks are evidence,
not a deployed-site capacity target or a long-duration soak test.

## Costs that still depend on traffic and data

- Exact visible comment/reply totals read matching index entries. Admin search
  across text, names and email and its exact totals can scan the permitted data;
  deeper admin pages use Django's offset pagination.
- Each explicit snapshot window grows the HTML returned to preserve progressive
  navigation. Opening multiple threads fetches a bounded reply window per thread.
- Filling a recent list after many inaccessible targets can require additional
  batches. Alias restrictions and project adapters/callbacks may run additional
  queries; arbitrary host permission logic cannot be presumed cheap or cached
  across visitors.
- Open forms create expiring tickets and CAPTCHA state. Quota decisions retain
  Site-level serialization, and mutations retain discussion-level serialization
  for consistency. SQLite serializes writers; use PostgreSQL for substantial
  concurrent write traffic and measure the real workload.
- Personalized output stays `private, no-store`. Do not put visitor-dependent
  comment HTML in a shared page/fragment/CDN cache. Keep the minute worker running
  so expired form, CAPTCHA and rate-limit records are pruned.

These are server-side synthetic checks through Django's test client and ORM,
with warm templates/caches. They do not include a production HTTP server,
network, browser execution, remote database latency, real SMTP or host callbacks.
They establish regressions and measured behavior, not a universal requests-per-
second guarantee or a long-duration production soak test.

---

[Documentation home](Home.md) · [Deployment](Deployment.md) · [Recent comments](Recent-comments.md)
