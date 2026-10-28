# Engineering log

## 2026-10-27

**Inspected:**
- every `src/*.py` module
- `tests/conftest.py`
- the docs (README, THIS_WEEK, ACTIVITY_PLAN)
- the git history

`origin/main` had nothing new.

**Environment:**
- There was no `.venv`, so I created one with `pip install -r requirements.txt` (Python 3.15.2).
- There is no `.env`, so there's no API key and no live LLM run was possible.

**Baseline tests:** 219 passed, 1 failed (`test_api_consent_rejects_admin_without_a_resident_row`).
- It passes on its own but fails after the magic-link route tests. Their `Set-Cookie` stayed
  in the shared `TestClient` jar, so the stale cookie was read instead.
- Fixed in the test helper (`reset_state` now clears cookies). This was a test isolation bug,
  not a product bug.
- Result: 220 passed.

**Simulation baseline:** Ran `src/match_eval.py` (new) on the code-only matcher. 282 groups,
0 rule violations, deterministic. Results are in `evaluation/results/baseline/`.

**Finding F1 (id-order tie-break):**
- Confirmed by a causal probe: reversing the tie-break flips the gap.
- Fixed with `demand.tie_order` in Python and the JS mirror.
- Tests added. The live `/run` page renders with no console errors, and the JS hash matches
  Python for e001–e005.

**After the fix:** 286 groups, 0 violations, and the gap goes from 0.47/0.52 to 0.03/0.14
placed days a week. Results are in `evaluation/results/`.

**Tests:** 227 passed.

**Not done or uncertain:**
- The LLM layer is not evaluated.
- F2–F7 need team decisions.
- The pilot bugs (held-back pairs, admin revocation) are documented, not fixed.
- The standalone Artifact HTML is not regenerated.
- Nothing is committed.

**Needs Idan:**
- approval to commit
- Q7 (paid run)
- the team session
