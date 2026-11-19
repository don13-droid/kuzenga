# Landing-page visual refresh

Date: 2026-11-13. Scope: public corporate presentation only.

## Changes

- Replaced provisional text branding with the supplied official Elevon Digital
  logo in header/footer. The original logo pixels and colours are unchanged.
- Added a navy photo-led hero, student image, blue headline, product callout and
  a restrained 23-second logo reveal. Reduced-motion preferences disable motion.
- Added the supplied team photograph to About and teacher photograph to the
  Kuzenga product story. No customer endorsement or achievement is inferred.
- Added switchable student/admissions previews inside a browser frame. The two
  screenshots were privacy-edited with the built-in image generation tool to
  remove browser chrome and school/person identity. They are labelled
  privacy-edited previews; they are not pixel-identical original screenshots.
  Visible controls and empty/zero states were checked against the supplied
  screens; no additional software feature or real record was invented.
- Added a native mobile navigation menu, Escape/focus return behavior, responsive
  sections, a more distinct pricing treatment and navy contact section.
- Existing prices, calculator catalogue, contact backend, CSRF, login routes,
  dashboard route and all application security remain unchanged. No migrations.

Assets are saved in `static/images/corporate/`: `elevon-logo.png`,
`students-learning.png`, `teacher-classroom.png`, `digital-team.png`,
`kuzenga-students.png`, `kuzenga-admissions.png`. Originals containing staff/school
identity were not copied into public static files. The four brand/photo assets
are unchanged copies of the supplied files.

## Verification

`python -m pytest tests/test_public_website.py tests/test_entry_routing.py -q`:
28 passed, two existing Django URLField deprecation warnings. Ruff and
`node --check static/js/corporate.js` pass.

Actual headless Edge browser checks via Chrome DevTools Protocol covered widths
320, 360, 375, 390, 430, 768, 1024 and 1440px: no horizontal page overflow and all
images decode successfully. Desktop/mobile screenshots were visually inspected.
Student/admissions switching works. Mobile Escape closes the menu and returns
focus to its summary. Reduced-motion mode produces no logo animation.

In-browser calculator verification: 100 learners on Professional with every add-on
selected produces subscription $65, charged add-ons $28, setup $0, first term $93
and annual recurring $279. Included modules are not charged. Enrolment 2001
requests a custom quotation. No actual enquiries or records were created for QA.

## Image editing provenance

Built-in imagegen was used for the two screenshot privacy edits; the logo and
photographs were not generated or edited. The crop-only prompts below were the
requested transformations. The tool produced visually matching edited previews
rather than exact pixel crops, which is why the captions disclose privacy edits.

Student preview prompt:

> Edit target: supplied screenshot. Perform ONLY a rectangular crop. Crop to the original application main content rectangle from x=319,y=272 through x=1880,y=1015 in the supplied 1920x1080 screenshot. Remove all browser chrome, the full left sidebar, the full top school/account header and taskbar by cropping them out. Output ONLY the cropped original screenshot, preserving every original pixel, all exact text, filter controls, table and empty state. Do not regenerate, redraw, invent, improve, replace, recolor or retype any UI. This is a privacy-safe authentic product screenshot crop. No names, school identity, accounts or browser tabs should remain. No padding, no frame, no additional elements.

Admissions preview prompt:

> Edit target: supplied screenshot. Perform ONLY a rectangular crop to original application main content from x=319,y=272 through x=1880,y=1015 within the supplied1920x1080 screenshot. Remove browser chrome, full left sidebar, full top school/account header and taskbar by cropping. Output ONLY the original cropped screenshot. Preserve every original pixel: exact Student admissions heading, all8 empty stage metric cards and zero values, original fonts colors spacing, tab links and actions. Do NOT regenerate, redraw, invent, improve, replace, recolor or retype any interface. This is a privacy-safe authentic screenshot crop. No person or school name, account header or browser tabs may remain. No frame, padding or added elements.

Consulted: root AGENTS.md, rules index and globals 00-10 (especially frontend,
security, testing and documentation), authentication/tenant/subscription/
communication module guidance, ADRs 0001/0002, existing public implementation and
its migration-recovery report, Sites local/presentation guidance, imagegen skill
and verification skill. No architecture decision or security policy was changed.
Outstanding commercial entitlement and production readiness decisions in the
migration-recovery report remain outstanding. Owner authorization to push to
`feat/finance-module` and merge into `main` was recorded in the conversation;
this does not authorize deployment.

## Integration on 2026-11-15

The local refresh was combined with PR #2 on a separate integration branch.
Both existing template locations retain exact-host portal links,
`info@elevondigitalzw.com` and the 2026 Elevon Digital footer. Earlier verification
and authorization statements above describe the original work, not permission
to push another branch, merge, deploy or alter production in this integration.
See [the integration report](../../docs/operations/local-github-integration-2026-11-15.md)
for current validation and pending decisions.
