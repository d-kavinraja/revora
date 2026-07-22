'use client';

import { useState } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { DailyCost } from '@/lib/api';

interface UsageChartProps {
  data: DailyCost[];
  isLoading?: boolean;
}

export function UsageChart({ data, isLoading }: UsageChartProps) {
  const [metric, setMetric] = useState<'cost_usd' | 'tokens'>('cost_usd');

  const formattedData = [...data].reverse().map(d => ({
    ...d,
    dateLabel: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
  }));

  const maxVal = Math.max(...data.map(d => d[metric] || 0));

  return (
    <div className="w-full rounded-xl border border-border bg-surface-1 p-5 backdrop-blur-md flex flex-col mb-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-bold text-foreground">Usage Trend</h2>
        <div className="flex bg-surface-2 p-1 rounded-lg border border-border">
          <button
            onClick={() => setMetric('cost_usd')}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${metric === 'cost_usd' ? 'bg-brand text-brand-foreground shadow' : 'text-muted-foreground hover:text-foreground'}`}
          >
            Cost (USD)
          </button>
          <button
            onClick={() => setMetric('tokens')}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${metric === 'tokens' ? 'bg-brand text-brand-foreground shadow' : 'text-muted-foreground hover:text-foreground'}`}
          >
            Tokens
          </button>
        </div>
      </div>
      
      <div className="w-full h-[300px]">
        {isLoading ? (
          <div className="w-full h-full flex items-center justify-center">
            <div className="animate-pulse flex space-x-4 w-full px-8">
               <div className="flex-1 space-y-4 py-1">
                 <div className="h-[200px] bg-surface-3 rounded w-full"></div>
               </div>
            </div>
          </div>
        ) : data.length === 0 ? (
          <div className="w-full h-full flex items-center justify-center text-sm text-muted-foreground">
            No data available for this period.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={formattedData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="colorMetric" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={metric === 'cost_usd' ? '#8b5cf6' : '#3b82f6'} stopOpacity={0.3}/>
                  <stop offset="95%" stopColor={metric === 'cost_usd' ? '#8b5cf6' : '#3b82f6'} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
              <XAxis 
                dataKey="dateLabel" 
                axisLine={false} 
                tickLine={false} 
                tick={{ fontSize: 12, fill: '#888' }} 
                dy={10}
                minTickGap={20}
              />
              <YAxis 
                hide 
                domain={[0, maxVal * 1.1]} 
              />
              <Tooltip 
                content={({ active, payload, label }) => {
                  if (active && payload && payload.length) {
                    const val = payload[0].value as number;
                    return (
                      <div className="bg-surface-2 border border-border p-3 rounded-lg shadow-xl backdrop-blur-md">
                        <p className="text-xs text-muted-foreground mb-1">{label}</p>
                        <p className="text-sm font-bold text-foreground">
                          {metric === 'cost_usd' ? `$${val.toFixed(4)}` : `${val.toLocaleString()} Tokens`}
                        </p>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Area 
                type="monotone" 
                dataKey={metric} 
                stroke={metric === 'cost_usd' ? '#8b5cf6' : '#3b82f6'} 
                strokeWidth={2}
                fillOpacity={1} 
                fill="url(#colorMetric)" 
                animationDuration={1000}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
