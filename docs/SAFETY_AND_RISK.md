# Safety, Risk and Testing

## 1. Demo-Account Protection

The supplied bridge includes a demo-account guard based on the MetaTrader 5 account trade mode.

State-changing operations are intended to be blocked when the account is not recognized as a demo account.

This protection must be independently validated in an isolated test environment before relying on it.

## 2. Current Risk Configuration

The supplied configuration contains:

| Setting | Current value |
|---|---:|
| Risk per new trading day | 10% of starting balance |
| Maximum daily loss | 20% |
| Configured order volume | 0.01 |
| Reward-to-risk ratio | 2.0 |

**Risk warning:** These settings are aggressive. They are not a recommendation and do not guarantee that losses will remain within configured limits.

Slippage, gaps, execution failures, broker conditions and other risks can cause actual results to differ from intended limits.

Do not trade with money you cannot afford to lose.

The 10% setting is described as risk per new trading day, not risk per individual trade. The 20% value is the configured maximum daily loss setting. Both are aggressive software settings and must be independently reviewed and tested.

## 3. API Security

- Keep the bridge bound to loopback unless a separately reviewed secure architecture is implemented.
- Never expose the bridge directly to the public internet.
- Use a strong, unique API key.
- Keep `.env` private.
- Never publish account credentials, API keys or sensitive trading logs.
- Do not share secrets in screenshots or support messages.

## 4. Position Ownership

The bridge includes magic-number checks intended to restrict position management to positions belonging to this system.

The configured magic number is `260927`.

Do not assume this mechanism protects against every possible account or broker-side condition.

## 5. Shadow Confirmation

Shadow confirmation is disabled in the supplied engine.

Do not enable it without configuring and testing the separate shadow bridge.

## 6. Testing Status

The package currently has seven source-level safety tests.

These tests check source structure and selected safety conditions. They do not prove:

- Successful connection to a broker.
- Correct order execution under all conditions.
- Correct behavior during network failures.
- Protection against every execution race or failure.
- Profitability or future performance.

A separate demo-account integration test is required.

## 7. Operational Rule

Do not switch to a live account as part of installation or packaging.

Any future live deployment requires a separate review, explicit authorization and independent risk assessment.

For reproducibility on a compatible Windows/Python 3.11 environment, the tested dependency snapshot is provided in `requirements-lock-py311-windows.txt`. The standard installation uses `requirements.txt`.