import { i18n } from './i18n'
import { sdk } from './sdk'

export const uiPort = 7156

export const setInterfaces = sdk.setupInterfaces(async ({ effects }) => {
  const web = sdk.MultiHost.of(effects, 'ui')
  const webOrigin = await web.bindPort(uiPort, {
    protocol: 'http',
    preferredExternalPort: uiPort,
  })
  const ui = sdk.createInterface(effects, {
    name: i18n('Web Interface'),
    id: 'ui',
    description: i18n('Open this page and pick Node Runner or Pool Operator. A node runner completes only the local DATUM form. A pool operator only lists a pool, unless they also run a second DATUM for their own mining.'),
    type: 'ui',
    masked: false,
    schemeOverride: null,
    username: null,
    path: '',
    query: {},
  })
  return [await webOrigin.export([ui])]
})
