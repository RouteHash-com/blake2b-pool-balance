import { i18n } from '../i18n'

export const configGroup = i18n('Config')

export function configMeta(name: Parameters<typeof i18n>[0], description: Parameters<typeof i18n>[0]) {
  return {
    name: i18n(name),
    description: i18n(description),
    warning: null,
    allowedStatuses: 'any' as const,
    group: configGroup,
    visibility: 'enabled' as const,
  }
}
