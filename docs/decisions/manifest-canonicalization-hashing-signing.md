# Manifest Canonicalization, Hashing and Signing

**Date**: 2026-10-09
**Status**: Proposed
**PRD**: `docs/prds/prd-signed-data-product-manifest.md`
**Issues**: _to be linked once filed_

## Context

The Signed Data Product Manifest must produce the same bytes (and therefore the same hash) for the same product content, in any process, on any machine, and in an independent verifier that does not import Ontos code. It must also be signed in a way that a consumer can verify with a public key alone. This ADR fixes the byte-level rules so that the backend, the offline verifier and any future implementation (another language, an ODF adapter) agree.

## Decision 1: Canonical JSON (strict subset of RFC 8785)

Manifests are serialized as JSON following [RFC 8785 (JCS)](https://www.rfc-editor.org/rfc/rfc8785), restricted to a subset without floating-point numbers, so that no number formatting rule is needed.

**Allowed values**

| Type | Rule |
|---|---|
| Object | Keys are strings. Members are sorted by the **UTF-16 code units** of the key (RFC 8785 §3.2.3). Duplicate keys are rejected |
| Array | Order is preserved as given. Producers are responsible for sorting (see Decision 6) |
| String | UTF-8. Escaped exactly as ECMAScript `JSON.stringify`: `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t`, other code points below U+0020 as `\u00xx` (lowercase hex); everything else literal (including U+2028/U+2029 and non-ASCII). Lone surrogates are rejected |
| Integer | Only integers with absolute value below 2^53. Serialized in decimal without leading zeros, exponent or fraction |
| Boolean / null | `true`, `false`, `null` |

**Normalization before serialization**

- Floats are **rejected**. The canonicalizer raises `CanonicalizationError` (`float_not_allowed`, with the JSON path of the value) for any float, including integral ones (`1.0`, `-0.0`, `1e3`) and `NaN`, `Infinity` and `-Infinity`. It never converts a float.
- Decimal values are carried as the schema defines them, converted by the manifest builder before canonicalization: as strings in a fixed format (quality scores: two decimals, `"0.95"`) or as scaled integers (`9500` basis points). A float that reaches the canonicalizer is therefore a builder bug, and the seal fails instead of producing a hash another implementation could not reproduce.
- A non-integer number without a declared format (for example a numeric `customProperties` value) makes the seal fail with `float_not_allowed` and its path, rather than being formatted by a language-specific rule. Declaring a format for that field (string or scaled integer) fixes it.
- Datetimes become ISO-8601 strings in UTC with a `Z` suffix and no fractional seconds unless present in the source (`2026-10-09T12:00:00Z`).
- UUIDs become lowercase hyphenated strings. Enums become their string values. Bytes are not allowed.
- No whitespace is emitted. The output is UTF-8 without BOM.

**Implementation note.** Python's `json.dumps(..., sort_keys=True)` sorts by code point, which differs from UTF-16 order for keys mixing characters above U+FFFF and in U+E000–U+FFFF. The implementation sorts keys with `key.encode("utf-16-be")` and is tested against the RFC 8785 Appendix B string vectors.

**Why a subset:** any conformant JCS library produces identical bytes for this input, so other implementations can use off-the-shelf JCS tooling, and no verifier depends on one language's float formatting.

**Tests:** the RFC 8785 Appendix B string and key-ordering vectors; a float anywhere in content (top level, nested object, array, integral or not) raises `float_not_allowed` with its path; the same golden vectors in the backend and the offline verifier.

## Decision 2: Hash function and encoding

- Hashes are encoded as [multihash](https://github.com/multiformats/multihash) and rendered with [multibase](https://github.com/multiformats/multibase) **base16 lowercase** (prefix `f`).
- **Default: `sha2-256`** (multihash code `0x12`, length `0x20`). A digest renders as `f1220` followed by 64 hex characters.
- The verifier also accepts **`sha3-256`** (code `0x16`, rendered `f1620…`). Any other code is rejected with `unsupported_hash_alg`.

**Rationale**

- SHA-256 is native in Databricks SQL (`sha2(expr, 256)`), in browsers (WebCrypto) and in standard tooling (`sha256sum`). SHA-3 is not available in Databricks SQL or Spark SQL built-ins, nor in WebCrypto.
- Multihash makes the algorithm explicit, so a later move to SHA-3 (for example to align with Open Data Fabric, which uses SHA3-256 multihashes and recommends base16, ODF RFC-012) does not break existing manifests.

`H(x)` below means `multihash_sha2_256(canonical_json(x))`.

## Decision 3: Three hashes and the signature input

| Value | Computed over |
|---|---|
| Section digests | `H(section)` for `odps`, each `odcs[contract_id]`, `semantic_links`, `owners`, `tags`, `assets` |
| `content_hash` | `H(content)` where `content = {definition, evidence}` |
| `definition_digest` | `H(content.definition)`, used to report "content modified" independently of evidence |
| `manifest_hash` | `H(envelope)` with the `manifest_hash` and `signature` members removed |
| `signature.value` | Ed25519 over the UTF-8 bytes of `"ontos-manifest-v1:" + manifest_hash`, base64url without padding |

Attestations follow the same pattern with their own envelope, `attestation_hash`, and the signing prefix `"ontos-attestation-v1:"`. The signed key list (Decision 7) uses `"ontos-keylist-v1:"` and the chain checkpoint (Decision 9) `"ontos-checkpoint-v1:"`. The distinct prefixes are **domain separation**: a valid signature of one kind can never be replayed as a signature of another.

## Decision 4: Envelope

```json
{
  "manifest_version": "ontos.manifest/v1",
  "subject": {"product_id": "…", "version_family_id": "…", "version": "1.2.0"},
  "content": {"definition": {}, "evidence": {"assets": [], "quality": {}}},
  "digests": {"definition": "f1220…", "odps": "f1220…", "odcs": {"<contract_id>": "f1220…"},
              "semantic_links": "f1220…", "owners": "f1220…", "tags": "f1220…", "assets": "f1220…"},
  "content_hash": "f1220…",
  "chain": {"sequence": 3, "previous_manifest_hash": "f1220…"},
  "publisher": {"instance": "<app name>", "workspace_id": "…", "key_id": "ed25519:…"},
  "sealed_at": "2026-10-09T12:00:00Z",
  "sealed_by": "user@example.com",
  "seal_reason": "publish",
  "manifest_hash": "f1220…",
  "signature": {"alg": "Ed25519", "key_id": "ed25519:…", "value": "<base64url>"}
}
```

`seal_reason` is one of `publish`, `certify`, `manual`, `backfill`. Attestation `attestation_type` is one of `published`, `unpublished`, `certified`, `decertified`.

## Decision 5: Chain rules

- Manifests form one chain per **`version_family_id`**, so all versions of a product share a history. Attestations form one chain per product.
- The first manifest of a family has `sequence = 0` and `previous_manifest_hash = null`. Each new manifest increments `sequence` and references the latest manifest of the family.
- **Dedupe:** if the latest manifest of the product already has the same `content_hash`, no manifest is created. The existing one is returned and only an attestation is appended.
- Forks are rejected by unique constraints on `(version_family_id, sequence)` and `(version_family_id, previous_manifest_hash)`. A concurrent writer that loses the race retries once against the new head.
- Append-only behavior is enforced by the repository (insert and read only) and by the constraints above. Database triggers are not used, to keep SQLite tests and Postgres/Lakebase portable.

## Decision 6: Content normalization

**Excluded from `content`** (lifecycle or presentation state, captured by attestations or the audit trail): `status` of products, ports, datasets and contracts; `publication_scope`; `published_at`/`published_by`; all `certification_*` and `maturity_*` fields; `created_at`/`updated_at`; `draft_owner_id`; `change_summary`; database row ids that are not stable entity ids.

**Sort orders**

| Collection | Sort key |
|---|---|
| ODPS `inputPorts`, `outputPorts` | (`name`, `version`) |
| ODPS `support` | (`channel`, `url`) |
| ODPS/ODCS `team.members` | (`username`, `role`) |
| `customProperties` | `property` |
| `authoritativeDefinitions` | (`type`, `url`) |
| ODPS `datasets` and their tables/views | `name` |
| ODCS `schema`, `properties` | `name` |
| ODCS `quality` | (`type`, `name`, `rule`) |
| ODCS `servers` | `server` |
| Domains | `id` (primary domain flagged) |
| Semantic links | `iri` (with `label`) |
| Tags | rendered as `namespace/name[=value]`, sorted |
| Evidence `assets` | (`port`, `asset_identifier`) |

Sealing needs a **strict** mode of the ODPS export that raises instead of silently omitting sections. Today `DataProductsManager.build_odps_export` logs a warning and drops `datasets` when the dataset hierarchy fails to load; a sealed manifest must never be built from such a partial export, which would produce a different but valid-looking hash.

## Decision 7: Keys

- Algorithm: **Ed25519**, via the `cryptography` package already pinned in `src/requirements.txt`.
- `key_id = "ed25519:" + first 16 hex characters of sha256(raw 32-byte public key)`.
- Providers implement a small `KeyProvider` interface:
  - **local**: a PEM private key at `MANIFEST_LOCAL_KEY_PATH` (default `~/.ontos/manifest_signing_ed25519.pem`), created with mode `0600` if missing. For development and tests only.
  - **databricks_secrets**: a PEM private key stored in a Databricks secret (`MANIFEST_SECRET_SCOPE` / `MANIFEST_SECRET_KEY`), read with the app service principal. Values returned base64-encoded by the API are decoded before loading.
- Private keys are never written to the database, logs or Git. The app stores **public keys only** (`manifest_signing_keys`), registering a key the first time it signs.
- **Rotation:** replacing the secret produces a new `key_id` on first use. Previously registered public keys remain available through `GET /api/manifests/keys` (status `retired`, with `retired_at`), so older manifests keep verifying.
- **Key status.** Each key is `active` (signs new manifests), `retired` (superseded by rotation, not compromised: its signatures stay valid) or `revoked` (compromised or withdrawn, with `revoked_at` and a reason). An admin revokes a key with `POST /api/manifests/keys/{key_id}/revoke`; revoking the active key stops sealing until a new key is provisioned (seals fail as in the PRD, "When sealing fails"). Status changes are appended, never edited.
- **Signed key list.** `GET /api/manifests/keys` returns `{keys: [{key_id, public_key, status, created_at, retired_at, revoked_at, reason}], issued_at, signature}`, signed with an active, non-revoked key over `"ontos-keylist-v1:" + H(list without signature)`. Exports of manifests carry the key list. The producer can publish the same list through the out-of-band channel it uses for pinning (PRD, "Trust model"); a verifier that pins keys accepts a key list only when it is signed by a pinned key.
- **Verifier outcome.** A signature by a key whose status is `revoked` reports `revoked`, whatever the manifest's `sealed_at`: `sealed_at` is written by the signer, so it can't tell a genuine old manifest from one forged with the stolen key. A revoked key's manifests are re-signed only by sealing again (`seal_reason = manual` or `backfill`) with the new key. The verifier also reports the `issued_at` of the key list it used, so an auditor knows how recent its revocation information is.
- **Limits in v1.** Revocation reaches the verifier only through the key list it is given. A verifier that only has an older list, or an attacker who controls the instance and withholds the list, can hide a revocation; the out-of-band channel and the reported `issued_at` are the mitigation. Online status checks (OCSP-like), a transparency log and automatic distribution are not part of v1.

## Decision 8: Failure semantics and enablement

- Feature flag `MANIFEST_SIGNING_ENABLED` (default `false`). When off, lifecycle hooks are no-ops and manifest endpoints return `409 signing_disabled`.
- Lifecycle hooks (publish, certify and related paths) are **fail-open** by default: they run after the domain commit in their own unit of work; on error they roll back only their own writes, log, record `MANIFEST_SEAL_FAILED` in the audit log and a row in `data_product_seal_failures`, and the product's seal state becomes `unsealed` with the reason. The user action succeeds.
- With `MANIFEST_SEAL_REQUIRED=true`, publish and certify are **fail-closed**: the manifest is built and signed before the domain commit and written in the same transaction; a sealing error rolls back the action and returns `409 manifest_seal_failed`. `unpublished` and `decertified` attestations stay fail-open.
- The manual seal endpoint is **fail-closed**: canonicalization errors return `422`, key-provider errors `503`.

## Decision 9: Verification outcomes and chain completeness

Verification reports independent flags rather than a single boolean:

| Flag | Meaning |
|---|---|
| `signature_valid` | Signature matches `manifest_hash` for a known public key |
| `trust_anchor` | `pinned`, `instance` or `none` (PRD, "Trust model") |
| `key_status` | `active`, `retired`, `revoked` or `unknown`, from the key list; `revoked` makes the verification fail |
| `manifest_hash_valid` | Recomputed envelope hash equals `manifest_hash` |
| `content_hash_valid` | Recomputed content and section digests match |
| `chain_valid` | `previous_manifest_hash` resolves and `sequence` is consecutive |
| `chain_complete` | `complete` or `incomplete`, against a signed head checkpoint (below) |
| `is_head` | The verified manifest is the head named by the checkpoint (otherwise a newer version exists) |
| `content_drift` | (live only) the current definition differs from the sealed one, per section |
| `data_drift` | (live only) the Delta version of an asset moved since the seal |
| `schema_drift` | (live only) the physical schema digest differs from the sealed one |

The offline verifier evaluates all but the live checks. The Ontos endpoint adds them.

**Head checkpoint.** `chain_valid` alone can't detect a chain cut short: a prefix of a valid chain is itself valid, and an older manifest can be shown as the latest. The producer therefore issues a signed checkpoint of the chain head:

```json
{
  "checkpoint_version": "ontos.checkpoint/v1",
  "version_family_id": "…",
  "sequence": 3,
  "head_manifest_hash": "f1220…",
  "attestation_heads": {"<product_id>": {"sequence": 5, "attestation_hash": "f1220…"}},
  "issued_at": "2026-10-09T12:00:00Z",
  "signature": {"alg": "Ed25519", "key_id": "ed25519:…", "value": "<base64url>"}
}
```

- It is signed over `"ontos-checkpoint-v1:" + H(checkpoint without signature)` with an active key, when the chain is read (`GET /api/data-products/{id}/manifests`) and in every export of the chain. It is a statement by the instance that, at `issued_at`, the head of the family's chain had that `sequence` and hash; nothing new is stored.
- The verifier checks the checkpoint signature under the same anchor and key status rules as manifests, then that the chain it was given starts at `sequence = 0` and ends at `head_manifest_hash` with that `sequence`. Same for each attestation chain in `attestation_heads`.
- It reports `chain_complete = incomplete` when it has no checkpoint, when the chain stops before the checkpoint's head (a prefix), or when it starts after sequence 0. `is_head` is false when the verified manifest is not the checkpoint's head.
- An older checkpoint only proves completeness up to its own `issued_at`. The verifier reports `issued_at`, and accepts an expected head (`--expect-head <manifest_hash>` or `<sequence>`) obtained through a trusted channel; a checkpoint behind it reports `incomplete`. Freshness beyond that (a transparency log or witness) is not part of v1.

`schema_drift` is an **integrity** signal: the physical table changed since the seal. It is distinct from contract-vs-catalog drift (#736), which compares a contract with the live catalog. When that analysis is available, its result is sealed as part of `evidence.assets[].contract_drift` (severity and suggested bump), so it is covered by `content_hash` but never recomputed by the verifier.

## Alternatives considered

| Alternative | Why not |
|---|---|
| HMAC signatures | Verification would require the shared secret, defeating independent verification |
| SHA3-256 as default | Not available in Databricks SQL, Spark SQL or WebCrypto; multihash keeps it available as an accepted algorithm |
| Canonical YAML | No established canonicalization standard; JSON + JCS has one |
| Full JCS library dependency | Restricting numbers to integers removes the only hard part of JCS; no new dependency needed |
| Floats with RFC 8785 number serialization | Every verifier would need the exact ECMAScript algorithm and its test vectors; sealed content has no value that needs a float |
| Revocation by `sealed_at` (only manifests sealed after `revoked_at` are revoked) | `sealed_at` is written by the signer, so a stolen key can backdate it |
| Lifecycle status inside the content hash | Every status transition would change the hash without changing the product, and duplicate the role of the Governance Event Stream (#421) |
| Database triggers for immutability | Not portable to the SQLite test setup; constraints plus repository surface are sufficient for v1 |

## Consequences

- Any implementation that follows this ADR can verify Ontos manifests with standard JCS, multihash and Ed25519 tooling.
- Adding a field to `content` changes `content_hash` for subsequent seals; such changes must bump `manifest_version`.
- Products whose exports change shape across Ontos releases will produce a new manifest on their next seal; dedupe compares hashes, not versions.

## Open questions

- Should `manifest_version` changes be accompanied by a migration that re-seals published products?
- Should a later version add a transparency log or witness for checkpoints and key lists, to give freshness guarantees beyond the out-of-band channel?
