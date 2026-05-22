'use client';

import { useEffect, useRef } from 'react';
import { createChart, CandlestickSeries, IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useMarketStore } from '@/store/marketStore';

export function CandlestickChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const candles = useMarketStore((s) => s.candles);
  const initialized = useRef(false);

  useEffect(() => {
    if (!containerRef.current || initialized.current) return;
    initialized.current = true;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#080808' },
        textColor: '#6b7280',
      },
      grid: {
        vertLines: { color: '#111' },
        horzLines: { color: '#111' },
      },
      crosshair: {
        vertLine: { color: '#374151', labelBackgroundColor: '#1f2937' },
        horzLine: { color: '#374151', labelBackgroundColor: '#1f2937' },
      },
      timeScale: {
        borderColor: '#1f2937',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: '#1f2937' },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    const initialData = useMarketStore.getState().candles;
    series.setData(initialData.map((c) => ({ ...c, time: c.time as Time })));
    chart.timeScale().fitContent();

    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      initialized.current = false;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;
    try {
      const last = candles[candles.length - 1];
      seriesRef.current.update({ ...last, time: last.time as Time });
    } catch {
      seriesRef.current.setData(
        [...candles].sort((a, b) => a.time - b.time).map((c) => ({ ...c, time: c.time as Time }))
      );
    }
  }, [candles]);

  return <div ref={containerRef} className="w-full h-full" />;
}
