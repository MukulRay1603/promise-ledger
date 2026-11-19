# Accessibility checks done by hand

Automated rules ([AXE-SUMMARY.md](AXE-SUMMARY.md)) catch only part of accessibility problems. Deque, which makes
axe-core, reports that automated checks find about 57% of issues by volume, and almost none of focus order, focus
visibility or keyboard use. These were checked by hand in Chrome on 2026-11-18, on the `dec2` build.

## Keyboard

| Check | Where | Result |
|---|---|---|
| Every control is reached with Tab, in reading order | County page: calendar link, timeline marks (oldest end first), then each table row's deal, council record, quote and template-text links | Pass |
| Focus is visible on every stop | Same 22 stops, checked for a visible outline or ring | Pass |
| A skip link goes to the main content | Every page (`Skip to content`, first Tab stop) | Pass |
| Dialogs take focus, close with Escape, and return focus to the control that opened them | Records request letter: focus lands on Subject; Escape closes; focus returns to "Draft a records request" | Pass |
| Folding cards say whether they are open | Documents and Your review: the Show/Hide button has `aria-expanded` and `aria-controls`, and its name includes the card title | Pass |
| Search runs from the keyboard | County search: Enter submits; example questions are buttons | Pass |
| Timeline is usable without seeing it | Each mark is a link in a list, with a full spoken label, e.g. "Bowie Commons Apartments: stated term runs to about 2064 or later" | Pass |

## Screen reader

Not yet done with a real screen reader. Accessible names, roles and live regions were checked in the browser's
accessibility tree (the search status and letter note are `role="status"`; the building picture and timeline have
text alternatives). A pass with NVDA on Windows and VoiceOver on iPhone is planned with the people testing the site.

## Also checked

- Reduced motion: the building, paper trail and timeline animations are off with `prefers-reduced-motion`.
- Larger text: the header's Larger text control scales the whole page.
- Phone width (375 px and 320 px): no sideways scrolling on the County page or a deal page.
