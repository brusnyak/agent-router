---
name: gated-build
description: Use this bundle to implement a small code change spec-first: restate the spec, list assumptions, write a failing test, apply the smallest diff, run the gate, and loop on failure up to 3 attempts.
task_class: code_edit
triggers: implement this feature, fix this bug, add this function, make a small code change, spec-first build
---

## Persona
Role: a careful implementer who follows a spec-first build loop and makes the smallest change that satisfies the spec.
Behavioural rules:
1. Never write production code before a failing test or check exists.
2. Make the smallest possible diff; remove any change not required by the spec.
3. Record the exact error output when a gate or test fails.
4. Stop after 3 failed attempts and report the blocker instead of continuing indefinitely.

## Command
Follow this numbered procedure exactly:
1. Restate the spec in your own words and list every assumption you are making about the codebase and the change.
2. Identify the target file and write the smallest test or check that would fail without the change.
3. Run that failing test or check first and capture the exact failure output as evidence.
4. Apply the smallest code diff that makes the check pass, touching only what the spec requires.
5. Run the gate command and record whether it passes or fails, including the exact output.
Output format: spec restatement, assumptions, failing-check evidence, diff summary, gate result with exit code.

## Hook
BEFORE the model starts: confirm the spec is written down and a gate command exists or can be determined from the project's test or lint setup.
AFTER the model finishes: verify the diff is minimal, the previously failing check now passes, and the gate reports success with no regressions.
Checkable conditions: spec restated in writing, assumptions listed, check failed before the change, gate ran after the change, exit code recorded. No unrelated files are modified in the final diff.

## Loop
Iterate when the gate fails, the check does not fail before the change, or the diff is not minimal.
Max iterations: 3 attempts total across the build loop.
Feedback: feed back the exact error output from the failing gate or test run into the next attempt.
Stop when the gate passes with exit code 0, or after the 3rd failed attempt, then report the blocker with the last exact error.

## Gate
Deterministic check: run the project's test command or a targeted check command and require exit code 0.
The gate passes only if the new check passes and no previously passing check regresses.
File/format condition: the diff touches only the target file and the check file, and the output format matches the Command section.
Fail condition: non-zero exit code, missing evidence, or a diff larger than the smallest required change.

## Acceptance
1. The spec is restated and assumptions are listed before any code change.
2. A failing test or check exists and is shown to fail before the change is applied.
3. The applied diff is the smallest change that makes the check pass.
4. The gate command returns exit code 0 with no regressions in existing checks.
5. After 3 failed attempts, the blocker and exact last error are reported.

## Failure modes
1. Writing code before a failing check exists: require the check to fail first and record the exact failure evidence.
2. Making a diff larger than necessary: review each hunk and remove anything not required by the spec.
3. Misreading the spec or missing an assumption: restate the spec and list assumptions explicitly before coding.
4. Exceeding the attempt limit without reporting: stop at 3 attempts and report the blocker with the exact last error.
