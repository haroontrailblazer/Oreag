/** Password strength rules used by sign-up and password reset. */
export const PASSWORD_RULES: { label: string; test: (p: string) => boolean }[] = [
  { label: "At least 12 characters", test: (p) => p.length >= 12 },
  { label: "One uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "One special character", test: (p) => /[^A-Za-z0-9]/.test(p) },
]

export function passwordFailures(password: string) {
  return PASSWORD_RULES.filter((r) => !r.test(password))
}
