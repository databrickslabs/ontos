/**
 * The PUT body the contract details page sends after the metadata dialog is saved.
 *
 * `tags` is passed through as the dialog sent it: missing keeps the contract's
 * tags, `[]` removes them all (#1435). Defaulting it to `[]` would remove every
 * tag on any metadata edit, since the dialog leaves `tags` out when the
 * selection wasn't changed.
 */
export function buildContractMetadataUpdate(payload: any) {
  return {
    name: payload.name,
    version: payload.version,
    status: payload.status,
    owner_team_id: payload.owner_team_id,
    project_id: payload.project_id,
    tenant: payload.tenant,
    // The dialog sends the multi-domain assignment; the legacy single domain is kept for older callers.
    domainIds: payload.domainIds,
    primaryDomainId: payload.primaryDomainId,
    domainId: payload.domainId,
    descriptionUsage: payload.description?.usage,
    descriptionPurpose: payload.description?.purpose,
    descriptionLimitations: payload.description?.limitations,
    tags: payload.tags,
  }
}
