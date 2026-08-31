export function VoxeraLogo({ size = 32 }) {
  return (
    <svg
      width={size}
      height={size * 0.47}
      viewBox="0 0 120 56"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect x="2" y="26" width="4" height="4" rx="2" fill="#2A3040" />
      <rect x="10" y="20" width="4" height="16" rx="2" fill="#2A3040" />
      <rect x="18" y="10" width="4" height="36" rx="2" fill="#3A4252" />
      <rect x="26" y="16" width="4" height="24" rx="2" fill="#5B8DEF" />
      <rect x="34" y="8" width="4" height="40" rx="2" fill="#5B8DEF" />

      <g>
        <rect
          x="50"
          y="10"
          width="20"
          height="36"
          rx="6"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
        />
        <circle cx="60" cy="39.5" r="1.6" fill="currentColor" />
        <rect x="56" y="14" width="8" height="1.6" rx="0.8" fill="#3A4252" />
      </g>

      <rect x="82" y="8" width="4" height="40" rx="2" fill="#5B8DEF" />
      <rect x="90" y="16" width="4" height="24" rx="2" fill="#5B8DEF" />
      <rect x="98" y="10" width="4" height="36" rx="2" fill="#3A4252" />
      <rect x="106" y="20" width="4" height="16" rx="2" fill="#2A3040" />
      <rect x="114" y="26" width="4" height="4" rx="2" fill="#2A3040" />
    </svg>
  )
}

/** For use under 28px (sidebar rail, favicon) where the detailed mark would blur. */
export function VoxeraLogoCompact({ size = 24 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect x="2" y="15" width="4" height="10" rx="2" fill="#5B8DEF" />
      <rect x="10" y="10" width="4" height="20" rx="2" fill="#5B8DEF" />
      <rect
        x="16"
        y="6"
        width="8"
        height="28"
        rx="4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
      />
      <circle cx="20" cy="27" r="1.4" fill="currentColor" />
      <rect x="26" y="10" width="4" height="20" rx="2" fill="#5B8DEF" />
      <rect x="34" y="15" width="4" height="10" rx="2" fill="#5B8DEF" />
    </svg>
  )
}
