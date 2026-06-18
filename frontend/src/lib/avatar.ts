/** Gravatar URL for an email (SHA-256; identicon fallback for unknown emails). */
export async function gravatarUrl(email: string, size = 160): Promise<string> {
  const normalized = email.trim().toLowerCase()
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(normalized)
  )
  const hash = Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
  return `https://www.gravatar.com/avatar/${hash}?d=identicon&s=${size}`
}
