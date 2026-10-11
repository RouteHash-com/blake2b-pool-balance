import { actions } from '../actions'
import { restoreInit } from '../backups'
import { setDependencies } from '../dependencies'
import { defaults, chooserJson } from '../fileModels/chooser.json'
import { setInterfaces } from '../interfaces'
import { sdk } from '../sdk'
import { versionGraph } from '../versions'

const seedConfig = sdk.setupOnInit(async (effects) => {
  const existing = await chooserJson.read().once()
  if (!existing) {
    await chooserJson.write(effects, defaults)
  }
})

export const init = sdk.setupInit(restoreInit, versionGraph, setInterfaces, setDependencies, actions, seedConfig)

export const uninit = sdk.setupUninit(versionGraph)
