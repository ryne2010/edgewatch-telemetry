# ADR: Standardize pressure sensors at 0–100 psi (water + oil)

Date: 2026-02-20  Status: Accepted

## Context

EdgeWatch monitors equipment where **water pressure** and **oil pressure** are key
operational signals. Hardware will vary by installation, but we need a sane, portable
default that:

- matches common pump/well monitoring ranges
- works with long cable runs and electrically noisy environments
- maps cleanly into the telemetry contract and alert thresholds

## Decision

We will standardize the default pressure measurement assumptions as:

- **Range:** 0–100 psi for both water and oil pressure
- **Units:** psi (edge converts raw sensor units into contract units before sending)
- **Preferred signal type:** **4–20 mA** industrial transmitters for noise immunity

Implementation will treat pressure scaling as configuration, so other ranges can be
supported by adjusting scaling constants (not rewriting code).

## Consequences

- ✅ Default thresholds, UI ranges, and test data are consistent
- ✅ 4–20 mA is robust for longer cable runs and motor noise
- ❌ 4–20 mA requires input conditioning (current-to-voltage) before an ADC
- ❌ Some deployments may require a different range (e.g., 0–300 psi)

## Alternatives considered

- **0.5–4.5 V transducers**
  - Pros: simpler wiring; direct ADC voltage
  - Cons: less robust for noise/cable length
- **Digital pressure sensors (I2C/SPI)**
  - Pros: no analog conditioning
  - Cons: fewer field-ready form factors; often shorter cable constraints
- **Different default range**
  - Pros: may match a specific system better
  - Cons: less general for a baseline reference implementation

## Rollout / migration plan

- Keep contract keys stable: `water_pressure_psi`, `oil_pressure_psi`.
- Keep alert thresholds configurable via `contracts/edge_policy/v1.yaml`.
- Put scaling constants and sensor ranges in edge config examples under `agent/config/`.

## Validation

- Validate that 4 mA maps to ~0 psi and 20 mA maps to ~100 psi after scaling.
- Verify alert thresholds trigger/recover as expected using simulated inputs.
- Verify UI charts display appropriate ranges for typical operating values.
