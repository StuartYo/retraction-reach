# Design notes (web demo)

Who uses it: a researcher, systematic-review author or journal editor checking a reference list before submission. Not a developer tool, so the main screen is one table of references with a status column, and the detail opens in place.

The one result a judge should see in the first screen: "a direct check flags N; two citation layers flag N + M", side by side, then the rows that explain the difference.

Starting point: the Stripe dashboard pattern (dense tables, neutral surfaces, one dark action colour, status chips that carry meaning), chosen because the job is reviewing a list of records, like reviewing payments.

- Type: IBM Plex Sans for text, IBM Plex Mono for DOIs, scores and timings. Sizes 12 / 13.5 / 15 / 22 / 40.
- Colour: ink `#16202e` is the only action colour. Status colours are used for status only: retracted `#b3122e`, check `#9a5200` on `#fdf0dc`, note `#3f5a78` on `#e8eef5`, clear `#4d6b55`, not visible `#7b7f86` dashed. Canvas `#f2f3f1`, surfaces white, lines `#dfe2e6`.
- Radius: 4px (inputs, chips, path nodes), 8px (panels, tables), pill only for the count strip.
- Status is never colour alone: every chip has a word, "not visible" uses a dashed border.
- Layout: 320px input column + results column at 1440; one column below 900px; path chains turn vertical on phones.
- No gradients, no glow, no icon-only buttons, no entrance animations.
