/**
 * A contract refused for an apiVersion outside ODCS is explained in the user's
 * language, from the code and param of either answer: the create route's 422
 * (`detail: [{type, ctx}]`) or the update route's 400 (`detail: {code, params}`).
 */
import { describe, it, expect, afterEach } from 'vitest'
import i18n from '@/i18n/config'
import { odcsApiVersionErrorText } from './odcs-api-version-error'

const CREATE_422 = {
  detail: [{
    type: 'odcs_api_version_unsupported', loc: ['body', 'apiVersion'],
    msg: 'apiVersion 9.9 is not an ODCS version', ctx: { api_version: '9.9' },
  }],
}
const UPDATE_400 = {
  detail: {
    code: 'odcs_api_version_unsupported', message: 'apiVersion v9.9 is not an ODCS version',
    params: { api_version: 'v9.9' },
  },
}

describe('odcsApiVersionErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('explains the create refusal, also from the raw text', async () => {
    await i18n.changeLanguage('pt')
    expect(odcsApiVersionErrorText(JSON.stringify(CREATE_422), i18n.t)).toBe(
      'O apiVersion 9.9 não é uma versão ODCS. Use uma das versões ODCS, por exemplo v3.1.0.',
    )
  })

  it('explains the update refusal', () => {
    expect(odcsApiVersionErrorText(UPDATE_400, i18n.t)).toBe(
      'apiVersion v9.9 is not an ODCS version. Use one of the ODCS versions, for example v3.1.0.',
    )
  })

  it('is null for any other error', () => {
    expect(odcsApiVersionErrorText({ detail: 'Not found' }, i18n.t)).toBeNull()
    expect(odcsApiVersionErrorText('not json', i18n.t)).toBeNull()
    expect(odcsApiVersionErrorText({ detail: [{ type: 'missing' }] }, i18n.t)).toBeNull()
  })
})
