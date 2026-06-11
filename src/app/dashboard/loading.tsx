export default function DashboardLoading() {
  return (
    <div className="space-y-6">
      <div className="h-8 w-64 bg-secondary rounded animate-pulse" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {[1,2,3,4,5].map(i => (
          <div key={i} className="h-20 bg-secondary rounded-xl animate-pulse" />
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {[1,2,3].map(i => (
          <div key={i} className="h-64 bg-secondary rounded-2xl animate-pulse" />
        ))}
      </div>
    </div>
  )
}
