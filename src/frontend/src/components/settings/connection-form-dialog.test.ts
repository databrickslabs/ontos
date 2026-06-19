/**
 * Unit tests for connection-form-dialog config-field helpers.
 *
 * These cover the config-building logic that determines which credential /
 * config fields are persisted per connector type. The full dialog itself
 * relies on Radix UI components that hang in jsdom, so the testable logic is
 * extracted into pure functions (see role-form-dialog.test.tsx for context).
 *
 * Regression: ONT-FEAT-029 — selecting "Snowflake" in Add Connection showed no
 * credential/config fields because the Snowflake connector type was missing
 * from the form's config-field map. These tests lock in that Snowflake exposes
 * its credential/config fields just like BigQuery.
 */
import { describe, it, expect } from 'vitest';
import {
  CONNECTOR_CONFIG_FIELDS,
  buildConnectionConfig,
} from './connection-form-dialog';

describe('CONNECTOR_CONFIG_FIELDS', () => {
  it('exposes BigQuery config fields', () => {
    expect(CONNECTOR_CONFIG_FIELDS.bigquery).toEqual([
      'project_id',
      'location',
      'uc_connection_name',
      'credentials_secret_scope',
      'credentials_secret_key',
      'credentials_path',
    ]);
  });

  it('exposes Snowflake credential/config fields (ONT-FEAT-029)', () => {
    // The defect was that this entry did not exist, so the form rendered no
    // credential fields for Snowflake.
    expect(CONNECTOR_CONFIG_FIELDS.snowflake).toBeDefined();
    expect(CONNECTOR_CONFIG_FIELDS.snowflake).toEqual([
      'account',
      'user',
      'warehouse',
      'database',
      'default_schema',
      'role',
    ]);
  });
});

describe('buildConnectionConfig', () => {
  it('includes only non-empty Snowflake fields', () => {
    const config = buildConnectionConfig('snowflake', {
      name: 'Prod SF',
      connector_type: 'snowflake',
      account: 'myorg-myaccount',
      user: 'ONTOS_SVC',
      warehouse: 'COMPUTE_WH',
      database: '',
      default_schema: 'PUBLIC',
      role: '',
      // BigQuery fields present in the shared form state must be ignored.
      project_id: 'should-not-leak',
    });

    expect(config).toEqual({
      account: 'myorg-myaccount',
      user: 'ONTOS_SVC',
      warehouse: 'COMPUTE_WH',
      default_schema: 'PUBLIC',
    });
    expect(config).not.toHaveProperty('project_id');
    expect(config).not.toHaveProperty('database');
    expect(config).not.toHaveProperty('role');
  });

  it('includes only non-empty BigQuery fields', () => {
    const config = buildConnectionConfig('bigquery', {
      connector_type: 'bigquery',
      project_id: 'my-gcp-project',
      location: 'US',
      uc_connection_name: '',
      // Snowflake fields present in shared form state must be ignored.
      account: 'should-not-leak',
    });

    expect(config).toEqual({
      project_id: 'my-gcp-project',
      location: 'US',
    });
    expect(config).not.toHaveProperty('account');
  });

  it('returns an empty config for connector types without field hints', () => {
    expect(buildConnectionConfig('databricks', { account: 'x' })).toEqual({});
    expect(buildConnectionConfig('unknown', { foo: 'bar' })).toEqual({});
  });
});
