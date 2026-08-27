// The "repeat contact" attention reason is the one case whose evidence lives in a
// DIFFERENT call, not a transcript moment in this one — attention_score.py writes it
// as `Repeat contact - previous call {call_id} on {date}` with evidence_segment_id: null.
const REPEAT_CONTACT_RE = /previous call ([0-9a-fA-F]+) on ([\d-]+)/

export function parseRepeatContact(reasonText) {
  if (!reasonText) return null
  const match = reasonText.match(REPEAT_CONTACT_RE)
  if (!match) return null
  return { callId: match[1], date: match[2] }
}
