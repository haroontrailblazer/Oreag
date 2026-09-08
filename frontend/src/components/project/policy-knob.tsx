"use client"

import { type PointerEvent, useRef } from "react"

import styles from "./policy-knob.module.css"

type PolicyKnobProps = {
  id: string
  label: string
  value: number
  min: number
  max: number
  step: number
  valueText?: string
  onChange: (value: string) => void
}

export function PolicyKnob({
  id, label, value, min, max, step, valueText, onChange,
}: PolicyKnobProps) {
  const current = Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : min
  const progress = (current - min) / (max - min)
  const drag = useRef<{ pointerId: number; angle: number; value: number; x: number; y: number } | null>(null)

  function update(next: number) {
    const snapped = min + Math.round((next - min) / step) * step
    onChange(String(Number(Math.min(max, Math.max(min, snapped)).toFixed(6))))
  }

  function angleAt(event: PointerEvent<HTMLDivElement>, x: number, y: number) {
    return Math.atan2(event.clientY - y, event.clientX - x) * 180 / Math.PI
  }

  return (
    <div className={styles.control}>
      <div
        id={id}
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={current}
        aria-valuetext={valueText ?? String(current)}
        aria-describedby={`${id}-hint`}
        className={styles.dial}
        onPointerDown={(event) => {
          if (!event.isPrimary || event.button !== 0) return
          const bounds = event.currentTarget.getBoundingClientRect()
          const x = bounds.left + bounds.width / 2
          const y = bounds.top + bounds.height / 2
          drag.current = { pointerId: event.pointerId, angle: angleAt(event, x, y), value: current, x, y }
          event.currentTarget.setPointerCapture(event.pointerId)
          event.currentTarget.focus()
        }}
        onPointerMove={(event) => {
          const active = drag.current
          if (!active || active.pointerId !== event.pointerId) return
          if ((event.buttons & 1) === 0) {
            drag.current = null
            return
          }
          // Ignore the centre, where a tiny movement can flip the angle.
          if (Math.hypot(event.clientX - active.x, event.clientY - active.y) < 12) return
          const angle = angleAt(event, active.x, active.y)
          const delta = ((angle - active.angle + 540) % 360) - 180
          active.angle = angle
          active.value = Math.min(max, Math.max(min, active.value + delta / 270 * (max - min)))
          update(active.value)
        }}
        onPointerUp={(event) => {
          if (drag.current?.pointerId !== event.pointerId) return
          drag.current = null
          event.currentTarget.releasePointerCapture(event.pointerId)
        }}
        onPointerCancel={() => { drag.current = null }}
        onLostPointerCapture={() => { drag.current = null }}
        onKeyDown={(event) => {
          let next: number
          switch (event.key) {
            case "ArrowUp": case "ArrowRight": next = current + step; break
            case "ArrowDown": case "ArrowLeft": next = current - step; break
            case "PageUp": next = current + step * 5; break
            case "PageDown": next = current - step * 5; break
            case "Home": next = min; break
            case "End": next = max; break
            default: return
          }
          event.preventDefault()
          update(next)
        }}
      >
        <svg className={styles.ticks} viewBox="0 0 160 160" aria-hidden="true">
          {Array.from({ length: 41 }, (_, index) => (
            <line
              key={index}
              x1="80" y1={index % 5 === 0 ? "6" : "9"} x2="80" y2="14"
              transform={`rotate(${-135 + index * 270 / 40} 80 80)`}
              className={index / 40 <= progress ? styles.activeTick : styles.tick}
              strokeWidth={index % 5 === 0 ? 1.8 : 1}
              strokeLinecap="round"
            />
          ))}
        </svg>
        <div className={styles.face} aria-hidden="true">
          <div className={styles.rotor} style={{ transform: `rotate(${-135 + progress * 270}deg)` }}>
            <span className={styles.indicator} />
          </div>
          <span className={styles.value}>{valueText ?? (step < 1 ? current.toFixed(2) : current)}</span>
        </div>
      </div>
      <p id={`${id}-hint`} className={styles.hint}>Drag to turn · Use arrow keys</p>
    </div>
  )
}
