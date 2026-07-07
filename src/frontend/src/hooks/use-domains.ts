import { useState, useEffect, useCallback, useMemo } from 'react'
import { DataDomain } from '@/types/data-domain'

interface DomainsState {
  domains: DataDomain[]
  loading: boolean
  error: string | null
}

let globalDomainsCache: DataDomain[] | null = null
let globalCachePromise: Promise<DataDomain[]> | null = null
let cachedServerVersion: number | null = null

// Persist server and domain cache versions to survive HMR/frontend reloads
const SERVER_VERSION_KEY = 'ucapp_server_cache_version'
const DOMAINS_VERSION_KEY = 'ucapp_domains_cache_version'

// Hydrate cachedServerVersion from localStorage on module load
try {
  const stored = typeof window !== 'undefined' ? window.localStorage.getItem(SERVER_VERSION_KEY) : null
  if (stored != null) {
    const parsed = Number(stored)
    if (!Number.isNaN(parsed)) {
      cachedServerVersion = parsed
    }
  }
} catch {
  // Ignore storage access errors
}

const checkCacheVersion = async (): Promise<boolean> => {
  try {
    const response = await fetch('/api/cache-version')
    if (!response.ok) {
      // If we can't get cache version, treat existing in-memory cache as stale to be safe
      return false
    }
    const data = await response.json()
    const serverVersion = data.version

    // Persist latest seen server version
    cachedServerVersion = serverVersion
    try {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(SERVER_VERSION_KEY, String(serverVersion))
      }
    } catch {
      // Ignore storage access errors
    }

    // Compare the domains cache version with server version
    let storedDomainsVersion: number | null = null
    try {
      const stored = typeof window !== 'undefined' ? window.localStorage.getItem(DOMAINS_VERSION_KEY) : null
      if (stored != null) {
        const parsed = Number(stored)
        if (!Number.isNaN(parsed)) {
          storedDomainsVersion = parsed
        }
      }
    } catch {
      // Ignore storage access errors
    }

    // If we have a domains cache in memory but no stored version, treat as stale
    if (globalDomainsCache && storedDomainsVersion === null) {
      return false
    }

    // Otherwise, valid only if versions match
    return storedDomainsVersion === serverVersion
  } catch (error) {
    // If cache version check fails, be conservative: mark as stale
    return false
  }
}

const invalidateCache = () => {
  globalDomainsCache = null
  cachedServerVersion = null
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(DOMAINS_VERSION_KEY)
      // Do not remove server version; it reflects last seen server boot
    }
  } catch {
    // Ignore storage access errors
  }
}

export const useDomains = () => {
  const [state, setState] = useState<DomainsState>({
    domains: globalDomainsCache || [],
    loading: globalDomainsCache === null,
    error: null,
  })

  const fetchDomains = useCallback(async (): Promise<DataDomain[]> => {
    // Return existing promise if fetch is already in progress
    if (globalCachePromise) {
      return globalCachePromise
    }

    // Check cache version before using cached data
    if (globalDomainsCache) {
      const isCacheValid = await checkCacheVersion()
      if (isCacheValid) {
        return globalDomainsCache
      } else {
        // Cache is stale, invalidate it
        invalidateCache()
      }
    }

    // Create new fetch promise
    globalCachePromise = (async () => {
      try {
        const response = await fetch('/api/data-domains')
        if (!response.ok) {
          throw new Error(`Failed to fetch domains: ${response.status} ${response.statusText}`)
        }
        const data = await response.json()
        const domains = data || []

        // Cache the result and update cache version
        globalDomainsCache = domains

        // Update cached server version
        try {
          const versionResponse = await fetch('/api/cache-version')
          if (versionResponse.ok) {
            const versionData = await versionResponse.json()
            cachedServerVersion = versionData.version
            // Persist both server version and domains cache version
            try {
              if (typeof window !== 'undefined') {
                window.localStorage.setItem(SERVER_VERSION_KEY, String(cachedServerVersion))
                window.localStorage.setItem(DOMAINS_VERSION_KEY, String(cachedServerVersion))
              }
            } catch {
              // Ignore storage access errors
            }
          }
        } catch (error) {
          // If cache version update fails, continue without it
        }

        return domains
      } catch (error) {
        // Clear the promise on error so next call can retry
        globalCachePromise = null
        throw error
      } finally {
        // Clear the promise when done
        globalCachePromise = null
      }
    })()

    return globalCachePromise
  }, [])

  const loadDomains = useCallback(async () => {
    if (globalDomainsCache) {
      // Check cache version before using cached data
      const isCacheValid = await checkCacheVersion()
      if (isCacheValid) {
        // Use cached data immediately
        setState({
          domains: globalDomainsCache,
          loading: false,
          error: null,
        })
        return
      } else {
        // Cache is stale, invalidate and refetch
        invalidateCache()
      }
    }

    setState(prev => ({ ...prev, loading: true, error: null }))

    try {
      const domains = await fetchDomains()
      setState({
        domains,
        loading: false,
        error: null,
      })
    } catch (error) {
      setState({
        domains: [],
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch domains',
      })
    }
  }, [fetchDomains])

  // Load domains on first use
  useEffect(() => {
    if (!globalDomainsCache) {
      loadDomains()
    }
  }, [loadDomains])

  // Memoized domain lookup function
  const getDomainName = useMemo(() => {
    const domainMap = new Map(state.domains.map(domain => [domain.id, domain.name]))
    
    return (domainId: string | undefined | null): string | null => {
      if (!domainId) return null
      return domainMap.get(domainId) || null
    }
  }, [state.domains])

  // Memoized domain lookup by name function
  const getDomainById = useMemo(() => {
    const domainMap = new Map(state.domains.map(domain => [domain.id, domain]))

    return (domainId: string | undefined | null): DataDomain | null => {
      if (!domainId) return null
      return domainMap.get(domainId) || null
    }
  }, [state.domains])

  // Memoized helper: resolve a list of domain IDs to their names (issue #520).
  // Unknown IDs are skipped; input order is preserved.
  const getDomainNames = useMemo(() => {
    const domainMap = new Map(state.domains.map(domain => [domain.id, domain.name]))

    return (domainIds: (string | null | undefined)[] | undefined | null): string[] => {
      if (!domainIds) return []
      return domainIds
        .map(id => (id ? domainMap.get(id) : undefined))
        .filter((name): name is string => Boolean(name))
    }
  }, [state.domains])

  // Memoized domain ID lookup by name function
  const getDomainIdByName = useMemo(() => {
    const domainNameMap = new Map(state.domains.map(domain => [domain.name.toLowerCase(), domain.id]))

    return (domainName: string | undefined | null): string | null => {
      if (!domainName) return null
      return domainNameMap.get(domainName.toLowerCase()) || null
    }
  }, [state.domains])

  return {
    domains: state.domains,
    loading: state.loading,
    error: state.error,
    getDomainName,
    getDomainNames,
    getDomainById,
    getDomainIdByName,
    refetch: loadDomains,
  }
}

// Test utility to reset module-level cache
export const __resetDomainsCache = () => {
  globalDomainsCache = null
  globalCachePromise = null
  cachedServerVersion = null
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(SERVER_VERSION_KEY)
      window.localStorage.removeItem(DOMAINS_VERSION_KEY)
    }
  } catch {
    // Ignore
  }
}