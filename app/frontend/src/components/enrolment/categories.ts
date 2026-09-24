/**
 * The twelve stylized-fact categories, as they appear in collection v1.0.
 *
 * Per-category familiarity is the operationally useful part of the expertise
 * profile (advandeb_methods/docs/10 §6): it lets reliability be reported
 * against *stated* expertise, which answers "do people who say they know this
 * area agree more?" — a question the paper asks of both strata.
 *
 * Keys must match `category` on the stylized_facts collection exactly, since
 * they are stored on the profile and later joined against elicitation records.
 */
export interface SfCategory {
  key: string
  label: string
}

export const SF_CATEGORIES: SfCategory[] = [
  { key: 'universal_laws_of_biological_organization', label: 'Universal laws of biological organization' },
  { key: 'ecological_physiological_proportions_and_relationships', label: 'Ecological–physiological proportions' },
  { key: 'temporal_characteristics_of_development_and_growth', label: 'Development and growth over time' },
  { key: 'reproductive_strategy', label: 'Reproductive strategy' },
  { key: 'metabolism_and_environment', label: 'Metabolism and environment' },
  { key: 'biological_experiments_and_data_patterns', label: 'Experiments and data patterns' },
  { key: 'dynamic_properties_and_equilibrium_states', label: 'Dynamics and equilibrium states' },
  { key: 'molecular_and_cellular_foundations', label: 'Molecular and cellular foundations' },
  { key: 'microbiological_and_parasitological_aspects', label: 'Microbiology and parasitology' },
  { key: 'thermoregulation_and_biophysical_constraints', label: 'Thermoregulation and biophysics' },
  { key: 'integrative_aspects_and_emergent_properties', label: 'Integrative and emergent properties' },
  { key: 'toxicology_and_ecotoxicology', label: 'Toxicology and ecotoxicology' },
]

/** Familiarity scale labels — 1–5, anchored so the ends mean something. */
export const FAMILIARITY_LABELS: Record<number, string> = {
  1: 'Not my area',
  2: 'Passing familiarity',
  3: 'Comfortable',
  4: 'Work in this area',
  5: 'Specialist',
}

export function prettyCategory(key: string): string {
  return SF_CATEGORIES.find(c => c.key === key)?.label
    || (key || '').replace(/_/g, ' ')
}
