import { IMPOSSIBLE, VersionInfo } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.1.0:0',
  releaseNotes: {
    en_US:
      'Service page uses the Node Runner and Pool Operator cards. Local max percent refuses a number above 30. Relays this machine reads sits under Pools on the relays. Before this gateway can move and List your pool stay closed until opened. The Nostr relay steps stay closed until opened. Node Runner writes Pool Host only on a personal mining DATUM. Pool Operator only lists a pool. Package id blake2b-pool-balance. It does not replace datum or routehash-gateway. Writes only Pool Host, port, and pubkey.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
