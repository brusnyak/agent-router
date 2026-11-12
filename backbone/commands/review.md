---
name: review
description: Review a change or file for bugs, risks and missing tests. Read-only, no edits.
worker: claude
readonly: true
---
Review the following for correctness bugs, security issues and missing tests. Do not edit files.
Report findings ranked by severity with file:line evidence, then the single highest-leverage fix.

$ARGUMENTS
