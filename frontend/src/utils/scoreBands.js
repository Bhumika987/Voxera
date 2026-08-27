// Attention-score bands. Max realistic score from attention_score.py's rules is 95
// (30+20+15+15+10+5), formally capped at 100 — "critical" covers both.
const SCORE_VARS = {
  critical: 'var(--color-score-critical)',
  high: 'var(--color-score-high)',
  watch: 'var(--color-score-watch)',
  normal: 'var(--color-score-normal)',
}

const SCORE_LABELS = {
  critical: 'Critical',
  high: 'High',
  watch: 'Watch',
  normal: 'Normal',
}

export function getScoreBand(score) {
  if (score == null) return 'normal'
  if (score >= 70) return 'critical'
  if (score >= 40) return 'high'
  if (score >= 20) return 'watch'
  return 'normal'
}

export function scoreColor(score) {
  return SCORE_VARS[getScoreBand(score)]
}

export function scoreBandLabel(score) {
  return SCORE_LABELS[getScoreBand(score)]
}
