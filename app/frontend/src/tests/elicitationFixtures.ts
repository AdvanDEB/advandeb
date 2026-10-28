/**
 * Fixtures typed with the generated API types, so a server-side model change
 * that the client has not caught up with fails to compile here first.
 */
import type {
  CalibrationFeedback, CalibrationItem, CalibrationStatus, ElicitationProgress,
  Guidelines, QueueItem,
} from '@/types/elicitation.generated'

export function evidenceItem(n = 4, over: Partial<QueueItem> = {}): QueueItem {
  return {
    queue_position: 0,
    task: 'evidence',
    sf_number: 1216,
    statement: 'Embryos do not feed.',
    statement_sha256: 'a'.repeat(64),
    category: 'core_deb_rules',
    collection_version: '1.0',
    existing_provenance: null,
    existing_source_citation: null,
    legacy_assessment: null,
    repeated_judgment: true,
    n_required: 5,
    comparison_item: true,
    stratum: 'core_deb_rules|deb',
    corpus_id: 'deb',
    evidence_set_id: 'growth_11:deb',
    evidence_content_hash: 'h'.repeat(64),
    // Canonical indices deliberately not 0..n-1, so a client keying by
    // position instead of by index would be caught.
    passages: Array.from({ length: n }, (_, i) => ({
      index: i * 2 + 1,
      text: `passage text ${i}`,
      similarity: 0.9 - i / 100,
      doi: `10.1/${i}`,
      title: `Paper ${i}`,
      year: 2000 + i,
      document_id: `doc${i}`,
    })),
    n_passages_total: n,
    evidence_condition: 'matched',
    ...over,
  }
}

export function provenanceItem(over: Partial<QueueItem> = {}): QueueItem {
  return {
    ...evidenceItem(0),
    task: 'provenance',
    sf_number: 565,
    stratum: 'growth|provenance',
    corpus_id: null,
    evidence_set_id: null,
    evidence_content_hash: null,
    passages: [],
    n_passages_total: null,
    evidence_condition: 'expertise',
    repeated_judgment: false,
    n_required: 1,
    comparison_item: false,
    ...over,
  }
}

export const progress: ElicitationProgress = {
  calibration_required: false,
  calibration_completed: 2,
  calibration_total: 2,
  total_queue: 3910,
  completed: 0,
  completed_by_me: 0,
  median_seconds_per_item: null,
  by_task: {},
  by_stratum: {},
  repeated_judgments: 0,
  ladder_count: 0,
  ladder_basis: 'panel-tier judgments on the evidence task',
  rung: 'pre-R0',
  rung_note: 'Below the pilot volume — no claim is supported yet',
  next_rung_at: 60,
}

export function status(over: Partial<CalibrationStatus> = {}): CalibrationStatus {
  return { total: 2, completed: 0, correct: 0, done: false, available: true, ...over }
}

export function calibrationCase(i: number, over: Partial<CalibrationItem> = {}): CalibrationItem {
  return {
    calibration_id: `cal_provenance_${1201 + i}`,
    queue_position: -1,
    task: 'provenance',
    sf_number: 1201 + i,
    statement: `Calibration statement ${i}`,
    statement_sha256: 'c'.repeat(64),
    category: 'core_deb_rules',
    collection_version: '1.0',
    existing_provenance: null,
    existing_source_citation: null,
    legacy_assessment: null,
    repeated_judgment: false,
    n_required: 1,
    comparison_item: false,
    stratum: 'calibration',
    completed: i,
    total: 2,
    ...over,
  }
}

export function feedback(over: Partial<CalibrationFeedback> = {}): CalibrationFeedback {
  return {
    correct: false,
    reference: { provenance_type: 'published', basis: 'collection provenance record' },
    explanation: 'Documented in the collection.',
    completed: 1,
    total: 2,
    ...over,
  }
}

export const guidelines: Guidelines = { version: '1.1', tasks: [] }
