# Blake2b Pool Balance (StartOS)

Blake2b Pool Balance is for a person who already mines Blake2b through their own DATUM gateway and does not want one pool to hold more of the XBT network than they are willing to help it hold.

About once a minute it reads the pools that have published a size limit. When the pool this gateway is on would pass the share this machine will help one pool hold, it moves Pool Host to a pool that still has room. That share starts at 30 percent of global XBT hashrate. House Pool is the last stop, already filled in as `pool.routehash.com:28915`, so the rig keeps hashing when every other pool is full. A pool operator uses the other card on the same page to publish that pool's own limit. Only this gateway moves, and only after you turn that on.

This StartOS download is the 64-bit package for an AMD or Intel server, `blake2b-pool-balance_x86_64.s9pk`. A Raspberry Pi running StartOS does not have this package in this release. A Raspberry Pi running Umbrel installs it from the RouteHash store, which builds the app on that Pi: [github.com/RouteHash-com/umbrel-store](https://github.com/RouteHash-com/umbrel-store).

Package id `blake2b-pool-balance`. Title **Blake2b Pool Balance**. Version `0.1.0:0`. Icon is `icon.svg` only.

It sits beside the DATUM gateway you already run. It does not replace `datum` or `routehash-gateway`. It does not install DATUM, it does not ship Knots, and it does not listen for ASICs. Your ASICs stay on the miner port of the gateway you already use. Never put port 28915 on an ASIC.

This service writes only three DATUM fields, and only after you opt in: Pool Host, Pool Port, and Pool Pubkey. It does not change the API listen port, the admin password, Pool Pass Full Users, Always Pay Self, or Prefer Pool Mining. Leave the gateway API address blank and it only records the choice. It does not turn on Allow API Config Writes. You turn that switch on yourself, on the DATUM dashboard.

It is a local choice on this machine. It does not change Knots, it does not change DATUM consensus, and it does not bind any machine that does not run it. A pool can still grow past 30 percent of global XBT hashrate when its miners do not opt in. The 30 percent field is the limit this machine will help one pool hold.

Sideload the x86_64 file from [Releases](https://github.com/RouteHash-com/blake2b-pool-balance/releases/tag/v0.1.0). Product notes: [app.routehash.com/pool/connect](https://app.routehash.com/pool/connect). The website download page stays the RouteHash Gateway s9pk only. This package is not added there.

The same app for Umbrel is in the RouteHash community store: [github.com/RouteHash-com/umbrel-store](https://github.com/RouteHash-com/umbrel-store). See [Umbrel](#umbrel) below.

## Install

1. Install the DATUM gateway you already use, and the Knots node that gateway uses. This package has an empty dependency list on purpose. StartOS will not pull DATUM in for you, and it will not replace a service named `datum`.
2. Download `blake2b-pool-balance_x86_64.s9pk` from [v0.1.0](https://github.com/RouteHash-com/blake2b-pool-balance/releases/tag/v0.1.0). This release file is x86_64.
3. Sideload that file in the StartOS UI. StartOS lists a new service named **Blake2b Pool Balance**.
4. If StartOS says it updated Datum, stop. That file's package id was `datum`. This file's id is `blake2b-pool-balance`. Sideloading it again is a reinstall of Blake2b Pool Balance. It does not replace RouteHash Gateway or any other gateway id.
5. Open the service page. StartOS serves it on port **7156** (Interfaces, then the web UI). The page is also what the Config actions edit. Those actions save the node-runner fields. They do not list a pool.

One DATUM per box is still the rule for the gateway itself. This service is not a second DATUM. It is a small Python loop beside the one you have. It runs about once a minute.

## Two roles

The service page has two cards: **Node Runner** and **Pool Operator**. Those cards are the only role switch. There is no second row of buttons.

Complete only the form for the role you are. The help under each card starts closed. Open it when you want the long steps. The red warning on the selected card stays open.

**Node Runner** is the only form that can move Pool Host. Use it only for the DATUM your own ASICs mine through. Check the mining-DATUM box or the page stores opt-in as off.

**Pool Operator** only lists a pool. That form does not move a gateway. Skip it if you only run a DATUM for your own ASICs.

If you operate a pool and also mine, run a second DATUM for your own ASICs. Open Node Runner only for that second DATUM. Do not opt in the DATUM that is the pool. That would send every miner on that pool to some other pool.

## Node Runner

Complete this list only for your own mining DATUM.

1. Point each ASIC at that gateway's miner port and leave it there. On StartOS that port is the one Interfaces shows for Stratum or Mining, often 23334, or the port StartOS assigned. Never put port 28915 on an ASIC. Hash-only miners who do not run a gateway skip this service. Their firmware stays `stratum.routehash.com:23335`.
2. On the DATUM dashboard open Interface, then Web UI, then Local. Copy the address and the API Listen Port. The gateway API address is `http://` plus that address and port.
3. Copy the API Password from that same Local screen. The dashboard user is `admin`.
4. Turn on Allow API Config Writes. This service cannot turn that switch on. Pool Host does not change while it is off.
5. On this service page, choose Node Runner. Paste the gateway API address and the API password. Check the mining-DATUM box, then opt in. A blank password on this page keeps the saved password. On the StartOS Config screen, a blank admin password clears the saved password, and then this service does not write.
6. Leave Local max percent empty if 30 is what you want. See [Local max percent](#local-max-percent).
7. Set Rig TH/s to the advertised figure for the rigs on this gateway. Zero stays on the saved Pool Host. This number is added only when checking whether a pool still has room. It is not a hash ceiling on the ASIC.
8. Leave Home Pool Host blank. About once a minute this service reads Pool Host, port, and pubkey from the gateway and keeps that as home. It does not wait for a DATUM restart. The read needs the gateway API address and the admin password. A typed host replaces that copy. Clearing a host that was already saved does not read the gateway again. Port 28915 on a blank form is only a placeholder until that copy happens.
9. Leave House Pool filled in unless you do not want that fallback. See [House Pool](#house-pool).
10. Leave the relay list, or add your own relay on the next line. See [Your own Nostr relay](#your-own-nostr-relay).

Save node runner settings on the node card. The relay list is on the same form. **Relays this machine reads** sits under **Pools on the relays**, and the second **Save node runner settings** button on that card stores the list too.

Opt in before Pool Host can move. Off leaves Pool Host where it is. A move is written only when the gateway API address and admin password are saved and Allow API Config Writes is on.

## Pool Operator

Skip publish if you only run a DATUM gateway. Your rig can move without a listing. Do not open Node Runner for the DATUM that is this pool.

The 320-character private key proves you own the pool. On StartOS it is the file `ratum-prime.key` in the RATUM Prime service data. DATUM Prime or RATUM writes that file the first time it starts and does not show it on screen. Show Pool Pubkey is the public 128-character pool key. Pasting that public key cannot sign a cap, because anyone can read it. It is not a Nostr key. A DATUM gateway does not have this file.

Paste the key from that file once. The page stores it in the service data and does not show it again. After save it shows the derived public 128-character pool key.

Percent of global XBT hashrate on the publish form is the pool cap, not the node-runner limit. The page sends the cap first. The listing is sent only after a relay accepts that cap. A listing with no cap does not move anyone. Name defaults to the host. A stats URL is optional, stored, and not fetched. Publish again within 24 hours. Caps are not auto-republished. Remove sends a cap that stops receiving, then a listing marked removed.

The **Pools on the relays** table is every signed listing read from your relay list. It is not an allow list. The RouteHash relay does not ask for a separate login. The signature is the permission. Open writes stay on. RouteHash cannot sign another pool's cap.

**List your pool** starts closed. Open it for these steps. That form does not write Pool Host.

## Your own Nostr relay

The node-runner relay list starts with `wss://relay.routehash.com`. Add your own relay on the next line, as `ws://` or `wss://`. This list does not grow by itself. There is no relay directory. Do not expect every seen relay to be copied onto your list.

This machine reads pools from every address on the node-runner list. Publish sends your pool to every address on the pool-operator list. Other machines see your pool when they already read one of those relays. One shared reachable relay is enough. Extra relays are for an outage. If the RouteHash relay is down, a machine that also reads your relay can still see a cap you published there.

A `wss://` URL needs a certificate for that name. The certificate for `relay.routehash.com` is on the RouteHash side. Your own `wss://` name needs its own certificate. Start9 trusts its own certificate on the LAN.

A Nostr client reads a relay. Damus, Amethyst, and noStrudel are clients. This list stores a relay address, not a client. You do not install a client to make pool balance work, and you do not paste a Nostr pubkey.

**Your own Nostr relay** starts closed. It sits under **Pools on the relays**, after **Relays this machine reads**.

### Start9

On the Start9 that should host the relay, open the marketplace and install **Nostr RS Relay**. The package id is `nostr-rs-relay`. Start it. Open Interfaces and copy the Relay websocket address. Paste that address on the next line of the relay box. A LAN address is enough for choosers on that same Start9. Turn Public on for StartTunnel, or forward the nostr port on your router, when other people should read your relay.

Leave Restrict Access alone. Saving Restrict Access while Authorized Pubkeys is empty locks every publish. Leave Permitted Events alone unless kinds **30080** and **30081** are both allowed. 30080 is the pool cap. 30081 is the pool listing. A fresh relay is open, which is what this page needs.

### Umbrel

On the Umbrel that should host the relay, open the App Store, open Social, and install **Nostr Relay**. Open that app and copy the relay URL it shows. On a LAN that URL is often `ws://` plus the Umbrel address and port **4848**. Paste that URL on the next line. Forward the nostr port on your router when other people should read your relay. Leave any kind filter alone unless 30080 and 30081 are both allowed.

## Local max percent

Local max percent is not a timer, not a cap on rig TH/s, and not the pool operator's published cap. The 30-minute House Pool wait is separate.

Leave the field empty and this machine stores **30** percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A stored number above 30 is used as 30. There is no blank setting that means no limit.

A pool publishes how much of the network it will hold. This number is how much of the network you will help one pool hold. This machine uses the lower of the two. The global XBT hashrate only turns that percent into TH. If adding your Rig TH/s would put a pool over that TH, this service tries the next pool. House Pool is not held to this number.

## House Pool

House Pool is already filled in as the last stop:

| Field | Value |
| --- | --- |
| Host | `pool.routehash.com` |
| Port | `28915` |
| Pubkey | the House Pool pubkey shown on [pool/connect](https://app.routehash.com/pool/connect) |

Your ASICs stay on your gateway. When home does not fit and every receiving pool would go over its cap, this service points the gateway Pool Host at House Pool so the rig keeps hashing. Clear the host if you do not want that fallback.

After 30 minutes on House Pool, the chooser stays there until your home Pool Host fits again. A pool that frees up does not pull the rig off House Pool during that hold.

## How a move is chosen

About once a minute the service reads the relays, the pool-size sample, and the global XBT hashrate, then decides.

- Pool size comes from mempool.guide, matched to the coinbase tag in the signed cap. A full tag match is required. A very short tag is skipped. This service does not read `samples.json`. Without a chain sample for a tag, that pool is not an overflow target.
- The global XBT hashrate comes from the node RPC when Node RPC address is set (`getnetworkhashps` on Knots or Bitcoin Core). When that address is blank, the total comes from mempool.guide. An example RPC address on a StartOS box is `http://10.0.3.1:8332`. Use the RPC port that node shows. The user is the rpcuser. The password is the rpcpassword. This is not the DATUM gateway and not a Nostr relay. A blank RPC password on the Config screen keeps the saved password.
- A listing without a current cap is not a move target. A cap that does not match the current listing is skipped. The newest unexpired listing updates the name, host, port, tag, and stats URL. The Nostr key only carries the event. It does not sign the cap. The DATUM identity signs the cap.
- A pool whose tag is missing or does not match is reverted and skipped for about 10 minutes.
- Home that was copied from your gateway still works when that pool has not published a listing.
- Pin holds the current Pool Host until you clear it. A file named `pin` in the service data directory pins as well. Clear the pin and the next pass can return to home.

Successful samples are kept for a short while. A failed fetch can reuse a recent sample. Cap stats URLs are never fetched.

## What you will see on the page

- **Node Runner** and **Pool Operator** cards.
- **Before this gateway can move** starts closed. It is the node-runner checklist.
- **List your pool** starts closed. It is the pool-operator checklist.
- **Pools on the relays**, then **Relays this machine reads**, then **Your own Nostr relay** (closed until you open it).
- Local max percent, with a maximum of 30.
- House Pool already filled in.
- Global Blake2b Network for the optional node RPC.

The loop does not show the private pool key again after you save it. It does not print the gateway admin password.

## Umbrel

In Umbrel: **Settings → App stores → Add a community app store** and paste:

```
https://github.com/RouteHash-com/umbrel-store
```

Install **Blake2b Pool Balance**. It does not replace **RouteHash Gateway**. The settings page is port **7156**. Copy says **beta** until a live Umbrel install is confirmed. The store app includes the Dockerfile and builds on install. It does not set both `build` and `image`, because Umbrel builds from the wrong path when a service has both.

The long Umbrel description is [blake2b-pool-balance/README.md](https://github.com/RouteHash-com/umbrel-store/blob/main/blake2b-pool-balance/README.md) in that store.

## Build

From this directory, with Node and Docker:

```
make x86
```

Output is `blake2b-pool-balance_x86_64.s9pk`. The image inside the package is built from the `Dockerfile` here. `node_modules/` and `javascript/` are build output and are not part of the source tree you need to edit. Pack from this directory only.
