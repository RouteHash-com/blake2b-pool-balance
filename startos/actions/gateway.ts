import { chooserJson } from '../fileModels/chooser.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'
import { configMeta } from './configMeta'

const { InputSpec, Value } = sdk

const spec = InputSpec.of({
  url: Value.text({
    name: i18n('API address'),
    description: i18n(
      'On the gateway service open Web Interface. Paste one Local https address from that list. The Listen Port on the API screen is the port inside the gateway. This is not the Node RPC address. On this screen a blank address clears the saved one.',
    ),
    required: false,
    default: '',
  }),
  password: Value.text({
    name: i18n('Admin password'),
    description: i18n(
      'Paste the Admin Password from the API screen on the gateway. The dashboard user is admin. Turn on Allow API Config Writes on that same API screen. This service cannot turn that switch on. On this screen a blank password clears the saved one, and then this service does not write.',
    ),
    required: false,
    default: '',
    masked: true,
  }),
})

export const gateway = sdk.Action.withInput(
  'gateway',
  configMeta(
    'Local gateway',
    'Where this service writes Pool Host, and only for your own mining DATUM. Do not put a public pool DATUM here. That would send every miner on that pool to some other pool. It posts only host, port, and pubkey, and only after you opt in. Leave the address blank and it does not write. Pool operators list a pool on the service page instead.',
  ),
  spec,
  async () => {
    const cfg = await chooserJson.read().once()
    return {
      url: cfg?.gateway.url ?? '',
      password: cfg?.gateway.password ?? '',
    }
  },
  async ({ effects, input }) => {
    await chooserJson.merge(effects, {
      gateway: {
        url: (input.url ?? '').trim(),
        password: input.password ?? '',
      },
    })
  },
)
