import { chooserJson } from '../fileModels/chooser.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'
import { configMeta } from './configMeta'

const { InputSpec, Value } = sdk

const spec = InputSpec.of({
  opt_in: Value.toggle({
    name: i18n('Opt in'),
    description: i18n(
      'When on, this service may change Pool Host on the DATUM whose API address you saved. When off, it leaves Pool Host where it is. A move is written only when the gateway API address and admin password are saved and Allow API Config Writes is on. Use this only for your own mining DATUM. Leave it off on a DATUM that is a public pool. Opting that pool in would send every miner on it to some other pool.',
    ),
    default: false,
  }),
  ceiling_percent: Value.text({
    name: i18n('Local max percent'),
    description: i18n('This is not a timer and it is not a cap on your rig TH/s. The 30-minute wait is separate. Leave empty and this machine stores 30 percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A pool publishes how much of the network it will hold. This number is how much of the network you will help one pool hold. This machine uses the lower of the two. There is no blank setting that means no limit. The global XBT hashrate only turns the percent into TH. If adding your Rig TH/s would put a pool over that TH, this service tries the next pool. House Pool is not held to this number.'),
    required: false,
    default: '',
  }),
  rig_th: Value.number({
    name: i18n('Rig TH/s'),
    description: i18n('Advertised TH/s of the ASICs on this gateway. This is the amount added when checking whether a pool still has room. It does not change by itself. Zero stays on the saved Pool Host.'),
    required: false,
    default: 0,
    integer: false,
    min: 0,
    max: 1000000,
    step: 0.01,
    units: null,
    placeholder: null,
    warning: null,
  }),
  pinned: Value.toggle({
    name: i18n('Pin Pool Host'),
    description: i18n(
      'While pinned, Pool Host is not moved. Clear the pin and the next choice can return to your home Pool Host. A file named pin in the service data directory pins as well.',
    ),
    default: false,
  }),
  relays: Value.textarea({
    name: i18n('Relay URLs'),
    description: i18n(
      'The list starts with wss://relay.routehash.com. Add your own relay on the next line, as ws:// or wss://. This list does not grow by itself. This machine reads pools from every address in this list. Other machines see your pool when they already read one of those relays. A wss URL needs a certificate for that name. On Start9 install Nostr RS Relay, package nostr-rs-relay, then copy the Relay websocket address from Interfaces. Start9 trusts its own certificate on the LAN. Turn Public on for StartTunnel, or forward the nostr port on your router, when other people should read your relay. On Umbrel install Nostr Relay from the App Store under Social and copy the relay URL it shows. On a LAN that URL is often ws:// and port 4848. A Nostr client reads a relay. This list stores the relay address, not the client. Leave Restrict Access alone. Saving it while Authorized Pubkeys is empty locks every publish. Kinds 30080 and 30081 must stay allowed.',
    ),
    required: false,
    default: 'wss://relay.routehash.com',
    minRows: 4,
  }),
})

function relayLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

export const machine = sdk.Action.withInput(
  'machine',
  configMeta(
    'This machine',
    'Node Runner only. Opt in, your local max percent, the rig size, and the relays for the DATUM your own ASICs use. Do not opt in a public pool DATUM. ASICs stay on your DATUM gateway. Each pool publishes its own cap. This screen does not set the pool cap.',
  ),
  spec,
  async () => {
    const cfg = await chooserJson.read().once()
    return {
      opt_in: cfg?.opt_in ?? false,
      ceiling_percent: cfg?.ceiling_percent ?? '',
      rig_th: cfg?.rig_th ?? 0,
      pinned: cfg?.pinned ?? false,
      relays: (cfg?.relays ?? ['wss://relay.routehash.com']).join('\n'),
    }
  },
  async ({ effects, input }) => {
    const ceiling = (input.ceiling_percent ?? '').trim()
    const ceilingNumber = Number(ceiling)
    if (ceiling !== '' && Number.isFinite(ceilingNumber) && ceilingNumber > 30) {
      throw new Error('Local max percent cannot be above 30.')
    }
    await chooserJson.merge(effects, {
      opt_in: input.opt_in ?? false,
      ceiling_percent: ceiling,
      rig_th: input.rig_th ?? 0,
      pinned: input.pinned ?? false,
      relays: relayLines(input.relays ?? ''),
    })
  },
)
