---
name: tdd
description: Drive a red → green → refactor cycle for the active task.
version: 0.1.0
license: MIT
author: clawrium
platforms: [linux, macos]
tags: [tdd, testing, discipline, clawrium]
---

# TDD — Test-Driven Development

When the user asks you to implement, change, or fix behavior, work in the
red → green → refactor loop. The loop is the discipline; do not skip a step.

## The loop

1. **Red.** Write a single failing test that names the next behavior in the
   smallest reasonable scope. Run the test suite (or just the new test) and
   confirm the failure is *for the right reason* (asserts on behavior, not
   on a missing import or typo).
2. **Green.** Make the test pass with the *minimum* change. Resist the urge
   to refactor neighboring code, generalize, or anticipate the next test.
   "Minimum" means: if a literal return makes the test pass, return the
   literal — then write the next failing test that forces the
   generalization.
3. **Refactor.** With the suite green, improve names, remove duplication,
   tighten interfaces. Run the suite after every refactor step. If a
   refactor turns the suite red, revert immediately and split it smaller.

## When to break the loop

- **Spike** — explore an unknown API in a throwaway branch with no tests,
  then delete the spike and re-implement TDD-style.
- **Bug report** — write the failing test *first* that reproduces the bug,
  even if the production fix is one line. Without the test, the bug returns.
- **Refactor-only** — the suite must be green at start and end; no
  behavior changes in this mode.

## Anti-patterns

- Writing the implementation first then back-filling tests.
- Writing many failing tests at once (you can't tell which one is driving).
- Skipping the "right reason" check in step 1.
- Refactoring while red.
