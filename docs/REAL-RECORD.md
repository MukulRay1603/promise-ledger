# A real public record, end to end

This is a case study. We ran Promise Ledger on two real, publicly posted records about one subsidized housing deal and checked every result by hand.

**The app's sample deals are still fictional.** Nothing from this case study is loaded into the app or the demo. The PDFs are not in this repository. Download them from the county's site with the links below.

Run date: November 10, 2026. Code: branch `dec2-real`.

## The record

**Deal:** Annapolis Junction, a planned 623-home rental development at 10010 Junction Drive, Howard County, Maryland. The developer is Midway 32, LLC. The County agreed to a payment in lieu of taxes (PILOT) in exchange for 95 affordable homes.

| # | Record | From | Date | Pages | Source |
|---|---|---|---|---|---|
| 1 | Testimony on the PILOT resolution, with the fiscal memo to the Housing and Community Development Board | Howard County Department of Housing and Community Development | March 21, 2026 (memo dated March 9, revised March 16) | 5 | <https://apps.howardcountymd.gov/olis/api/Documents/LegislationDocument/43929> |
| 2 | Council Resolution 51-2026, as enacted, with the PILOT agreement attached as Exhibit 1 | County Council of Howard County | Adopted May 4, 2026. Approved by the County Executive May 14, 2026 | 21 | <https://apps.howardcountymd.gov/olis/api/Documents/LegislationDocument/45240> |

Both files come from the County's own legislative site. Record 1 has a normal text layer. Record 2 is a scan with a text layer added by OCR, and its resolution pages have a line number on every line.

The County Auditor's fiscal analysis for the same resolution is also posted (<https://apps.howardcountymd.gov/olis/api/Documents/LegislationDocument/44953>). We did not run it.

### Why this one

- It is a real tax break tied to affordable-housing commitments: 95 homes at three income levels.
- It has both ends of the path: the staff case for the deal, and the resolution the Council adopted with the agreement attached.
- The two records do not fully agree. The testimony says the homes are restricted for 30 years. The attached agreement ties the restriction to a 20-year term. This is the kind of gap the receipt exists to show.
- It is hard in ordinary ways: a scan, OCR mistakes, line numbers, a blank signature page, handwritten dates, and local words for income levels.
- It names officials and companies only. There are no details about residents.

The agreement in Record 2 is the form the Council approved. Its signature blocks are blank. We did not find the executed agreement posted.

## How we ran it

We used the app's own code path: a temporary local store, then `deals.create_deal`, `deals.add_document` and `deals.process_document`, then `deals.deal_review`. This is what an upload in the app does. Record 1 was typed "Staff report" and Record 2 "Resolution". No dates were entered.

The primary model (`gemini-3.5-flash`) returned 429 (out of quota) on every try, so the app fell back to `gemini-flash-lite-latest`, as designed. All results here are from the fallback model.

We ran the pair twice to see how much the model varies.

## What Promise Ledger produced

### Run 1, with the code as it was

The model proposed 26 candidates. Code kept 6.

| # | Record, page | Term | Quote (start) | Stage |
|---|---|---|---|---|
| 1 | Testimony, p. 1 | Income limit | "The total development is offering 95 affordable rental units, 50 in Building 1…" | Proposed |
| 2 | Testimony, p. 2 | Homes | "If the total number of units falls below 623, the number of affordable units may be adjusted…" | Proposed |
| 3 | Testimony, p. 3 | Public support | "At that meeting, the Board recommended approval of the PILOT request…" | Supported |
| 4 | Testimony, p. 4 | Homes | "The development will provide 95 affordable rental units at multiple affordability levels…" | Proposed |
| 5 | Resolution, p. 7 | Remedies | "At the option of the County, if any Payment is due and unpaid sixty (60) days…" | Supported |
| 6 | Resolution, p. 8 | Remedies | "Upon the occurrence and during the continuance of an Event of Default, the County may…" | Supported |

The receipt said:

- **50 homes described as affordable.** This is wrong. The records say 95.
- Furthest stage: Supported. No signed record located.
- Term, responsible party, reporting and rent limits: not located.
- Record 2 date: "not located in the record".

### After the fixes in this branch

The same two saved readings, checked again with the fixed code (no new model call), keep 9 claims. The three new ones are the income levels in the resolution, pages 2 and 3: 32 homes at 20%, 32 at 40% and 31 at 60% of the County's median income, all Supported. The receipt now says 95 homes.

Run 2 (a fresh reading of both files, fixed code) kept 13 of 36 candidates. It added the resolution's "will provide 95 affordable rental units" (p. 2), the zoning rule that 15% of homes be moderate income (p. 2), and two more statements from the fiscal memo (p. 4). It did not propose the Board's recommendation this time.

## Hand check

We read both PDFs page by page and listed every sentence that states a commitment or a term. That list has 31 statements: 12 in the testimony and 19 in the resolution and agreement. We left out pages 15 to 19 of Record 2, which repeat Record 1 as a scan, and page 20, an amendment marked "Not introduced" by hand.

| | Run 1, code as it was | Run 1, fixed code | Run 2, fixed code |
|---|---|---|---|
| Claims kept | 6 | 9 | 13 |
| Quote is in the record, word for word | 6 of 6 | 9 of 9 | 13 of 13 |
| Cited page is right | 6 of 6 | 9 of 9 | 13 of 13 |
| Filed under the right term | 6 of 6 | 9 of 9 | 13 of 13 |
| Stage is right | 6 of 6 | 9 of 9 | 13 of 13 |
| Claims marked signed or delivered in error | 0 | 0 | 0 |
| Hand-listed statements found (recall) | 6 of 31 (19%) | 9 of 31 (29%) | 12 of 31 (39%) |
| Home count on the receipt | 50 (wrong) | 95 | 95 |

Precision was high and recall was low. What the app kept was right. It kept too little.

**Stages.** Record 1 is Proposed, with the Board's recommendation Supported. Record 2 is Supported. Both match our reading: the Council adopted the resolution, and nobody has signed the attached agreement. The model named two signers from the typed names under the blank signature lines. Code rejected both, so nothing was marked Signed.

**Caveats on the kept claims.**

- Claim 1 stops mid-sentence, at the end of page 1. The sentence carries on to page 2 with the 40% and 60% levels, and that half was dropped.
- The app labels income limits as a percent "of area median income". These records use Howard County's median income. The label is wrong here.
- With the fixed code, the receipt flags "Income limit: wording differs (20 percent to 60 percent)". That is a false flag. The three numbers are three levels of one commitment.
- In Run 2, one sentence produced two claims: the full sentence and a piece of it.

### What it missed, and why

The model proposed 17 of the 31 statements in Run 1. Code dropped 11 of those 17. The model never proposed the other 14.

| Missed statement | Where | Why |
|---|---|---|
| 95 affordable homes; the 20%, 40% and 60% income levels; the zoning rule that 15% of homes be moderate income (5 statements) | Resolution, pp. 2 to 3 | The pages have line numbers, so each two-line sentence has a number inside it. The quote check failed. **Fixed** for three. Two still fail because the model dropped "WHEREAS," and wrote "The" for "the". |
| Homes are restricted for 30 years | Testimony, p. 2 | "income-" and "eligible" are split across two lines. The check joined them as "incomeeligible". **Fixed.** It is still dropped, because the sentence says "PILOT" and the term rule treats that as a tax period. |
| The agreement's term is 20 years | Agreement, p. 6 | The sentence is a definition ("Term" means…). Code drops definitions. |
| Two 10-year renewals | Agreement, p. 7 | OCR printed "of ten" as "often", so code saw no number of years. |
| $200 per home per year for 20 years in place of County property taxes | Testimony, p. 2; agreement, p. 6 | The public support rule looks for words like "approve" or "shall pay". These say "is offering" and "shall make". |
| Inspection of records, and reports the County may require | Agreement, p. 8 | The reporting rule needs a cadence such as "annual". |
| The covenant: the owner and all later owners must offer at least 32, 32 and 31 affordable homes during the term | Agreement, p. 7 | The model never proposed it. This is the most important sentence in the deal. |
| The County shall abate all County real property taxes | Resolution, p. 3 | Not proposed. |
| Later owners are bound; the covenants run with the property | Agreement, p. 9 | Not proposed. |
| Late-payment penalties; the agreement is void if not in effect by December 31, 2031 | Agreement, pp. 7 to 8 | Not proposed. |
| Income levels and the $200 payment, as restated in the fiscal memo; $31.9 million less tax revenue over 20 years | Testimony, pp. 4 to 5 | Mostly not proposed in Run 1. Run 2 found two. |

Because of these misses the receipt said the term, the responsible party and reporting were "not located". All three are in the records. Only "rent limits: not located" was right: neither record states a rent limit.

The app also did not surface the gap we chose this deal for: 30 years in the testimony against a 20-year term in the agreement.

### Things a text reader cannot see

- The adoption date and the "Adopted" tick on page 1 of Record 2 are handwritten. The app said the date was not located. That is the right answer for a tool that does not guess.
- The amendment on page 20 is marked "Not introduced" by hand. The model proposed both of its reporting duties as claims. Code dropped them only because the OCR text did not match. A cleaner scan would have let a rejected amendment onto the receipt.

## Cost, tokens and time

| | Record 1 | Record 2 | Both |
|---|---|---|---|
| Tokens in | 3,083 | 9,305 | 12,388 |
| Tokens out (Run 1) | 1,150 | 1,998 | 3,148 |
| Model time (Run 1) | 4.2 s | 9.5 s | 13.7 s |
| Estimated cost (Run 1) | $0.0038 | $0.0078 | $0.0116 |

Cost uses the app's rate table ($0.30 per million tokens in, $2.50 out). The rate for the fallback model that answered may differ.

Whole exercise: 10 API attempts. 4 readings succeeded, 5 tries on the primary model returned 429, and 1 try on the fallback returned 503. That reading showed as failed and worked on retry. Estimated total: $0.025.

## What it taught us

**Fixed in this branch** (`app/pipeline.py`, tests in `tests/test_pipeline.py`). All 305 tests pass, and the sample evaluation is unchanged (96.3% precision, 98.1% recall).

1. **Line numbers in bills and resolutions.** The quote check now also tries the page without margin line numbers. It removes them only when most lines carry one and they count up by one.
2. **A compound word split at its hyphen.** "income-" then "eligible" now matches "income-eligible".
3. **A number printed twice.** "twenty (20) years" and "sixty-six (66) units" are now read as 20 years and 66 homes.
4. **Home count with two describing words.** "95 affordable rental units, 50 units in Building 1" now reads 95, not 50.
5. **"Up to" needs a homes word.** "up to 20% of the median income" was read as a cap of 20 homes and raised a false "wording differs". Found in Run 2.

**Not fixed. Next steps.**

1. **Recall is the main gap.** The term rules were tuned on our own sample wording. Real agreements say "shall make annual payments", "during the Term" and "shall run with the Property". Widen the rules for public support, term, responsible party and reporting, and test them on text like this.
2. **Definitions can carry the value.** Keep a definition when it states the term itself, such as a number of years.
3. **A sentence that mentions the tax break can still state the affordability term.** Do not drop "restrict … for 30 years" because "PILOT" is in the same sentence.
4. **Levels are not a conflict.** Several income levels in one record should show as levels, not as "wording differs". Compare records level by level.
5. **Local income words.** Show the record's own basis ("Howard County median income") and not "area median income" by default. Add local unit names to the prompt.
6. **Sentences that cross a page break.** Join the last line of a page with the first line of the next before checking quotes.
7. **Tell the model what matters most.** It skipped the covenant sentence in both runs. Name covenants, restrictions and "successors and assigns" in the prompt. Consider reading long agreements in sections.
8. **A resolution template is not a vote.** Code marks a resolution Supported when it finds "BE IT RESOLVED". We checked this with the as-introduced copy of another Howard County resolution, which has blank adoption lines (<https://cc.howardcountymd.gov/sites/default/files/2022-10/CR185-2022.pdf>). It was also marked Supported. Here the answer was right, but for a weak reason. Look for a filled-in adoption line or a vote, and ask a person when the line is blank or handwritten.
9. **Handwriting.** Send pages with handwritten marks to the scanned-page reader, or ask staff to enter the adoption date and to confirm amendments.
10. **First-letter case.** The model wrote "The" where the record has "WHEREAS, the". Decide whether to accept a quote that differs only in the case of its first letter.
11. **Run-to-run change.** Two readings of the same file gave 9 and 19 candidates for Record 1. Read twice and merge, or pin the model version.
12. **Locked PDFs.** A related County file is encrypted with no password needed to open it. The app refused it ("could not be read"). Many government PDFs are saved this way. Try an empty password before refusing.
13. **Not checked.** We did not test how the source panel highlights a quote on a line-numbered page in the browser.

## After the recall work

Run date: November 11, 2026. Code: branch `dec2-recall`.

The case study above ended with one finding: what the app kept was right, and it kept too little. This section reports the work on that gap, measured on the same two files.

### The hand check is now a labeled set

The 31 statements are written out in `evals/real/howard-county/expected_claims.json`, each with its file, page, term and stage. `manifest.json` in the same folder gives each PDF's URL and SHA-256. The PDFs are still not in this repository. Anyone can download them and score the pipeline:

```
python evals/run_heldout_evals.py --set real --pdf-dir <folder with the two PDFs>
python evals/diagnose_misses.py --pdf-dir <folder with the two PDFs>
```

Three things to know about the labels:

- The hand check above counted 31 statements but did not print the list. The list was written out again from the same pages, so a few entries may differ from that count. For that reason the "before" numbers below were measured again with this list. They are not copied from the table above.
- Pages 15 to 19 of Record 2 repeat Record 1 as a scan. Claims kept from them are left out of every score. Page 20, the amendment marked "Not introduced", has no labeled statement, so a claim kept from it would count as an error.
- These records restate their terms many times. The labels also list 27 other sentences that state a term of the deal correctly (`also_right`), mostly restatements. A kept claim that matches one is counted as right. It is not counted for recall. Two of the 27 are pieces of labeled statement t01 and were added after a reading split that sentence.

### What changed

1. **Term rules.** The word lists now cover ordinary drafting vocabulary: "shall make annual payments", "shall abate", "run with the Property", "binding upon … successors and assigns", "null and void", "penalties for a late Payment", "shall submit such other reports". This was next step 1.
2. **Definitions that carry a value** are kept: `"Term" means … twenty (20) years`. A definition with no value is still left out. This was next step 2.
3. **A sentence that names the tax break can state the term** when it restricts the homes: "restrict the occupancy … for 30 years" is now a term claim. A span of years in a sentence that is about the tax break alone is kept under public support. This was next step 3.
4. **Sentences that cross a page break** are matched across the break and cited to the page where they start. This was next step 6.
5. **Opening-letter case.** "The Development will provide" now matches "WHEREAS, the Development will provide", and the stored quote is the record's wording. Spaces added by the text layer ("$ 200", "Tax -Property") no longer fail the check. This was next step 10.
6. **The prompt** names covenants, recitals, definitions with values, list items and restated terms. This was next step 7.
7. **Long records are read 4 pages at a time.** Given all 21 pages at once, the model skipped whole sections, a different section on each run. Given 4 pages, it reads them. The second half of next step 7.
8. **One sentence, one claim.** A piece of a sentence already kept from the same page under the same term is not a second claim.

Stage rules were not changed. The model still proposes and code still decides.

### Numbers

Each column is a fresh reading of both files. Run 1 was answered by the main model (`gemini-3.5-flash`; in the "after" run the fallback answered two of the eight sections). Run 2 was answered by the fallback model alone (`gemini-flash-lite-latest`), because the main model was out of quota.

| | Before, run 1 | Before, run 2 | After, run 1 | After, run 2 |
|---|---|---|---|---|
| Model | main | fallback | main | fallback |
| Candidates the model proposed | 49 | 29 | 72 | 66 |
| Claims kept | 21 | 14 | 40 | 34 |
| Kept claims that are right | 20 of 21 (95.2%) | 13 of 14 (92.9%) | 39 of 40 (97.5%) | 33 of 34 (97.1%) |
| Kept claims that match one of the 31 | 15 of 21 | 11 of 14 | 29 of 40 | 23 of 34 |
| Labeled statements found (recall) | 15 of 31 (48.4%) | 11 of 31 (35.5%) | 29 of 31 (93.5%) | 23 of 31 (74.2%) |
| Cited page is right | 100% | 100% | 100% | 100% |
| Stage is right | 100% | 100% | 100% | 100% |
| Claims marked signed or delivered in error | 0 | 0 | 0 | 0 |
| Quotes not on the cited page | 0 | 0 | 0 | 0 |
| Terms not located | rent limits, reporting, responsible party, term | remedies, rent limits, reporting, responsible party, term | rent limits | remedies, rent limits, reporting |

In between: the old readings scored with the new rules alone (no new prompt, no sections) found 23 of 31 on run 1 and 15 of 31 on run 2. So the rules gave about half of the gain on the main model's reading, and the prompt and sections gave the rest.

"Rent limits: not located" is the right answer. Neither record states a rent limit.

The receipt now shows the gap this deal was chosen for: the term is flagged "wording differs", 30 years in the testimony against 20 years in the agreement's definition of "Term".

### Why statements were missed, before and after

| Cause | Before, run 1 | Before, run 2 | After, run 1 | After, run 2 |
|---|---|---|---|---|
| The model never proposed the sentence | 6 | 14 | 0 | 7 |
| The model proposed it, but the quote was not found on a page | 0 | 0 | 0 | 1 |
| Found, then rejected by a term rule | 9 | 5 | 2 | 0 |
| Found, then left out as a definition | 1 | 1 | 0 | 0 |
| Total missed | 16 | 20 | 2 | 8 |

### What it still misses

- **After, run 1 (2 misses).** The right to inspect records (Agreement, p. 8): by rule an inspection right is not a reporting duty, so it is shown as a sentence to check. "95 units at below market rents" (Testimony, p. 5): the model filed it under rent limits, and "below market" is not a limit, so it too is a sentence to check.
- **After, run 2 (8 misses).** The fallback model did not propose the late-payment penalties, the two termination clauses, the void-by-2031 clause or the two reporting sentences, all on pages 7 and 8 of the agreement, or the Board's recommendation. It added "and" to the end of one list item, so that quote was rejected. That is the quote check working, and one statement lost.
- **One kept claim in each run is not a term of this deal:** a sentence about what the County's inventory will gain (run 1), and background on Council Bill 18-2025 filed under income limit (run 2).

### Not fixed

- **Run-to-run change is still large.** 29 against 23 on the same files. Which model answers matters more than anything in the rules. Reading twice and merging, or pinning the model, is still open (next step 11).
- **Income levels still raise a false "wording differs"** (next step 4), and the label still says "area median income" (next step 5).
- **A resolution template is still read as a vote** (next step 8). **Handwriting** is still not read (next step 9). **Locked PDFs** are still refused (next step 12).
- **The rejected amendment on page 20.** Both runs proposed reporting duties from it again. Code dropped them because the OCR text did not match, not because it knows the amendment was not introduced. This risk is unchanged.
- **Source panel.** We did not check in a browser how the panel highlights a quote that crosses a page break, or one on a line-numbered page (next step 13).
- **Cost went up for long records.** Two calls became eight. The pair cost $0.058 on run 1 and $0.024 on run 2, against $0.012 to $0.041 before. Records of up to 4 pages are still one call.

### Limits of this section

The same limits as below, and one more: the rules and prompt were widened with this record's misses in view. The wording added is general drafting vocabulary, and each rule has tests written on other sentences (`tests/test_recall_rules.py`), but this record is no longer unseen. A second real record from another county is the next honest test.

## Limits of this case study

One deal, two records, one county, and one pass of hand checking that no second reviewer or housing staff has repeated. The numbers above are not an accuracy score. They show where the pipeline stands on a record it was never tuned on, and what to fix next.
