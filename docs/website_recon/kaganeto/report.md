# Website Recon Report: kagane.to

Issue: **Websites Request - Kagane.to** (Closes #22)

Date (UTC): 2026-07-18
Website key: `kaganeto`
Base URL: `https://kagane.to`

## Recon outcome summary

`kagane.to` is currently **not DNS-resolvable** from this environment (`Could not resolve host` / `No address associated with hostname`). Because the target host cannot be resolved, live HTML/JSON extraction and selector verification could not be completed.

Evidence:

- `curl https://kagane.to/` → `curl: (6) Could not resolve host: kagane.to`
- `curl https://www.kagane.to/` → `curl: (6) Could not resolve host: www.kagane.to`
- `web_fetch https://kagane.to/` → `failed to lookup address information: No address associated with hostname`
- `getent hosts kagane.to` and `getent hosts www.kagane.to` returned no records.

---

## 1) CMS family

- Verdict: **UNVERIFIED**
- Reason: no retrievable homepage or series page HTML due DNS failure.

## 2) API availability (metadata / chapters / search / front page)

- `/wp-json/`: **UNVERIFIED** (host unresolved)
- `/api/` style endpoints: **UNVERIFIED**
- Search endpoint: **UNVERIFIED**
- Latest updates endpoint: **UNVERIFIED**

Recommended schema mode: **UNVERIFIED** until host is reachable.

## 3) URL identity

No live series/chapter URLs could be collected from the target domain.

### URL round-trip table

| Sample URL | Regex extract | Rebuilt URL | Match |
|---|---|---|---|
| UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |

## 4) Series page selectors

All required selectors are **UNVERIFIED** because no series page HTML could be fetched.

## 5) Premium / locked chapters

- Presence of locked chapters: **UNVERIFIED**
- Locked-row selector: **UNVERIFIED**
- Rebuild rule requirement: **UNVERIFIED**

## 6) Search

- Search transport/request shape: **UNVERIFIED**
- Result selectors (title/url/cover): **UNVERIFIED**
- Live query proof: **UNVERIFIED**

## 7) Front page / latest updates

- Latest-only strategy: **UNVERIFIED**
- Latest update selectors: **UNVERIFIED**

## 8) Content filters

- Adult/mature gate cookie/localStorage: **UNVERIFIED**

## 9) Cover hotlinking

- Direct cover request behavior: **UNVERIFIED**
- Referer requirement: **UNVERIFIED**

## 10) Test-case candidate

Could not identify a completed series candidate from the live website due host resolution failure.

- Candidate: **UNVERIFIED**

## Closest reference schema

- **UNVERIFIED** (no retrievable assets to classify CMS family)

## Next-step recommendation for schema author

1. Re-run recon from an environment where `kagane.to` resolves.
2. If DNS remains unresolved globally, the domain may be inactive; request a replacement domain from requester.
3. Once reachable, complete selector/API verification and replace all `UNVERIFIED` placeholders.

=== WEBSITE RECON ===
website_key: kaganeto
domain: kagane.to
cms_family: custom
closest_reference_schema: UNVERIFIED
recommended_schema_mode: dom
anti_bot: other — DNS resolution failure (host unreachable)
api_sections: metadata=dom chapters=dom search=dom front_page=dom
premium_chapters: UNVERIFIED
content_filter: UNVERIFIED
cover_policy: UNVERIFIED
latest_strategy: UNVERIFIED
test_case_title: UNVERIFIED
test_case_url: UNVERIFIED
test_case_status: UNVERIFIED
chapter_count: 0
first_chapter_url: UNVERIFIED
last_chapter_url: UNVERIFIED
search_query: UNVERIFIED
unverified_items: cms family, metadata API, chapters API, search API, front page API, url regex, chapter url regex, URL templates, series selectors, premium selectors, search selectors, latest selectors, content filter, cover policy, test case
notes: Target domain was not DNS-resolvable during recon; all extraction fields require re-validation in a reachable environment.
=== END RECON ===
