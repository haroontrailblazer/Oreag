import { ImageResponse } from "next/og"

// Route metadata — Next wires these into og:image / twitter:image.
export const alt = "Oreag — RAG & Memory as a Service"
export const size = { width: 1200, height: 630 }
export const contentType = "image/png"

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #1f1f23 0%, #0a0a0a 100%)",
          color: "#ffffff",
          fontFamily: "sans-serif",
          padding: "80px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "28px" }}>
          <div
            style={{
              width: "104px",
              height: "104px",
              borderRadius: "26px",
              background: "#ffffff",
              color: "#0a0a0a",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "62px",
              fontWeight: 800,
            }}
          >
            O
          </div>
          <div
            style={{
              display: "flex",
              fontSize: "96px",
              fontWeight: 800,
              letterSpacing: "-3px",
            }}
          >
            Oreag
          </div>
        </div>

        <div
          style={{
            display: "flex",
            marginTop: "36px",
            fontSize: "38px",
            color: "#a1a1aa",
            textAlign: "center",
            maxWidth: "900px",
          }}
        >
          RAG &amp; Memory as a Service — turn your documents into a queryable API
        </div>

        <div style={{ display: "flex", gap: "16px", marginTop: "44px" }}>
          {["BYOK", "pgvector", "Memory Graph"].map((t) => (
            <div
              key={t}
              style={{
                display: "flex",
                padding: "12px 26px",
                borderRadius: "9999px",
                border: "1px solid #3f3f46",
                color: "#e4e4e7",
                fontSize: "28px",
              }}
            >
              {t}
            </div>
          ))}
        </div>
      </div>
    ),
    { ...size }
  )
}
