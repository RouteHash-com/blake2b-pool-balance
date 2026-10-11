# Blake2b Pool Balance (StartOS)

Opt-in chooser for a Blake2b DATUM Pool Host. Package id `blake2b-pool-balance`. Title **Blake2b Pool Balance**. Version `0.1.0:0`. Icon is `icon.svg` only.

It sits beside the DATUM gateway you already run. It does not replace `datum` or `routehash-gateway`. It does not install DATUM and it does not listen for ASICs.

Sideload the `.s9pk` from [Releases](https://github.com/RouteHash-com/blake2b-pool-balance/releases). Product notes: [app.routehash.com/pool/connect](https://app.routehash.com/pool/connect).

## What it does

- Node Runner writes only Pool Host, port, and pubkey, and only on the one DATUM whose API address you save, after you opt in. Use that for the DATUM your own ASICs mine through. ASICs stay on that gateway miner port. Never put 28915 on an ASIC.
- Pool Operator only lists a pool. That form does not move a gateway. Do not opt in the DATUM that is the pool. That would send every miner on that pool to some other pool.
- Local max percent is not a timer. Leave it empty and this machine stores 30 percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A pool publishes how much of the network it will hold, and this machine uses the lower of the two.
- House Pool is already filled in as the last stop (`pool.routehash.com:28915`). Clear it if you do not want that fallback.
- The relay list starts with `wss://relay.routehash.com`. Add your own relay on the next line. This list does not grow by itself.

The service page is on port 7156. See `instructions.md`.

## Umbrel

The same app is in the RouteHash community store: [github.com/RouteHash-com/umbrel-store](https://github.com/RouteHash-com/umbrel-store).

In Umbrel: **Settings → App stores → Add a community app store** and paste that URL. Install **Blake2b Pool Balance**. It does not replace **RouteHash Gateway**.

Copy says **beta** until a live Umbrel install is confirmed. The store app includes the Dockerfile and builds on install. It does not set both `build` and `image`, because Umbrel builds from the wrong path when a service has both.

## Build

From this directory, with Node and Docker:

```
make x86
```

Output is `blake2b-pool-balance_x86_64.s9pk`. The image inside the package is built from the `Dockerfile` here.
