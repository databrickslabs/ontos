import { describe, expect, it } from 'vitest';
import { buildContractMetadataUpdate } from './contract-metadata-payload';

const sent = (payload: any) => JSON.parse(JSON.stringify(buildContractMetadataUpdate(payload)));

describe('buildContractMetadataUpdate', () => {
  it('leaves tags out when the dialog did not send them (keeps the contract tags)', () => {
    expect(sent({ name: 'Orders', description: { purpose: 'p' } })).not.toHaveProperty('tags');
  });

  it('sends an empty list when the dialog removed every tag', () => {
    expect(sent({ name: 'Orders', tags: [] }).tags).toEqual([]);
  });

  it('sends the selection when the dialog changed it', () => {
    expect(sent({ name: 'Orders', tags: ['ns/a'] }).tags).toEqual(['ns/a']);
  });

  it('passes the domain assignment the dialog sends', () => {
    expect(sent({ domainIds: ['d1', 'd2'], primaryDomainId: 'd2' })).toMatchObject({
      domainIds: ['d1', 'd2'], primaryDomainId: 'd2',
    });
  });

  it('maps the description fields', () => {
    expect(sent({ description: { purpose: 'p', usage: 'u', limitations: 'l' } })).toMatchObject({
      descriptionPurpose: 'p', descriptionUsage: 'u', descriptionLimitations: 'l',
    });
  });
});
