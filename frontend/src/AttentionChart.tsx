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
        {!singleDayEvent && <ReferenceArea x1={0} x2={eventDuration} fill="#e9c98a" fillOpacity={0.25} label={{ value: 'Event duration', position: 'insideTop', fill: '#765e33', fontSize: 9 }} />}
        <ReferenceLine
          x={0}
          stroke="#aa7b2e"
          strokeDasharray="4 3"
          label={{ value: singleDayEvent ? `Event · ${eventStartLabel}` : `Starts · ${eventStartLabel}`, position: 'insideTopLeft', fill: '#765e33', fontSize: 9 }}
        />
        {!singleDayEvent && <ReferenceLine
          x={eventDuration}
          stroke="#aa7b2e"
          strokeDasharray="4 3"
          label={{ value: `Ends · ${eventEndLabel}`, position: 'insideTopRight', fill: '#765e33', fontSize: 9 }}
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
