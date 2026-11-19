# Automated accessibility results

axe-core 4.10.3, WCAG 2.0/2.1 A and AA rules, run 2026-11-19 in Chrome by `tools/a11y/check.mjs`.
1 views × 2 sizes (1280 px, 375 px) × 2 themes = 4 page checks, with reduced motion on.

**4 of 4 page checks have no violations.**

| View | Size | Theme | Violations | Rules passed | Needs a person |
|---|---|---|---|---|---|
| `#/county` | desktop | light | none | 26 | 19 |
| `#/county` | desktop | dark | none | 26 | 19 |
| `#/county` | phone | light | none | 26 | 8 |
| `#/county` | phone | dark | none | 26 | 8 |

Automated rules catch only part of accessibility problems. "Needs a person" counts items axe could not decide
(usually contrast over gradients or images). Keyboard order, visible focus and screen-reader wording are checked by
hand in [MANUAL-CHECKS.md](MANUAL-CHECKS.md).
