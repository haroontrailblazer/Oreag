/** Password strength rules used by sign-up and password reset. */
export const PASSWORD_RULES: {
  key: string
  label: string
  /** Compact label for the inline requirement chips. */
  short: string
  /** For the length rule: the target count, so the chip can show n/target live. */
  target?: number
  test: (p: string) => boolean
}[] = [
  {
    key: "length",
    label: "At least 12 characters",
    short: "characters",
    target: 12,
    test: (p) => p.length >= 12,
  },
  {
    key: "uppercase",
    label: "One uppercase letter",
    short: "Uppercase",
    test: (p) => /[A-Z]/.test(p),
  },
  {
    key: "special",
    label: "One special character",
    short: "Special character",
    test: (p) => /[^A-Za-z0-9]/.test(p),
  },
]

export function passwordFailures(password: string) {
  return PASSWORD_RULES.filter((r) => !r.test(password))
}
