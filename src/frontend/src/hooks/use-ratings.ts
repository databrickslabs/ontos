import { useState, useCallback, useRef } from 'react';
import { useApi } from './use-api';
import type { RatingAggregation } from '@/types/comments';

/**
 * Hook for fetching ratings for multiple entities efficiently
 * Uses a cache to avoid duplicate requests
 */
export function useRatings() {
  const { get } = useApi();
  const [ratingsCache, setRatingsCache] = useState<Record<string, RatingAggregation>>({});
  const [loadingEntities, setLoadingEntities] = useState<Set<string>>(new Set());
  const pendingRequests = useRef<Record<string, Promise<RatingAggregation | null>>>({});

  const getCacheKey = (entityType: string, entityId: string) => `${entityType}:${entityId}`;

  const fetchRating = useCallback(async (
    entityType: string,
    entityId: string
  ): Promise<RatingAggregation | null> => {
    const cacheKey = getCacheKey(entityType, entityId);

    // Return cached value if available
    if (ratingsCache[cacheKey]) {
      return ratingsCache[cacheKey];
    }

    // Return pending request if one exists
    const pendingRequest = pendingRequests.current[cacheKey];
    if (pendingRequest !== undefined) {
      return pendingRequest;
    }

    // Mark as loading
    setLoadingEntities(prev => new Set(prev).add(cacheKey));

    // Create the request promise
    const requestPromise = (async () => {
      try {
        const response = await get<RatingAggregation>(
          `/api/entities/${entityType}/${entityId}/ratings`
        );

        if (response.error || !response.data) {
          return null;
        }

        // Cache the result
        setRatingsCache(prev => ({
          ...prev,
          [cacheKey]: response.data,
        }));

        return response.data;
      } catch (error) {
        console.error(`Failed to fetch rating for ${entityType}/${entityId}:`, error);
        return null;
      } finally {
        // Clean up loading state
        setLoadingEntities(prev => {
          const next = new Set(prev);
          next.delete(cacheKey);
          return next;
        });
        // Clean up pending request
        delete pendingRequests.current[cacheKey];
      }
    })();

    // Store the pending request
    pendingRequests.current[cacheKey] = requestPromise;

    return requestPromise;
  }, [get, ratingsCache]);

  const getRating = useCallback((entityType: string, entityId: string): RatingAggregation | undefined => {
    const cacheKey = getCacheKey(entityType, entityId);
    return ratingsCache[cacheKey];
  }, [ratingsCache]);

  const isLoading = useCallback((entityType: string, entityId: string): boolean => {
    const cacheKey = getCacheKey(entityType, entityId);
    return loadingEntities.has(cacheKey);
  }, [loadingEntities]);

  const invalidate = useCallback((entityType: string, entityId: string) => {
    const cacheKey = getCacheKey(entityType, entityId);
    setRatingsCache(prev => {
      const next = { ...prev };
      delete next[cacheKey];
      return next;
    });
  }, []);

  const clearCache = useCallback(() => {
    setRatingsCache({});
  }, []);

  return {
    fetchRating,
    getRating,
    isLoading,
    invalidate,
    clearCache,
    ratingsCache,
  };
}

export default useRatings;

