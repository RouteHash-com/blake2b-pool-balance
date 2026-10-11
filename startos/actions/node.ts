import { chooserJson } from '../fileModels/chooser.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'
import { configMeta } from './configMeta'

const { InputSpec, Value } = sdk

const spec = InputSpec.of({
  url: Value.text({
    name: i18n('Node RPC address'),
    description: i18n(
      'Optional. JSON-RPC of the Knots or Bitcoin Core node on this machine, such as http://10.0.3.1:8332. Use the RPC port that node shows. When this address is set, the global XBT hashrate comes from that node. When it is blank, the total comes from mempool.guide. This is not the DATUM gateway and not a Nostr relay.',
    ),
    required: false,
    default: '',
  }),
  user: Value.text({
    name: i18n('RPC user'),
    description: i18n('RPC username for that node, the rpcuser in its settings. Leave blank when the address is blank. Not used when the total comes from mempool.guide.'),
    required: false,
    default: '',
  }),
  password: Value.text({
    name: i18n('RPC password'),
    description: i18n('RPC password for that node, the rpcpassword in its settings. Leave blank to keep the saved password. Leave it blank when the address is blank.'),
    required: false,
    default: '',
    masked: true,
  }),
})

export const node = sdk.Action.withInput(
  'node',
  configMeta(
    'Global Blake2b Network',
    'Reads the global XBT hashrate from the Knots or Bitcoin Core node on this machine. When the RPC address is set, the total comes from that node. When it is blank, the total comes from mempool.guide. Pool size still comes from mempool.guide by coinbase tag.',
  ),
  spec,
  async () => {
    const cfg = await chooserJson.read().once()
    return {
      url: cfg?.node.url ?? '',
      user: cfg?.node.user ?? '',
      password: cfg?.node.password ?? '',
    }
  },
  async ({ effects, input }) => {
    const current = await chooserJson.read().once()
    const password = (input.password ?? '').trim()
    await chooserJson.merge(effects, {
      node: {
        url: (input.url ?? '').trim(),
        user: (input.user ?? '').trim(),
        password: password || current?.node?.password || '',
      },
    })
  },
)
