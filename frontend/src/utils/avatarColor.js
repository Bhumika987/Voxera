export function getAvatarColor(name) {
  const colors = ['#D4536F', '#5B8DEF', '#3FBF7F', '#B5790C', '#8B69D4', '#2F9E9E', '#E0793E', '#4A90A4']
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}
