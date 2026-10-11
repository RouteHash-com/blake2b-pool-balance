import { chooserJson } from '../fileModels/chooser.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'
import { configMeta } from './configMeta'

const { InputSpec, Value } = sdk

const spec = InputSpec.of({
  host: Value.text({
    name: i18n('Pool Host'),
    description: i18n('Leave this blank. This service copies the Pool Host already saved on your DATUM gateway. That copy needs the gateway API address and admin password under Local gateway. Type a host only when you want a different home.'),
    required: false,
    default: '',
  }),
  port: Value.number({
    name: i18n('Port'),
    description: i18n('Filled from the gateway when Pool Host is left blank. This is the pool port, not an ASIC port. 28915 is only the placeholder until that copy happens.'),
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
    description: i18n('128 hex characters from that pool. Leave this blank when Pool Host is blank. The gateway copy fills it. Type it only when you set the host yourself.'),
    required: false,
    default: '',
  }),
})

export const home = sdk.Action.withInput(
  'home',
  configMeta('Home Pool Host', 'Leave Pool Host blank. About once a minute this service reads Pool Host, port, and pubkey from your DATUM gateway and keeps that as home. It does not wait for a DATUM restart. The read needs the gateway API address and admin password. A typed host replaces that copy. Clearing a host that was already saved does not read the gateway again.'),
  spec,
  async () => {
    const cfg = await chooserJson.read().once()
    return {
      host: cfg?.home.host ?? '',
      port: cfg?.home.port ?? 28915,
      pubkey: cfg?.home.pubkey ?? '',
    }
  },
  async ({ effects, input }) => {
    const previous = await chooserJson.read().once()
    const typed = (input.host ?? '').trim()
    const previousHost = (previous?.home.host ?? '').trim()
    await chooserJson.merge(effects, {
      home: {
        host: typed,
        port: input.port ?? 28915,
        pubkey: (input.pubkey ?? '').trim(),
      },
      home_from_gateway: Boolean(typed) || Boolean(previousHost),
    })
  },
)
