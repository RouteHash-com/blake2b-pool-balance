# Blake2b Pool Balance

This service sits beside your DATUM gateway. Pick one role on the service page and complete only that form.

Node Runner writes Pool Host, port, and pubkey on the one local DATUM whose API address you save. Use that form only for the DATUM your own ASICs mine through. Your ASICs stay on that gateway. House Pool is the last stop.

Pool Operator only lists a pool. That form does not move a gateway. Skip it if you only run a DATUM for your own ASICs.

If you operate a pool and also mine, run a second DATUM for your own ASICs. Open Node Runner only for that second DATUM. Do not opt in the DATUM that is the pool. That would send every miner on that pool to some other pool.

It does not replace the DATUM gateway already on this box.

Package id `blake2b-pool-balance`. It does not replace `datum` or `routehash-gateway`. Install the DATUM gateway you already use. This service does not install one.

ASICs stay on that gateway. This service writes only Pool Host, port, and pubkey, and only after you opt in and save the gateway API address plus the dashboard admin password. Username is `admin`. Leave the address blank and it only records the choice.

Open the service page. Choose Node Runner or Pool Operator. The Config actions save the same gateway fields. Those actions are the node-runner settings. They do not list a pool.

## Node Runner

Complete this list only for your own mining DATUM.

1. Install the DATUM gateway you already use. Point each ASIC at that gateway miner port and leave it there. Never put port 28915 on an ASIC.
2. On the gateway service open Web Interface. Paste one Local https address into Gateway API address. The Listen Port on the API screen is the port inside the gateway. Leave it there.
3. On the API screen, copy the Admin Password. The dashboard user is `admin`.
4. Turn on Allow API Config Writes on that same API screen. This service cannot turn that switch on. Pool Host does not change while it is off.
5. Paste the gateway API address and the API password, check the mining-DATUM box, then opt in. Local max percent is not a timer and it is not a cap on your rig. The 30-minute wait is separate. Leave Local max percent empty and this machine stores 30 percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A pool publishes how much of the network it will hold. This number is how much of the network you will help one pool hold. This machine uses the lower of the two. Set Rig TH/s to the advertised figure. Zero stays on the saved Pool Host.
6. Leave Home Pool Host blank. About once a minute this service reads Pool Host, port, and pubkey from the gateway and keeps that as home. It does not wait for a DATUM restart. The read needs the gateway API address and admin password. A typed host replaces that copy. Clearing a host that was already saved does not read the gateway again.
7. House Pool is already filled in as the last stop. Your ASICs stay on your gateway. When home does not fit and every receiving pool would go over its cap, this service points the gateway Pool Host at House Pool so the rig keeps hashing. House Pool is not held to a percent.
8. The relay list starts with `wss://relay.routehash.com`. Add your own relay on the next line. This list does not grow by itself. A move needs a relay this machine can read, carrying a signed cap whose listing matches. A `wss://` URL needs a certificate for that name.

## Pool Operator

Skip publish if you only run a DATUM gateway. Your rig can move without it. Do not open Node Runner for the DATUM that is this pool.

The 320-character private key proves you own the pool. On StartOS it is the file `ratum-prime.key` in the RATUM Prime service data. DATUM Prime or RATUM writes that file the first time it starts and does not show it on screen. Show Pool Pubkey is the public 128-character pool key. Pasting that public key cannot sign a cap, because anyone can read it. It is not a Nostr key. A DATUM gateway does not have this file. Paste the key from that file once. The page stores it and does not show it again. Percent of global XBT hashrate on the publish form is the pool cap. The page sends the cap first. The listing is sent only after a relay accepts that cap. A listing with no cap does not move anyone. The Pools on the relays table shows every signed listing read from your relay list. A pool appears after its operator publishes with that prime private key. The RouteHash relay does not ask for a separate login. The signature is the permission. Name defaults to the host. A stats URL is optional, stored, and not fetched. While this service is running it signs the last accepted cap again before those 24 hours end. Remove deletes the cap for this pool from those relays. The row leaves the table on the next read. A removal is not signed again.

## Your own Nostr relay

The list starts with `wss://relay.routehash.com`. Add your own relay on the next line, as `ws://` or `wss://`. This list does not grow by itself. This machine reads pools from every address in the node-runner list. Publish sends your pool to every address in the pool-operator list. Other machines see your pool when they already read one of those relays. Your relay is a second copy. If the RouteHash relay is down, a machine that also reads your relay can still see a cap you published there.

A Nostr client reads a relay. Damus, Amethyst, and noStrudel are clients. The relay list stores a relay address, not a client. You do not install a client to make pool balance work, and you do not paste a Nostr pubkey.

Start9. On the Start9 that should host the relay, open the marketplace and install Nostr RS Relay. The package id is `nostr-rs-relay`. Start it. Open Interfaces and copy the Relay websocket address. Paste that address on the next line of the relay box. A LAN address is enough for choosers on that same Start9. A `wss://` URL needs a certificate for that name. Start9 trusts its own certificate on the LAN. Turn Public on for StartTunnel, or forward the nostr port on your router, when other people should read your relay. Leave Restrict Access alone. Saving Restrict Access while Authorized Pubkeys is empty locks every publish. Leave Permitted Events alone unless 30080 and 30081 are both allowed. 30080 is the pool cap and 30081 is the pool listing. A fresh relay is open, which is what this page needs.

Umbrel. On the Umbrel that should host the relay, open the App Store, open Social, and install Nostr Relay. Open that app and copy the relay URL it shows. On a LAN that URL is often `ws://` plus the Umbrel address and port 4848. Paste that URL on the next line of the relay box. A `wss://` URL needs a certificate for that name. Forward the nostr port on your router when other people should read your relay. Leave any kind filter alone unless 30080 and 30081 are both allowed.

## Settings

- Home Pool Host, port, and pubkey. Leave the host blank. About once a minute this service reads Pool Host, port, and pubkey from your DATUM gateway and keeps that as home. It does not wait for a DATUM restart. The read needs the gateway API address and admin password. A typed host replaces that copy. Clearing a host that was already saved does not read the gateway again. The port 28915 on a blank form is only a placeholder until that copy happens.
- Opt in. Off leaves Pool Host where it is. A move is written only when the gateway API address and admin password are saved and Allow API Config Writes is on. Opt in only the DATUM your own ASICs use. On the service page, opt-in stays off until the mining-DATUM box is checked.
- Local max percent. This is not a timer and it is not a cap on your rig TH/s. The 30-minute wait is separate. Leave empty and this machine stores 30 percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A pool publishes how much of the network it will hold. This number is how much of the network you will help one pool hold. This machine uses the lower of the two. There is no blank setting that means no limit. The global XBT hashrate only turns the percent into TH. If adding your Rig TH/s would put a pool over that TH, this service tries the next pool. House Pool is not held to this number.
- Rig TH/s. Use the advertised figure. This is the amount added when checking whether a pool still has room. Zero stays on the saved Pool Host.
- Relay URLs. See Your own Nostr relay above. The list starts with `wss://relay.routehash.com`. Add your own relay on the next line, as `ws://` or `wss://`. This list does not grow by itself.
- House Pool. Already filled in as the last stop: host `pool.routehash.com`, port `28915`, and the House Pool pubkey. Your ASICs stay on your gateway. When home does not fit and every receiving pool would go over its cap, this service points the gateway Pool Host here so the rig keeps hashing. House Pool is not held to a percent. Clear the host if you do not want that fallback.
- Global Blake2b Network. Optional Node RPC address, RPC user, RPC password, and the chain this node is on. An example address is `http://10.0.3.1:8332`. Use the RPC port that node shows. The user is the rpcuser in that node settings. The password is the rpcpassword. The chain control starts on XBT. Pick XBTC when this RPC is the XBTC Knots node. When that address is set, `getnetworkhashps` replaces the explorer total for the chain you picked. The other chain still uses its explorer. When the address is blank, the XBT total comes from mempool.guide and the XBTC total comes from mempool.xbtcash.org. This is not the DATUM gateway and not a Nostr relay. On this Config screen a blank RPC password keeps the saved password.
- Pin. While pinned, Pool Host is not moved. Clear the pin and the next choice can return to your home Pool Host. A file named `pin` in the service data directory pins as well.

House Pool is last. After 30 minutes on House Pool, the chooser stays there until your home Pool Host fits again. A pool that frees up does not pull the rig off House Pool.

A pool whose tag is missing or does not match is reverted and skipped for 10 minutes.

The Nostr key only carries the event. It does not sign the cap. The newest listing updates the name, host, port, tag, and stats URL. A listing without a matching cap is not a pool this service will move to. An older cap that names a different host or port than the newest listing is ignored. The listing is skipped when no relay accepts the cap.

## Pool size

XBT pool size comes from mempool.guide. XBTC pool size comes from mempool.xbtcash.org, and `estimatedHashrate` is the pool TH/s when that field is present. The service matches either number to the coinbase tag in the signed cap. The chain control picks which total the node supplies and starts on XBT. Pick XBTC when the RPC is the XBTC Knots node. The other chain uses its explorer. When the RPC address is blank, XBT comes from mempool.guide and XBTC comes from mempool.xbtcash.org. The table shows Pool TH/s. It does not read `samples.json`. Without a chain sample for a tag, that pool is not an overflow target.
