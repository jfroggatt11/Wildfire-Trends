import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export type AttentionChartPoint = {
  date: string
  relativeDay: number
  [topicId: string]: string | number
}

type TopicDefinition = { id: string; label: string; color: string }

type TooltipEntry = { name: string; value: number; color: string }

type BoundaryLabelProps = {
  title: string
  date: string
  side: 'before' | 'after' | 'center'
  viewBox?: { x?: number; y?: number }
}

function BoundaryLabel({ title, date, side, viewBox }: BoundaryLabelProps) {
  const lineX = Number(viewBox?.x ?? 0)
  const top = Number(viewBox?.y ?? 0) + 11
  const x = side === 'before' ? lineX - 7 : side === 'after' ? lineX + 7 : lineX
  const textAnchor = side === 'before' ? 'end' : side === 'after' ? 'start' : 'middle'
  return (
    <text x={x} y={top} textAnchor={textAnchor} fill="#765e33" fontSize={9} fontWeight={650}>
      <tspan x={x}>{title}</tspan>
      <tspan x={x} dy={11} fontWeight={500}>{date}</tspan>
    </text>
  )
}

function ChartTooltip({
  active,
  payload,
  label,
  eventDuration,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  label?: number
  eventDuration: number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <strong>{label === 0 ? 'Event starts' : label === eventDuration ? 'Event ends' : `Day ${label && label > 0 ? '+' : ''}${label}`}</strong>
      {payload
        .filter((item) => item.value != null)
        .map((item) => (
          <span key={item.name}>
            <i style={{ background: item.color }} />
            {item.name}
            <b>{item.value}</b>
          </span>
        ))}
    </div>
  )
}

export default function AttentionChart({
  points,
  eventDuration,
  eventStartLabel,
  eventEndLabel,
  topics,
}: {
  points: AttentionChartPoint[]
  eventDuration: number
  eventStartLabel: string
  eventEndLabel: string
  topics: TopicDefinition[]
}) {
  const singleDayEvent = eventDuration === 0
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={points} margin={{ top: 16, right: 10, left: -24, bottom: 0 }}>
        <CartesianGrid stroke="#dce3df" strokeDasharray="3 4" vertical={false} />
        <XAxis
          dataKey="relativeDay"
          tick={{ fontSize: 11 }}
          tickFormatter={(value) => (value === 0 ? 'Event' : `${value > 0 ? '+' : ''}${value}d`)}
        />
        <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
        <Tooltip content={<ChartTooltip eventDuration={eventDuration} />} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
        {!singleDayEvent && <ReferenceArea x1={0} x2={eventDuration} fill="#e9c98a" fillOpacity={0.25} />}
        <ReferenceLine
          x={0}
          stroke="#aa7b2e"
          strokeDasharray="4 3"
          label={<BoundaryLabel title={singleDayEvent ? 'Event' : 'Starts'} date={eventStartLabel} side={singleDayEvent ? 'center' : 'before'} />}
        />
        {!singleDayEvent && <ReferenceLine
          x={eventDuration}
          stroke="#aa7b2e"
          strokeDasharray="4 3"
          label={<BoundaryLabel title="Ends" date={eventEndLabel} side="after" />}
        />}
        {topics.map((topic) => (
          <Line
            key={topic.id}
            type="monotone"
            dataKey={topic.id}
            name={topic.label}
            stroke={topic.color}
            strokeWidth={2}
            dot={points.length < 10}
            connectNulls={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
