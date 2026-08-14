import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
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

const TOPICS = [
  { id: 'climate_change', label: 'Climate change', color: '#286e59' },
  { id: 'clean_transport', label: 'Clean transport', color: '#d56743' },
  { id: 'electric_vehicles', label: 'Electric vehicles', color: '#6575b7' },
  { id: 'clean_energy', label: 'Clean energy', color: '#c59a2b' },
]

type TooltipEntry = { name: string; value: number; color: string }

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  label?: number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <strong>{label === 0 ? 'Event starts' : `Day ${label && label > 0 ? '+' : ''}${label}`}</strong>
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
}: {
  points: AttentionChartPoint[]
  eventDuration: number
}) {
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
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
        <ReferenceArea x1={0} x2={eventDuration} fill="#e9c98a" fillOpacity={0.22} />
        {TOPICS.map((topic) => (
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
