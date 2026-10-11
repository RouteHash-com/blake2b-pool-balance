import { defaults, chooserJson } from './fileModels/chooser.json'
import { i18n } from './i18n'
import { uiPort } from './interfaces'
import { sdk } from './sdk'

export const main = sdk.setupMain(async ({ effects }) => {
  console.info(i18n('Starting Blake2b Pool Balance'))

  const existing = await chooserJson.read().once()
  if (!existing) {
    await chooserJson.write(effects, defaults)
  }

  const sub = sdk.SubContainer.of(
    effects,
    { imageId: 'main' },
    sdk.Mounts.of().mountVolume({
      volumeId: 'main',
      subpath: null,
      mountpoint: '/data',
      readonly: false,
    }),
    'chooser-data',
  )

  return sdk.Daemons.of(effects).addDaemon('chooser', {
    subcontainer: sub,
    exec: {
      command: ['python3', '/opt/routehash/pool_balance_loop.py', '--data', '/data', '--ui', String(uiPort)],
    },
    ready: {
      display: i18n('Chooser'),
      fn: () =>
        sdk.healthCheck.checkPortListening(effects, uiPort, {
          successMessage: i18n('The chooser loop is running'),
          errorMessage: i18n('The chooser page is unreachable'),
        }),
    },
    requires: [],
  })
})
