"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/**
 * What each source actually provides, fetched from the backend's single
 * declaration (`app/sources/profiles.py`) rather than duplicated here.
 *
 * The dashboard used to draw a rating axis for every source, including
 * ones that have no ratings — YouTube's rating chart was permanently
 * empty, and with two rating-bearing sources the endpoint's
 * `(source, rating)` grouping produced silently overlapping x-values.
 * Panels are now chosen from these profiles, so a chart can only appear
 * where the underlying field exists.
 */
export type SourceProfile = {
  id: string;
  label: string;
  doc_types: string[];
  rating: { scale: number; label: string } | null;
  engagement: { key: string; label: string; extras: string[][] } | null;
  threaded: boolean;
  verified_purchase: boolean;
  subject_label: string | null;
  product_id_label: string | null;
  variant_label: string | null;
  notes: string | null;
};

export type ProfilesResponse = {
  profiles: SourceProfile[];
  comparable_dimensions: string[];
};

/** Used when a source has no declared profile — shows only the fields
 *  every document is guaranteed to have, rather than guessing. */
export const FALLBACK_PROFILE: Omit<SourceProfile, "id" | "label"> = {
  doc_types: [],
  rating: null,
  engagement: null,
  threaded: false,
  verified_purchase: false,
  subject_label: null,
  product_id_label: null,
  variant_label: null,
  notes: null,
};

export function useSourceProfiles() {
  return useQuery({
    queryKey: ["source-profiles"],
    // These are static facts about connectors, not per-project data —
    // they never change while the app is open.
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error } = await api.GET("/sources/profiles");
      if (error) throw error;
      return data as ProfilesResponse;
    },
  });
}

export function profileFor(
  profiles: SourceProfile[] | undefined,
  source: string
): SourceProfile {
  const found = profiles?.find((p) => p.id === source);
  if (found) return found;
  return { id: source, label: source, ...FALLBACK_PROFILE };
}
