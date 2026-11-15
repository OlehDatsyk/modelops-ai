/** Client-side mirror of the backend password policy (the backend remains authoritative). */
export function passwordIssues(pw: string): string[] {
  const issues: string[] = []
  if (pw.length < 10) issues.push('at least 10 characters')
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length
  if (classes < 3) issues.push('three of: lowercase, uppercase, digit, symbol')
  return issues
}
