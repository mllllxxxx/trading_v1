# Risk Critic And Compiled Rule Verifier

## Goal

Implement workflow steps 13-14:

- add a deterministic risk critic that reviews draft `TradeDecisionTicket`
  payloads before verifier/risk compiler;
- add a rule verifier that reads generated
  `trading/rulebook/compiled/verifier_rules.json`;
- reject unsafe non-HOLD tickets without calling broker or computing final
  quantity.

## Scope

- Add `trading/auto/critic.py`.
- Add `trading/verifier/rule_verifier.py`.
- Add `trading/verifier/__init__.py`.
- Add tests for critic and verifier fail-closed behavior.
- Update Dockerfile so the verifier package is available in the container.

## Non-Goals

- Do not wire scheduler execution through the new verifier yet.
- Do not implement risk/order compiler in this batch.
- Do not add broker calls or live trading behavior.
- Do not let the LLM set executable quantity.
- Do not move risk thresholds into prompt or scheduler code.

## Design

The critic is rule-based for MVP. It accepts `dossier`, `retrieved_rules`, and a
draft ticket. It returns the existing shared `CriticReview` contract:

- `APPROVE` when no concern is found;
- `REVISE` for softer concerns that should reduce risk or request better
  context;
- `REJECT` for hard-rule violations such as missing playbook, fake citation,
  data-quality failure, or risk exceeding compiled hard-rule limits.

The rule verifier loads generated hard rules from
`trading/rulebook/compiled/verifier_rules.json`. It validates:

- generated artifact marker;
- `TradeDecisionTicket` schema;
- real rule citations and playbook ID;
- playbook applicability for market, candidate direction, regime, and timeframe;
- non-HOLD data quality and positive current price;
- risk plan presence and risk percentage within compiled hard-rule limit;
- required entry/risk/invalidation fields;
- required playbook hard-rule citations when a playbook declares them.

Verifier exceptions fail closed as `VerifierResult(passed=False, ...)`.

## Validation Plan

- `trading/tests/test_critic.py`
- `trading/tests/test_rule_verifier.py`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
- `python -m pytest -x`
- Docker build/up and `/health`
