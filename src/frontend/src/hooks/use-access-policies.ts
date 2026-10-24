import { useCallback, useEffect, useState } from 'react';
import { useApi } from '@/hooks/use-api';
import type { AccessCollection, OdrlProfile, ReleaseTargets } from '@/types/access-policy';

let profileCache: OdrlProfile | null = null;

/** The Ontos ODRL profile vocabulary (actions, left operands, operators); cached per session. */
export function useOdrlProfile() {
  const { get } = useApi();
  const [profile, setProfile] = useState<OdrlProfile | null>(profileCache);

  useEffect(() => {
    if (profileCache) return;
    let cancelled = false;
    get<OdrlProfile>('/api/access-policies/profile').then((res) => {
      if (!cancelled && res.data && !res.error) {
        profileCache = res.data;
        setProfile(res.data);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [get]);

  return profile;
}

/** Audiences + asset collections (one row per family) for pickers and IRI -> name lookups. */
export function useAccessCollections() {
  const { get } = useApi();
  const [audiences, setAudiences] = useState<AccessCollection[]>([]);
  const [assetCollections, setAssetCollections] = useState<AccessCollection[]>([]);

  const reload = useCallback(async () => {
    const [a, c] = await Promise.all([
      get<AccessCollection[]>('/api/access-policies/audiences'),
      get<AccessCollection[]>('/api/access-policies/asset-collections'),
    ]);
    setAudiences(Array.isArray(a.data) ? a.data : []);
    setAssetCollections(Array.isArray(c.data) ? c.data : []);
  }, [get]);

  useEffect(() => {
    reload();
  }, [reload]);

  const nameForIri = useCallback(
    (iri: string): string | null =>
      audiences.find((x) => x.uid === iri)?.name ?? assetCollections.find((x) => x.uid === iri)?.name ?? null,
    [audiences, assetCollections],
  );

  return { audiences, assetCollections, nameForIri, reload };
}

/** Targets releases can compile for (active Access Targets or the built-in UC target) + Delivery Modes. */
export function useCompileTargets() {
  const { get } = useApi();
  const [data, setData] = useState<ReleaseTargets | null>(null);

  useEffect(() => {
    let cancelled = false;
    get<ReleaseTargets>('/api/access-policies/compile-targets').then((res) => {
      if (!cancelled && res.data && !res.error) setData(res.data);
    });
    return () => {
      cancelled = true;
    };
  }, [get]);

  return data;
}
