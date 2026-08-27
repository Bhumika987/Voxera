export default function Card({ title, icon: Icon, children, className = '' }) {
  return (
    <section className={`rounded-lg border border-app-border bg-app-panel p-4 ${className}`}>
      {title && (
        <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-app-text-secondary">
          {Icon && <Icon size={13} />}
          {title}
        </h3>
      )}
      {children}
    </section>
  )
}
