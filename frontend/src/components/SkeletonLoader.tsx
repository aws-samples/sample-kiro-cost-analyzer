import './SkeletonLoader.css';

type SkeletonVariant = 'cards' | 'table' | 'chart' | 'container' | 'key-value';

interface SkeletonLoaderProps {
  variant: SkeletonVariant;
  count?: number;
  height?: number;
  columns?: number;
}

function CardsVariant({ count, columns }: { count: number; columns: number }) {
  return (
    <div
      className="skeleton-cards"
      style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
      data-testid="skeleton-cards"
    >
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-block skeleton-card" />
      ))}
    </div>
  );
}

function TableVariant({ count }: { count: number }) {
  return (
    <div className="skeleton-table" data-testid="skeleton-table">
      {/* Header row */}
      <div className="skeleton-table-row">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="skeleton-block skeleton-table-header" />
        ))}
      </div>
      {/* Data rows */}
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-table-row">
          {Array.from({ length: 4 }, (_, j) => (
            <div key={j} className="skeleton-block skeleton-table-cell" />
          ))}
        </div>
      ))}
    </div>
  );
}

function ChartVariant({ height }: { height: number }) {
  return (
    <div
      className="skeleton-block skeleton-chart"
      style={{ height: `${height}px` }}
      data-testid="skeleton-chart"
    />
  );
}

function ContainerVariant() {
  return (
    <div className="skeleton-block skeleton-container" data-testid="skeleton-container">
      <div className="skeleton-container-inner">
        <div className="skeleton-block skeleton-container-line" style={{ width: '40%' }} />
        <div className="skeleton-block skeleton-container-line" style={{ width: '70%' }} />
        <div className="skeleton-block skeleton-container-line" style={{ width: '55%' }} />
      </div>
    </div>
  );
}

function KeyValueVariant({ count, columns }: { count: number; columns: number }) {
  return (
    <div
      className="skeleton-key-value"
      style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
      data-testid="skeleton-key-value"
    >
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-kv-pair">
          <div className="skeleton-block skeleton-kv-label" />
          <div className="skeleton-block skeleton-kv-value" />
        </div>
      ))}
    </div>
  );
}

export default function SkeletonLoader({
  variant,
  count = 3,
  height = 200,
  columns = 4,
}: SkeletonLoaderProps) {
  switch (variant) {
    case 'cards':
      return <CardsVariant count={count} columns={columns} />;
    case 'table':
      return <TableVariant count={count} />;
    case 'chart':
      return <ChartVariant height={height} />;
    case 'container':
      return <ContainerVariant />;
    case 'key-value':
      return <KeyValueVariant count={count} columns={columns} />;
  }
}

export type { SkeletonVariant, SkeletonLoaderProps };
