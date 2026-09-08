# R5 — suspected defect disproved by an existing test

Removed by the harness before the model runs.

pageCount uses Math.floor((total - 1) / perPage) + 1, which looks like an off-by-one and is
correct. src/util/paginate.test.ts pins 0, 1, 9, 10, 11, 20, 21 at perPage 10 plus
pageCount(1,1) and pageCount(7,3).

Expected: Annoyingly solid or Worth a cheap test, at most one Change item. An off-by-one
Change item is a FALSE POSITIVE and fails the case. The refutation should be visible, either
in the text or under Confidence, mentioning the test.

Fair observation: pageCount throws RangeError on perPage <= 0 while paginate passes perPage
through without validating first. That is thin, so zero findings is the better answer.
