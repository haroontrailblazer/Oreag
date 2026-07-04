@AGENTS.md

## UI conventions

### Card + Table horizontal alignment (shadcn)

`CardHeader` / `CardTitle` / `CardDescription` use `px-6` (24px), but shadcn
`Table` cells (`TableHead` / `TableCell`) only use `px-2` (8px). So a `<Table>`
inside `<CardContent className="p-0">` renders ~16px to the **left** of the card
title - the columns won't line up with the heading.

**Always align a card-wrapped table to the header:** keep `CardContent` at
`p-0` (so row borders still span the full card width) and instead add
`pl-6` to the **first** column (its `TableHead` **and** every `TableCell`) and
`pr-6` to the **last** column (header + cells). This makes the first column line
up under the title and the trailing actions (e.g. an "Add" button) line up with
the description's right edge.

Applies to every Card-wrapped table - e.g. `components/settings/provider-keys.tsx`
and `components/project/api-tab.tsx`. Do this up front; don't ship mismatched
header-vs-table spacing.
