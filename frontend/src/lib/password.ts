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
  // lowercase + number exist to MATCH Supabase's server-side
  // password_required_characters, which is a fixed enum of character classes:
  // its strictest value demands lower, upper, digit and symbol together, and
  // there is no "upper + symbol only" option to pick instead.
  //
  // Client and server must ask for exactly the same thing. If the server were
  // stricter, someone would satisfy every rule on this form and still be
  // refused by Supabase with an error the form never predicted - and the
  // browser talks to Supabase directly, so our backend cannot soften that.
  {
    key: "lowercase",
    label: "One lowercase letter",
    short: "Lowercase",
    test: (p) => /[a-z]/.test(p),
  },
  {
    key: "number",
    label: "One number",
    short: "Number",
    test: (p) => /[0-9]/.test(p),
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
