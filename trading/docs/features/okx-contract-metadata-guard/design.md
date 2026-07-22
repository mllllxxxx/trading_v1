# OKX Contract Metadata Guard

## Problem

OKX USDT swap order size is expressed in contracts, and each instrument has its
own contract value. `NEAR-USDT-SWAP` uses `contractSize=10`, so `20` contracts
means `200 NEAR`, not `20 NEAR`.

The demo execution path previously allowed unknown top-50 symbols to fall back
to `contract_size=1`. That made risk compilation think a NEAR order was about
`$38.60` notional while OKX opened about `$386` notional, requiring about
`$128` isolated margin at 3x leverage.

## Runtime Rule

For OKX demo/testnet futures execution:

- Before submitting a broker order, resolve exchange instrument metadata for
  the exact swap symbol.
- Pass resolved `contract_size` and `min_qty` into bracket sizing.
- If metadata cannot be resolved for a dynamic symbol outside the static safe
  universe, fail closed and do not submit the order.

Exchange-reconciled positions should preserve broker-reported notional and
contract sizing so dashboard margin math matches OKX.

## Verification

- Unit test dynamic NEAR metadata mapping: `contract_size=10` keeps a `$200`
  capped order near `$40` notional.
- Unit test OKX demo adapter passes exchange metadata into bracket sizing.
- Runtime check current NEAR exposure: `20 contracts * 10 NEAR * 1.93 / 3`
  explains the observed `~$128` margin.
