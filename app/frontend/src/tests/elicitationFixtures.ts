/**
 * Fixtures typed with the generated API types, so a server-side model change
 * that the client has not caught up with fails to compile here first.
 */
import type {
  CalibrationFeedback, CalibrationItem, CalibrationStatus, ElicitationProgress,
  EvidencePassage, Guidelines, PassageCitation, QueueItem,
} from '@/types/elicitation.generated'

export function citation(over: Partial<PassageCitation> = {}): PassageCitation {
  return {
    status: 'resolved',
    authors: ['Caroline Tolla', 'Sebastiaan A.L.M. Kooijman', 'Jean-Christophe Poggiale'],
    year: 2007,
    title: 'A kinetic inhibition mechanism for maintenance',
    journal: 'Journal of Theoretical Biology',
    doi: '10.1016/j.jtbi.2006.09.001',
    pages: null,
    file_name: null,
    library_id: '2674',
    ...over,
  }
}

export const unresolvedCitation: PassageCitation = citation({
  status: 'unresolved', authors: [], year: null, title: null, journal: null,
  doi: null, file_name: 'Kooy93.pdf', library_id: '2801',
})

function passages(n: number): EvidencePassage[] {
  // Canonical indices deliberately not 0..n-1, so a client keying by
  // position instead of by index would be caught.
  return Array.from({ length: n }, (_, i) => ({
    index: i * 2 + 1,
    text: `passage text ${i}`,
    similarity: 0.9 - i / 100,
    doi: null,
    title: `file${i}.pdf`,
    year: null,
    document_id: `${2670 + i}`,
    citation: i === 1 ? unresolvedCitation : citation(),
  }))
}

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
    passages: passages(n),
    n_passages_total: n,
    evidence_condition: 'matched',
    ...over,
  }
}

export const progress: ElicitationProgress = {
  calibration_required: false,
  calibration_completed: 0,
  calibration_total: 0,
  calibration_version: null,
  total_queue: 124,
  completed: 0,
  completed_by_me: 3,
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
  return {
    total: 2, completed: 0, correct: 0, done: false, available: true,
    required: true, version: 1, ...over,
  }
}

export const noCalibration: CalibrationStatus = {
  total: 0, completed: 0, correct: 0, done: false, available: false,
  required: false, version: null,
}

export function calibrationCase(i: number, over: Partial<CalibrationItem> = {}): CalibrationItem {
  return {
    calibration_id: `v1:${1201 + i}:deb`,
    version: 1,
    sf_number: 1201 + i,
    statement: `Calibration statement ${i}`,
    statement_sha256: 'c'.repeat(64),
    category: 'core_deb_rules',
    corpus_id: 'deb',
    evidence_set_id: `${1201 + i}:deb`,
    evidence_content_hash: 'h'.repeat(64),
    passages: passages(2),
    n_passages_total: 2,
    completed: i,
    total: 2,
    ...over,
  }
}

export function feedback(over: Partial<CalibrationFeedback> = {}): CalibrationFeedback {
  return {
    correct: false,
    strength_matches: true,
    consensus_matches: false,
    passages_compared: 1,
    passages_agreed: 1,
    reference: {
      evidence_strength: 2, consensus_direction: 3,
      passage_directions: { 1: 'supports' },
      explanation: 'Passage 1 reports the measurement; the rest restate it.',
    },
    completed: 1,
    total: 2,
    ...over,
  }
}

export const guidelines: Guidelines = {
  version: '2.0',
  tasks: [],
  how_it_works: [
    'You see one stylized fact at a time, with the passages our search found for it.',
    'Label every passage, then judge the fact from the passages AND what you know.',
  ],
}
