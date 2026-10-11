import { sdk } from '../sdk'
import { gateway } from './gateway'
import { home } from './home'
import { house } from './house'
import { machine } from './machine'
import { node } from './node'

export const actions = sdk.Actions.of().addAction(machine).addAction(home).addAction(house).addAction(gateway).addAction(node)
