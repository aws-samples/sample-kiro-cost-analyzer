import { useRef, useEffect, useState } from 'react';
import { select } from 'd3-selection';
import { scaleLinear } from 'd3-scale';

interface FunnelChartData {
  label: string;
  value: number;
  percentage: number;
}

interface D3FunnelChartProps {
  data: FunnelChartData[];
  width?: number;
  height?: number;
  colors?: string[];
  showConversionRates?: boolean;
}

const DEFAULT_COLORS = [
  '#0972d3', // Cloudscape blue
  '#1b9e77', // teal
  '#5e6b7a', // slate
  '#7570b3', // muted purple
  '#2d8659', // forest green
];

export default function D3FunnelChart({
  data,
  width: propWidth,
  height: propHeight,
  colors = DEFAULT_COLORS,
  showConversionRates = true,
}: D3FunnelChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [containerWidth, setContainerWidth] = useState<number>(propWidth ?? 500);

  // Responsive: observe container width changes
  useEffect(() => {
    if (propWidth) {
      setContainerWidth(propWidth);
      return;
    }

    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const newWidth = entry.contentRect.width;
        if (newWidth > 0) {
          setContainerWidth(newWidth);
        }
      }
    });

    observer.observe(container);
    setContainerWidth(container.clientWidth || 500);

    return () => observer.disconnect();
  }, [propWidth]);

  // D3 rendering
  useEffect(() => {
    if (!svgRef.current || data.length === 0) return;

    const svg = select(svgRef.current);
    svg.selectAll('*').remove();

    const chartWidth = containerWidth;
    const segmentHeight = propHeight
      ? (propHeight - (showConversionRates ? (data.length - 1) * 24 : 0)) / data.length
      : 50;
    const conversionLabelHeight = showConversionRates ? 24 : 0;
    const totalHeight = propHeight ?? data.length * segmentHeight + (data.length - 1) * conversionLabelHeight;
    const padding = 20;
    const availableWidth = chartWidth - padding * 2;

    svg.attr('width', chartWidth).attr('height', totalHeight);

    // Scale width proportional to value relative to the first (widest) segment
    const maxValue = data[0]?.value ?? 1;
    const widthScale = scaleLinear()
      .domain([0, maxValue])
      .range([availableWidth * 0.2, availableWidth]);

    let yOffset = 0;

    data.forEach((item, index) => {
      const currentWidth = widthScale(item.value);
      const nextWidth = index < data.length - 1 ? widthScale(data[index + 1].value) : currentWidth * 0.8;

      const topLeft = (chartWidth - currentWidth) / 2;
      const topRight = topLeft + currentWidth;
      const bottomLeft = (chartWidth - nextWidth) / 2;
      const bottomRight = bottomLeft + nextWidth;

      // Build trapezoid path
      const path = `M ${topLeft} ${yOffset}
        L ${topRight} ${yOffset}
        L ${bottomRight} ${yOffset + segmentHeight}
        L ${bottomLeft} ${yOffset + segmentHeight}
        Z`;

      const color = colors[index % colors.length];

      // Draw trapezoid
      svg
        .append('path')
        .attr('d', path)
        .attr('fill', color)
        .attr('opacity', 0.85)
        .attr('class', 'funnel-segment');

      // Label: stage name + count centered on the segment
      const labelY = yOffset + segmentHeight / 2;
      svg
        .append('text')
        .attr('x', chartWidth / 2)
        .attr('y', labelY)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', 'var(--color-text-body-default, #ffffff)')
        .attr('font-size', '13px')
        .attr('font-weight', '600')
        .attr('class', 'funnel-label')
        .text(`${item.label} (${item.value.toLocaleString()})`);

      yOffset += segmentHeight;

      // Conversion rate label between segments
      if (showConversionRates && index < data.length - 1) {
        const nextItem = data[index + 1];
        const rate = nextItem.percentage;

        svg
          .append('text')
          .attr('x', chartWidth / 2)
          .attr('y', yOffset + conversionLabelHeight / 2)
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .attr('fill', 'var(--color-text-body-secondary, #5f6b7a)')
          .attr('font-size', '12px')
          .attr('class', 'funnel-conversion-label')
          .text(`${rate.toFixed(1)}%`);

        yOffset += conversionLabelHeight;
      }
    });
  }, [data, containerWidth, propHeight, colors, showConversionRates]);

  // Handle empty data
  if (!data || data.length === 0) {
    return (
      <div ref={containerRef} style={{ width: propWidth ?? '100%' }}>
        <svg ref={svgRef} aria-label="Empty funnel chart" />
      </div>
    );
  }

  const segmentHeight = propHeight
    ? (propHeight - (showConversionRates ? (data.length - 1) * 24 : 0)) / data.length
    : 50;
  const conversionLabelHeight = showConversionRates ? 24 : 0;
  const totalHeight = propHeight ?? data.length * segmentHeight + (data.length - 1) * conversionLabelHeight;

  return (
    <div ref={containerRef} style={{ width: propWidth ?? '100%' }}>
      <svg
        ref={svgRef}
        width={containerWidth}
        height={totalHeight}
        aria-label="Funnel chart"
        role="img"
      />
    </div>
  );
}
