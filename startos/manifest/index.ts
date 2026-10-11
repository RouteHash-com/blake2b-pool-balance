import { setupManifest } from '@start9labs/start-sdk'
import { long, short } from './i18n'

export const manifest = setupManifest({
  id: 'blake2b-pool-balance',
  title: 'Blake2b Pool Balance',
  license: 'MIT',
  packageRepo: 'https://github.com/RouteHash-com/blake2b-pool-balance',
  upstreamRepo: 'https://github.com/RouteHash-com/blake2b-pool-balance',
  marketingUrl: 'https://app.routehash.com/pool/connect',
  donationUrl: null,
  description: { short, long },
  volumes: ['main'],
  images: {
    main: {
      source: {
        dockerBuild: {
          dockerfile: 'Dockerfile',
          workdir: '.',
        },
      },
      arch: ['x86_64', 'aarch64'],
    },
  },
  dependencies: {},
})
