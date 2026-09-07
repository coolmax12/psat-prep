# Changelog

## 2026-09-07

- Allowed students to move backward and forward through every test question without answering in sequence.
- Added a pre-submit numbered question grid with green answered states and yellow unanswered states.
- Allowed direct navigation from the question grid and submission with unanswered questions after confirmation.
- Kept the running test timer visible through question navigation and answer review.

## 2026-09-06

- Removed `Math output error` placeholders from imported prompts, explanations, and stored source text.

## 2026-08-29

- Expanded PDF answer-choice image crops to include formulas positioned above their choice labels without pulling in the previous choice.

## 2026-08-22

- Kept corrected questions out of the normal active test pool until fresh and still-missed material is exhausted.
- Cleared missed-review flags whenever a later answer is correct, including corrections made during normal tests.
- Accepted equivalent fractions, decimals, alternate numeric lists, and documented answer-entry variants for typed Math responses.

## 2026-08-13

- Rendered Math explanations from the source PDF so formulas and diagrams remain legible when extracted text is incomplete.

## 2026-08-12

- Added a Windows server watchdog task that restarts the local app when it is not listening on the configured port.

## 2026-08-11

- Corrected answer scoring and made saved in-progress answers reliably available when a session is resumed.

## 2026-08-10

- Improved PDF rendering for graph-, table-, and formula-heavy questions and answer choices.
- Added a media refresh utility for existing imports.
- Added Windows update-and-restart automation with database backups and logs.

## 2026-08-09

- Randomized normal test generation so selected questions are no longer pulled in source PDF order.
- Kept the existing fresh-first, due-review, and seen-question scheduling buckets while sampling randomly inside each bucket.
- Added a Math and Reading/Writing rule that targets at least 40% Hard questions in normal tests when Hard questions are available in the selected filters.
- Added fresh top-level topic coverage for Math and Reading/Writing tests so each selected official topic is represented when unexhausted questions are available.
- Preserved difficulty filters: tests that exclude Hard questions stay limited to the selected Easy/Medium difficulties, and Hard-only tests remain all Hard.
- Preserved imported answer choice order for Math and Reading/Writing so displayed A/B/C/D labels match source PDF explanations.
- Allowed in-progress test answers to be changed before finishing and added Back/Next navigation through reached questions.
- Added a live test stopwatch plus completed-test total time and average time per question.
- Moved the in-test stopwatch into the sticky bottom action row so it stays visible while scrolling.
- Updated README documentation to describe the project feature set and the current test-sampling behavior.
