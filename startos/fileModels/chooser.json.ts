import { FileHelper, z } from '@start9labs/start-sdk'
import { sdk } from '../sdk'

const HOUSE_PUBKEY =
  'b1ccb80129763858d52249e4fef4f9d6aff97921543abf0559e03819a03aab1093872ef7b8f0481635d0221485379948a812c3d2ffcec3fe7cbc4f8ccec1d735'

const homeListen = z.object({
  host: z.string().catch(''),
  port: z.number().catch(28915),
  pubkey: z.string().catch(''),
})

const houseListen = z.object({
  host: z.string().catch('pool.routehash.com'),
  port: z.number().catch(28915),
  pubkey: z.string().catch(HOUSE_PUBKEY),
})

export const shape = z.object({
  algorithm: z.literal('blake2b').catch('blake2b'),
  opt_in: z.boolean().catch(false),
  ceiling_percent: z.string().catch(''),
  rig_th: z.number().catch(0),
  pinned: z.boolean().catch(false),
  relays: z.array(z.string()).catch(['wss://relay.routehash.com']),
  home_from_gateway: z.boolean().catch(false),
  home: homeListen.catch({ host: '', port: 28915, pubkey: '' }),
  house: houseListen.catch({
    host: 'pool.routehash.com',
    port: 28915,
    pubkey: HOUSE_PUBKEY,
  }),
  gateway: z
    .object({
      url: z.string().catch(''),
      password: z.string().catch(''),
    })
    .catch({ url: '', password: '' }),
  node: z
    .object({
      url: z.string().catch(''),
      user: z.string().catch(''),
      password: z.string().catch(''),
    })
    .catch({ url: '', user: '', password: '' }),
})

export const defaults = {
  algorithm: 'blake2b' as const,
  opt_in: false,
  ceiling_percent: '',
  rig_th: 0,
  pinned: false,
  relays: ['wss://relay.routehash.com'],
  home_from_gateway: false,
  home: { host: '', port: 28915, pubkey: '' },
  house: {
    host: 'pool.routehash.com',
    port: 28915,
    pubkey: HOUSE_PUBKEY,
  },
  gateway: { url: '', password: '' },
  node: { url: '', user: '', password: '' },
}

export const chooserJson = FileHelper.json(
  {
    base: sdk.volumes.main,
    subpath: 'chooser.json',
  },
  shape,
)
