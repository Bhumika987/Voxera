// Mood scale — identical hexes as index.css's --color-mood-* tokens, referenced via
// var() so dynamic (data-driven) color picks don't depend on Tailwind's static class scan.
export const MOOD_VALUES = ['happy', 'neutral', 'confused', 'frustrated', 'angry']

const MOOD_VARS = {
  happy: 'var(--color-mood-happy)',
  neutral: 'var(--color-mood-neutral)',
  confused: 'var(--color-mood-confused)',
  frustrated: 'var(--color-mood-frustrated)',
  angry: 'var(--color-mood-angry)',
}

export function moodColor(mood) {
  return MOOD_VARS[mood] || MOOD_VARS.neutral
}

export function moodLabel(mood) {
  if (!mood) return 'Unknown'
  return mood[0].toUpperCase() + mood.slice(1)
}
