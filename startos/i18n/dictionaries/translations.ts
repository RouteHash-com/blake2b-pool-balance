import dict, { LangDict } from './default'

const en = Object.fromEntries(
  Object.entries(dict).map(([english, id]) => [id, english]),
) as LangDict

export default {
  es_ES: en,
  de_DE: en,
  pl_PL: en,
  fr_FR: en,
} satisfies Record<string, LangDict>
