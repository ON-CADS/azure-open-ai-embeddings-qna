# GitHub Copilot - Instructions

These instructions apply when GitHub copilot is reviewing code.

## General Principles
- Identify potential bugs, edge cases, and incorrect assumptions.
- Flag code and infra security risks (input validation,auth checks,secrets handling).
- Provide fixes abd code refactoring suggestions for the raised issues.
- Check if test cases are added in the repository or not.
- Ensure that all edge cases are handled in the test cases and add the missing ones.
- Execute all these test cases and validate if all test cases are passed or not.

## Language & Style:
- Match the naming conventions already present in the codebase.
- Do not introduce new frameworks unless neccessary.

## What to Avoid
- Style only feedbcak with no functional impact.
- Raising hypothetical issues without clear evidence.
- Repeating obvious information already clear from the code.

## Output Style
- Be concise and actionable.
- Use bullet points for listing multiple issues.
- Provide concrete suggestions and examples when possible.