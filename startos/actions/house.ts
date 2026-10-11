import { chooserJson } from '../fileModels/chooser.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'
import { configMeta } from './configMeta'

const { InputSpec, Value } = sdk

const spec = InputSpec.of({
  host: Value.text({
    name: i18n('Pool Host'),
    description: i18n('Already pool.routehash.com. This is where the gateway Pool Host goes when no capped pool has room. You can replace it. Clear it to turn the fallback off.'),
    required: false,
    default: 'pool.routehash.com',
  }),
  port: Value.number({
    name: i18n('Port'),
    description: i18n('Already 28915. This is the port the gateway uses for House Pool. Never put this port on an ASIC.'),
    required: false,
    default: 28915,
    integer: true,
    min: 1,
    max: 65535,
    step: 1,
    units: null,
    placeholder: null,
    warning: null,
  }),
  pubkey: Value.text({
    name: i18n('Pubkey'),
    description: i18n('Already the House Pool pubkey, 128 hex characters. The gateway needs this pubkey to connect to House Pool. Leave it unless you replace the host.'),
    required: false,
    default:
      'b1ccb80129763858d52249e4fef4f9d6aff97921543abf0559e03819a03aab1093872ef7b8f0481635d0221485379948a812c3d2ffcec3fe7cbc4f8ccec1d735',
  }),
})

export const house = sdk.Action.withInput(
  'house',
  configMeta(
    'House Pool',
    'House Pool is the last stop, already filled in. Your ASICs stay on your gateway. When home does not fit and every receiving pool would go over its cap, this service points the gateway Pool Host here so the rig keeps hashing. House Pool is not held to a percent. After 30 minutes here, it stays until home fits again. A pool that frees up does not pull the rig off House Pool. Clear the host to turn that fallback off.',
  ),
  spec,
  async () => {
    const cfg = await chooserJson.read().once()
    return {
      host: cfg?.house.host ?? 'pool.routehash.com',
      port: cfg?.house.port ?? 28915,
      pubkey:
        cfg?.house.pubkey ??
        'b1ccb80129763858d52249e4fef4f9d6aff97921543abf0559e03819a03aab1093872ef7b8f0481635d0221485379948a812c3d2ffcec3fe7cbc4f8ccec1d735',
    }
  },
  async ({ effects, input }) => {
    await chooserJson.merge(effects, {
      house: {
        host: (input.host ?? 'pool.routehash.com').trim(),
        port: input.port ?? 28915,
        pubkey: (input.pubkey ?? '').trim(),
      },
    })
  },
)
